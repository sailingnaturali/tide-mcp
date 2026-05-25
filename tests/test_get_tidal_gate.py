import httpx
import respx

from tide_mcp.cache import EventCache
from tide_mcp.client import RateLimitedClient
from tide_mcp.tools import get_tidal_gate

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


@respx.mock
async def test_get_tidal_gate_noaa_unavailable_in_v1(tmp_path):
    cache = EventCache(str(tmp_path / "c.sqlite")); cache.init_schema()
    client = RateLimitedClient()
    result = await get_tidal_gate(client, cache, "Boundary Pass", date="2026-05-24")
    await client.aclose(); cache.close()
    assert result["slack_windows"] == []
    assert "not yet available" in result["note_display"]
