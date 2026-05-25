import httpx
import respx

from tide_mcp.cache import EventCache
from tide_mcp.client import RateLimitedClient
from tide_mcp.tools import get_passage_gates

# Gillard Passage is ~137 nm from Victoria -> ~23h at 6 kn. Departing 2026-05-24T00:00Z,
# the earliest reachable slack must be ~23h out, so the slack lands on 2026-05-25.
DAY = [
    {"eventDate": "2026-05-25T00:00:00Z", "qualifier": "EXTREMA_EBB", "value": 5.0},
    {"eventDate": "2026-05-25T02:00:00Z", "qualifier": "SLACK", "value": 0.0},
    {"eventDate": "2026-05-25T05:00:00Z", "qualifier": "EXTREMA_FLOOD", "value": 6.0},
]


@respx.mock
async def test_passage_multi_gate_first_gets_departure(tmp_path):
    respx.get(url__regex=r".*/stations/.*/data").mock(return_value=httpx.Response(200, json=DAY))
    cache = EventCache(str(tmp_path / "c.sqlite")); cache.init_schema()
    client = RateLimitedClient()
    result = await get_passage_gates(client, cache, "Cordero Channel",
                                     depart_time="2026-05-24T00:00:00Z")
    await client.aclose(); cache.close()

    assert result["destination"] == "Cordero Channel"
    assert [g["name"] for g in result["gates"]] == ["Gillard Passage", "Dent Rapids"]
    assert result["gates"][0]["recommended_depart_display"] is not None
    assert result["gates"][1]["recommended_depart_display"] is None
    assert "note_display" in result["gates"][1]


async def test_passage_open_water_returns_empty_gates(tmp_path):
    cache = EventCache(str(tmp_path / "c.sqlite")); cache.init_schema()
    client = RateLimitedClient()
    result = await get_passage_gates(client, cache, "Desolation Sound")
    await client.aclose(); cache.close()
    assert result["gates"] == []
    assert "open-water" in result["summary_display"].lower()


async def test_passage_unknown_destination(tmp_path):
    cache = EventCache(str(tmp_path / "c.sqlite")); cache.init_schema()
    client = RateLimitedClient()
    result = await get_passage_gates(client, cache, "Atlantis")
    await client.aclose(); cache.close()
    assert result.get("unmatched") is True
    assert "suggestions_display" in result


async def test_passage_noaa_gate_unavailable(tmp_path):
    cache = EventCache(str(tmp_path / "c.sqlite")); cache.init_schema()
    client = RateLimitedClient()
    result = await get_passage_gates(client, cache, "Friday Harbor")
    await client.aclose(); cache.close()
    assert result["gates"][0]["slack_windows"] == []
    assert "not yet available" in result["gates"][0]["note_display"]
