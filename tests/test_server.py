import httpx
import pytest
import respx

from currents_mcp.cache import EventCache
from currents_mcp.client import RateLimitedClient
from currents_mcp.currents_source import CurrentsClient
from currents_mcp.server import DEFAULT_SIGNALK_URL, TOOL_NAMES, build_server, dispatch

# Dodd Narrows station_id; slack at 09:14Z.
CURRENTS_PAYLOAD = {"stations": [
    {"stationId": "63aef1866a2b9417c035030f", "label": "Dodd Narrows",
     "lat": 49.1344, "lon": -123.8171, "events": [
         {"utc": "2026-05-24T09:14:00Z", "kind": "slack", "speedKn": 0.0},
         {"utc": "2026-05-24T12:14:00Z", "kind": "flood", "speedKn": 6.0},
     ]},
]}


def _currents(payload):
    return CurrentsClient("http://signalk:3000", getter=lambda url: payload)


def test_tool_names():
    assert TOOL_NAMES == ["get_passage_gates", "get_tidal_gate", "list_gates", "get_tide_heights"]


def test_default_signalk_url_targets_the_boat():
    """The mac-dev rig is retired — nothing answers on localhost:3000, and the
    fetch degrades silently to empty windows, so a wrong default looks like
    'no slack windows' rather than an error."""
    assert DEFAULT_SIGNALK_URL == "http://naturalaspi.local:3000"


async def test_build_server_names_it():
    cache = EventCache(":memory:"); cache.init_schema()
    client = RateLimitedClient()
    server = build_server(client, cache, _currents({"stations": []}))
    assert server.name == "currents-mcp"
    await client.aclose(); cache.close()


async def test_dispatch_get_tidal_gate():
    cache = EventCache(":memory:"); cache.init_schema()
    client = RateLimitedClient()
    currents = _currents(CURRENTS_PAYLOAD)
    result = await dispatch(client, cache, currents, "get_tidal_gate",
                            {"name": "Dodd Narrows", "date": "2026-05-24"})
    await client.aclose(); cache.close()
    assert result["name"] == "Dodd Narrows"
    assert result["slack_windows"][0]["utc"] == "2026-05-24T09:14:00Z"


async def test_dispatch_get_passage_gates():
    # Open-water destination routes through dispatch with no gates (empty gate list).
    cache = EventCache(":memory:"); cache.init_schema()
    client = RateLimitedClient()
    currents = _currents({"stations": []})
    result = await dispatch(client, cache, currents, "get_passage_gates",
                            {"destination": "Desolation Sound"})
    await client.aclose(); cache.close()
    assert result["destination"] == "Desolation Sound"
    assert result["gates"] == []


async def test_dispatch_list_gates():
    # Guards against an accidental `await` being added to the sync list_gates branch.
    cache = EventCache(":memory:"); cache.init_schema()
    client = RateLimitedClient()
    currents = _currents({"stations": []})
    result = await dispatch(client, cache, currents, "list_gates", {})
    await client.aclose(); cache.close()
    assert "coverage" in result and "display" in result


async def test_dispatch_unknown_tool():
    cache = EventCache(":memory:"); cache.init_schema()
    client = RateLimitedClient()
    currents = _currents({"stations": []})
    try:
        with pytest.raises(ValueError):
            await dispatch(client, cache, currents, "nope", {})
    finally:
        await client.aclose(); cache.close()


HILO_MAY26 = [
    {"eventDate": "2026-05-26T09:48:00Z", "value": 3.0},
    {"eventDate": "2026-05-26T16:31:00Z", "value": 1.2},
]
HILO_MAY27 = [
    {"eventDate": "2026-05-26T23:05:00Z", "value": 3.1},
    {"eventDate": "2026-05-27T05:30:00Z", "value": 0.9},
]
STATIONS = [
    {"id": "AAA", "officialName": "Montague Harbour", "latitude": 48.76, "longitude": -123.05,
     "operating": True, "timeSeries": [{"code": "wlp-hilo"}]},
]


def _hilo_by_day(request):
    from_str = request.url.params.get("from", "")
    if from_str.startswith("2026-05-26"):
        return httpx.Response(200, json=HILO_MAY26)
    if from_str.startswith("2026-05-27"):
        return httpx.Response(200, json=HILO_MAY27)
    return httpx.Response(200, json=[])


@respx.mock
async def test_dispatch_get_tide_heights(tmp_path):
    respx.get("https://api-sine.dfo-mpo.gc.ca/api/v1/stations").mock(
        return_value=httpx.Response(200, json=STATIONS)
    )
    respx.get("https://api-sine.dfo-mpo.gc.ca/api/v1/stations/AAA/data").mock(
        side_effect=_hilo_by_day
    )
    cache = EventCache(str(tmp_path / "c.sqlite")); cache.init_schema()
    client = RateLimitedClient()
    currents = _currents({"stations": []})
    result = await dispatch(
        client, cache, currents, "get_tide_heights",
        {"lat": 48.76, "lon": -123.05, "date": "2026-05-26"},
    )
    await client.aclose(); cache.close()
    assert result["station_name"] == "Montague Harbour"
    assert [e["type"] for e in result["events"]] == ["high", "low", "high", "low"]
