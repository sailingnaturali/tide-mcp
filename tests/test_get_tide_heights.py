from datetime import datetime, timezone

import httpx
import respx

from currents_mcp.cache import EventCache
from currents_mcp.client import RateLimitedClient
from currents_mcp.tools import _fmt_height, get_tide_heights

HEIGHT_STATIONS = [
    {"id": "AAA", "officialName": "Montague Harbour", "latitude": 48.76, "longitude": -123.05,
     "operating": True, "timeSeries": [{"code": "wlp-hilo"}]},
]
HILO_MAY26 = [
    {"eventDate": "2026-05-26T09:48:00Z", "value": 3.05},
    {"eventDate": "2026-05-26T16:31:00Z", "value": 1.24},
]
HILO_MAY27 = [
    {"eventDate": "2026-05-26T23:05:00Z", "value": 3.10},
    {"eventDate": "2026-05-27T05:30:00Z", "value": 0.85},
]


def _hilo_by_day(request):
    """Return the right per-UTC-day payload so n_days=2 fetches see distinct data."""
    from_str = request.url.params.get("from", "")
    if from_str.startswith("2026-05-26"):
        return httpx.Response(200, json=HILO_MAY26)
    if from_str.startswith("2026-05-27"):
        return httpx.Response(200, json=HILO_MAY27)
    return httpx.Response(200, json=[])


def test_fmt_height_string():
    # DISPLAY_TZ is America/Vancouver, so this is locale-independent.
    utc = datetime(2026, 5, 26, 16, 31, tzinfo=timezone.utc)
    assert _fmt_height(utc, "low", 1.24) == "Low 09:31 PDT — 1.2 m"


@respx.mock
async def test_get_tide_heights_shape(tmp_path):
    respx.get("https://api-sine.dfo-mpo.gc.ca/api/v1/stations").mock(
        return_value=httpx.Response(200, json=HEIGHT_STATIONS)
    )
    respx.get("https://api-sine.dfo-mpo.gc.ca/api/v1/stations/AAA/data").mock(
        side_effect=_hilo_by_day
    )
    cache = EventCache(str(tmp_path / "c.sqlite")); cache.init_schema()
    client = RateLimitedClient()
    result = await get_tide_heights(client, cache, lat=48.76, lon=-123.05, date="2026-05-26")
    await client.aclose(); cache.close()

    assert result["station_name"] == "Montague Harbour"
    assert result["distance_km"] >= 0
    # n_days=2 + filter to >= after returns the full local-day cycle, capped at 4.
    assert [e["type"] for e in result["events"]] == ["high", "low", "high", "low"]
    assert result["events"][1]["display"] == "Low 09:31 PDT — 1.2 m"
    assert result["events"][1]["height_m"] == 1.2
    assert result["events"][1]["utc"] == "2026-05-26T16:31:00Z"
    # summary names the NEXT extreme (the 02:48 PDT high), not a later low
    assert "Next high" in result["summary_display"]
    assert "Montague Harbour" in result["summary_display"]


@respx.mock
async def test_get_tide_heights_filters_past_events(tmp_path):
    # When `after` is mid-day, past events must not leak into the response.
    respx.get("https://api-sine.dfo-mpo.gc.ca/api/v1/stations").mock(
        return_value=httpx.Response(200, json=HEIGHT_STATIONS)
    )
    respx.get("https://api-sine.dfo-mpo.gc.ca/api/v1/stations/AAA/data").mock(
        side_effect=_hilo_by_day
    )
    cache = EventCache(str(tmp_path / "c.sqlite")); cache.init_schema()
    client = RateLimitedClient()
    # 18:00 UTC May 26 is after the 09:48Z high and 16:31Z low; only 23:05Z high and
    # May 27 05:30Z low remain in the future.
    result = await get_tide_heights(client, cache, lat=48.76, lon=-123.05,
                                    date="2026-05-26T18:00:00Z")
    await client.aclose(); cache.close()

    types = [e["type"] for e in result["events"]]
    assert types == ["high", "low"]
    assert result["events"][0]["utc"] == "2026-05-26T23:05:00Z"
    # Summary must point at a future event, not the morning low we filtered out.
    assert "16:31" not in result["summary_display"]


@respx.mock
async def test_get_tide_heights_no_events_is_honest(tmp_path):
    respx.get("https://api-sine.dfo-mpo.gc.ca/api/v1/stations").mock(
        return_value=httpx.Response(200, json=HEIGHT_STATIONS)
    )
    respx.get("https://api-sine.dfo-mpo.gc.ca/api/v1/stations/AAA/data").mock(
        return_value=httpx.Response(200, json=[])
    )
    cache = EventCache(str(tmp_path / "c.sqlite")); cache.init_schema()
    client = RateLimitedClient()
    result = await get_tide_heights(client, cache, lat=48.76, lon=-123.05, date="2026-05-26")
    await client.aclose(); cache.close()

    assert result["events"] == []
    assert "unavailable" in result["summary_display"].lower()
