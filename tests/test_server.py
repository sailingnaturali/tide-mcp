import httpx
import pytest
import respx

from tide_mcp.cache import EventCache
from tide_mcp.client import RateLimitedClient
from tide_mcp.server import TOOL_NAMES, build_server, dispatch

DAY = [
    {"eventDate": "2026-05-24T09:14:00Z", "qualifier": "SLACK", "value": 0.0},
    {"eventDate": "2026-05-24T12:14:00Z", "qualifier": "EXTREMA_FLOOD", "value": 6.0},
]


def test_tool_names():
    assert TOOL_NAMES == ["get_passage_gates", "get_tidal_gate", "list_gates"]


async def test_build_server_names_it():
    cache = EventCache(":memory:"); cache.init_schema()
    client = RateLimitedClient()
    server = build_server(client, cache)
    assert server.name == "tide-mcp"
    await client.aclose(); cache.close()


@respx.mock
async def test_dispatch_get_tidal_gate(tmp_path):
    respx.get(url__regex=r".*/stations/.*/data").mock(return_value=httpx.Response(200, json=DAY))
    cache = EventCache(str(tmp_path / "c.sqlite")); cache.init_schema()
    client = RateLimitedClient()
    result = await dispatch(client, cache, "get_tidal_gate", {"name": "Dodd Narrows", "date": "2026-05-24"})
    await client.aclose(); cache.close()
    assert result["name"] == "Dodd Narrows"
    assert result["slack_windows"][0]["utc"] == "2026-05-24T09:14:00Z"


async def test_dispatch_get_passage_gates():
    # Open-water destination routes through dispatch with no HTTP (empty gate list).
    cache = EventCache(":memory:"); cache.init_schema()
    client = RateLimitedClient()
    result = await dispatch(client, cache, "get_passage_gates", {"destination": "Desolation Sound"})
    await client.aclose(); cache.close()
    assert result["destination"] == "Desolation Sound"
    assert result["gates"] == []


async def test_dispatch_list_gates():
    # Guards against an accidental `await` being added to the sync list_gates branch.
    cache = EventCache(":memory:"); cache.init_schema()
    client = RateLimitedClient()
    result = await dispatch(client, cache, "list_gates", {})
    await client.aclose(); cache.close()
    assert "coverage" in result and "display" in result


async def test_dispatch_unknown_tool():
    cache = EventCache(":memory:"); cache.init_schema()
    client = RateLimitedClient()
    try:
        with pytest.raises(ValueError):
            await dispatch(client, cache, "nope", {})
    finally:
        await client.aclose(); cache.close()
