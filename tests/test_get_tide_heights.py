from datetime import datetime, timezone

import httpx
import respx

from tide_mcp.cache import EventCache
from tide_mcp.client import RateLimitedClient
from tide_mcp.tools import _fmt_height, get_tide_heights

HEIGHT_STATIONS = [
    {"id": "AAA", "officialName": "Montague Harbour", "latitude": 48.76, "longitude": -123.05,
     "operating": True, "timeSeries": [{"code": "wlp-hilo"}]},
]
HILO_DAY = [
    {"eventDate": "2026-05-26T09:48:00Z", "value": 3.05},
    {"eventDate": "2026-05-26T16:31:00Z", "value": 1.24},
]


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
        return_value=httpx.Response(200, json=HILO_DAY)
    )
    cache = EventCache(str(tmp_path / "c.sqlite")); cache.init_schema()
    client = RateLimitedClient()
    result = await get_tide_heights(client, cache, lat=48.76, lon=-123.05, date="2026-05-26")
    await client.aclose(); cache.close()

    assert result["station_name"] == "Montague Harbour"
    assert result["distance_km"] >= 0
    assert [e["type"] for e in result["events"]] == ["high", "low"]
    assert result["events"][1]["display"] == "Low 09:31 PDT — 1.2 m"
    assert result["events"][1]["height_m"] == 1.2
    assert result["events"][1]["utc"] == "2026-05-26T16:31:00Z"
    # summary names the next low relative to the start of the query day
    assert "low" in result["summary_display"].lower()
    assert "Montague Harbour" in result["summary_display"]


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
