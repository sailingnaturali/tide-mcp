import httpx
import respx

from currents_mcp.cache import EventCache
from currents_mcp.client import RateLimitedClient
from currents_mcp.tools import get_tidal_gate

DAY = [
    {"eventDate": "2026-05-24T06:14:00Z", "qualifier": "EXTREMA_EBB", "value": 5.0},
    {"eventDate": "2026-05-24T09:14:00Z", "qualifier": "SLACK", "value": 0.0},
    {"eventDate": "2026-05-24T12:14:00Z", "qualifier": "EXTREMA_FLOOD", "value": 6.0},
]


@respx.mock
async def test_get_tidal_gate_returns_slack_windows(tmp_path):
    respx.get(url__regex=r".*/stations/.*/data").mock(return_value=httpx.Response(200, json=DAY))
    cache = EventCache(str(tmp_path / "c.sqlite")); cache.init_schema()
    client = RateLimitedClient()
    result = await get_tidal_gate(client, cache, "Dodd Narrows", date="2026-05-24")
    await client.aclose(); cache.close()

    assert result["name"] == "Dodd Narrows"
    assert result["transit_window_minutes"] == 30
    assert result["slack_windows"][0]["utc"] == "2026-05-24T09:14:00Z"
    assert "ebb→flood" in result["slack_windows"][0]["display"]


async def test_get_tidal_gate_unknown_name_suggests(tmp_path):
    cache = EventCache(str(tmp_path / "c.sqlite")); cache.init_schema()
    client = RateLimitedClient()
    result = await get_tidal_gate(client, cache, "Nowhere Narrows")
    await client.aclose(); cache.close()
    assert result.get("unmatched") is True
    assert "Dodd Narrows" in result["suggestions_display"]


NOAA_DAY = {"current_predictions": {"cp": [
    {"Type": "ebb", "Time": "2026-05-24 06:00", "Velocity_Major": -2.0, "meanFloodDir": 3, "meanEbbDir": 236},
    {"Type": "slack", "Time": "2026-05-24 09:00", "Velocity_Major": 0, "meanFloodDir": 3, "meanEbbDir": 236},
    {"Type": "flood", "Time": "2026-05-24 12:00", "Velocity_Major": 2.0, "meanFloodDir": 3, "meanEbbDir": 236},
]}}


@respx.mock
async def test_get_tidal_gate_boundary_pass_via_noaa(tmp_path):
    respx.get(url__regex=r".*api.tidesandcurrents.noaa.gov.*").mock(
        return_value=httpx.Response(200, json=NOAA_DAY)
    )
    cache = EventCache(str(tmp_path / "c.sqlite")); cache.init_schema()
    client = RateLimitedClient()
    result = await get_tidal_gate(client, cache, "Boundary Pass", date="2026-05-24")
    await client.aclose(); cache.close()
    assert result["name"] == "Boundary Pass"
    assert result["slack_windows"][0]["utc"] == "2026-05-24T09:00:00Z"
