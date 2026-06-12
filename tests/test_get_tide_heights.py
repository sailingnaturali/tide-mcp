from datetime import datetime, timezone

import httpx

from currents_mcp.tides_source import TidesClient
from currents_mcp.tools import _fmt_height, get_tide_heights

# Neaps-shaped extremes (see tides_source PAYLOAD); times chosen so the
# 2026-05-26 PDT local day (starts 07:00Z) holds five future events.
EXTREMES = [
    {"time": "2026-05-26T09:48:00.000Z", "level": 3.05, "high": True, "low": False, "label": "High"},
    {"time": "2026-05-26T16:31:00.000Z", "level": 1.24, "high": False, "low": True, "label": "Low"},
    {"time": "2026-05-26T23:05:00.000Z", "level": 3.10, "high": True, "low": False, "label": "High"},
    {"time": "2026-05-27T05:30:00.000Z", "level": 0.85, "high": False, "low": True, "label": "Low"},
    {"time": "2026-05-27T12:01:00.000Z", "level": 3.20, "high": True, "low": False, "label": "High"},
]


def _payload(extremes):
    return {"datum": "LAT", "units": "meters",
            "station": {"name": "Montague Harbour BC"},
            "distance": 1.42, "extremes": extremes}


def _tides(extremes):
    return TidesClient("http://signalk:3000",
                       getter=lambda url, params: _payload(extremes))


def test_fmt_height_string():
    # DISPLAY_TZ is America/Vancouver, so this is locale-independent.
    utc = datetime(2026, 5, 26, 16, 31, tzinfo=timezone.utc)
    assert _fmt_height(utc, "low", 1.24) == "Low 09:31 PDT — 1.2 m"


async def test_get_tide_heights_shape():
    result = await get_tide_heights(_tides(EXTREMES), lat=48.76, lon=-123.05,
                                    date="2026-05-26")
    assert result["station_name"] == "Montague Harbour BC"
    assert result["distance_km"] == 1
    # Five future events come back; the response caps at 4.
    assert [e["type"] for e in result["events"]] == ["high", "low", "high", "low"]
    assert result["events"][1]["display"] == "Low 09:31 PDT — 1.2 m"
    assert result["events"][1]["height_m"] == 1.2
    assert result["events"][1]["utc"] == "2026-05-26T16:31:00Z"
    # summary names the NEXT extreme (the 02:48 PDT high), not a later low
    assert "Next high" in result["summary_display"]
    assert "Montague Harbour BC" in result["summary_display"]


async def test_get_tide_heights_filters_past_events():
    # When `after` is mid-day, past events must not leak into the response
    # even if the server returns them.
    result = await get_tide_heights(_tides(EXTREMES), lat=48.76, lon=-123.05,
                                    date="2026-05-26T18:00:00Z")
    types = [e["type"] for e in result["events"]]
    assert types == ["high", "low", "high"]
    assert result["events"][0]["utc"] == "2026-05-26T23:05:00Z"
    # Summary must point at a future event, not the afternoon low we filtered out.
    assert "16:31" not in result["summary_display"]


async def test_get_tide_heights_requests_a_36h_window():
    seen = {}
    def fake_get(url, params):
        seen.update(params)
        return _payload(EXTREMES)
    tides = TidesClient("http://signalk:3000", getter=fake_get)
    await get_tide_heights(tides, lat=48.76, lon=-123.05, date="2026-05-26")
    # Local-midnight anchor (07:00Z in PDT) + 36 h, so a late-evening call
    # still covers that night's events landing in tomorrow UTC.
    assert seen["start"] == "2026-05-26T07:00:00Z"
    assert seen["end"] == "2026-05-27T19:00:00Z"


async def test_get_tide_heights_no_events_is_honest():
    result = await get_tide_heights(_tides([]), lat=48.76, lon=-123.05,
                                    date="2026-05-26")
    assert result["events"] == []
    assert "unavailable" in result["summary_display"].lower()
    assert "Montague Harbour BC" in result["summary_display"]


async def test_get_tide_heights_unreachable_server_says_so():
    # R1: the agent must be able to tell "no data" from "no service".
    async def boom(url, params):
        raise httpx.ConnectError("nope")
    tides = TidesClient("http://signalk:3000", getter=boom)
    result = await get_tide_heights(tides, lat=48.76, lon=-123.05)
    assert result["events"] == []
    assert "unreachable" in result["summary_display"].lower()
