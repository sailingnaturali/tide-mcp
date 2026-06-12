from datetime import datetime, timezone

import httpx
import pytest
import respx

from currents_mcp.providers import TideHeightEvent
from currents_mcp.tides_source import TidesClient

# Trimmed from a live /signalk/v2/api/tides/extremes response (Pi, 2026-06-12).
PAYLOAD = {
    "datum": "LAT",
    "units": "meters",
    "station": {"id": "ticon/montague-fake", "name": "Montague Harbour BC"},
    "distance": 1.42,
    "extremes": [
        # Deliberately unsorted: the client must sort by time.
        {"time": "2026-05-26T16:31:00.000Z", "level": 1.24, "high": False, "low": True, "label": "Low"},
        {"time": "2026-05-26T09:48:00.000Z", "level": 3.05, "high": True, "low": False, "label": "High"},
    ],
}

START = datetime(2026, 5, 26, 7, 0, tzinfo=timezone.utc)
END = datetime(2026, 5, 27, 19, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_extremes_parses_and_sorts_payload():
    c = TidesClient("http://signalk:3000", getter=lambda url, params: PAYLOAD)
    info, events = await c.extremes(48.76, -123.05, START, END)
    assert info == {"station_name": "Montague Harbour BC", "distance_km": 1}
    assert [(e.kind, e.height_m) for e in events] == [("high", 3.05), ("low", 1.24)]
    assert isinstance(events[0], TideHeightEvent)
    assert events[0].utc == datetime(2026, 5, 26, 9, 48, tzinfo=timezone.utc)
    assert c.unreachable is False


@pytest.mark.asyncio
async def test_extremes_passes_position_and_window_params():
    seen = {}
    def fake_get(url, params):
        seen.update(params)
        return PAYLOAD
    c = TidesClient("http://signalk:3000", getter=fake_get)
    await c.extremes(48.76, -123.05, START, END)
    assert seen == {
        "latitude": 48.76, "longitude": -123.05,
        "start": "2026-05-26T07:00:00Z", "end": "2026-05-27T19:00:00Z",
    }


@pytest.mark.asyncio
async def test_unreachable_server_degrades_and_flags():
    async def boom(url, params):
        raise httpx.ConnectError("nope")
    c = TidesClient("http://signalk:3000", getter=boom)
    info, events = await c.extremes(48.76, -123.05, START, END)
    assert (info, events) == (None, [])
    assert c.unreachable is True
    # A later successful call clears the flag.
    c._getter = lambda url, params: PAYLOAD
    info, _ = await c.extremes(48.76, -123.05, START, END)
    assert info is not None
    assert c.unreachable is False


@pytest.mark.asyncio
async def test_malformed_extreme_is_skipped_not_fatal(capsys):
    payload = {
        "station": {"name": "X"}, "distance": 0,
        "extremes": [
            {"time": "2026-05-26T09:48:00Z", "level": "not-a-number", "high": True, "low": False},
            {"time": "2026-05-26T16:31:00Z", "level": 1.24, "high": False, "low": True},
            {"level": 2.0, "high": True, "low": False},  # no time
        ],
    }
    c = TidesClient("http://signalk:3000", getter=lambda url, params: payload)
    _, events = await c.extremes(48.76, -123.05, START, END)
    assert [(e.kind, e.height_m) for e in events] == [("low", 1.24)]
    assert "skipping" in capsys.readouterr().err


@respx.mock
@pytest.mark.asyncio
async def test_http_get_url_encodes_timestamps():
    # The Neaps API rejects raw ':' in start/end — httpx params= must encode them.
    route = respx.get("http://signalk:3000/signalk/v2/api/tides/extremes").mock(
        return_value=httpx.Response(200, json=PAYLOAD)
    )
    c = TidesClient("http://signalk:3000")
    info, events = await c.extremes(48.76, -123.05, START, END)
    assert info["station_name"] == "Montague Harbour BC"
    raw_query = str(route.calls[0].request.url.query, "ascii")
    assert "2026-05-26T07%3A00%3A00Z" in raw_query
