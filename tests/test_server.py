import pytest

from currents_mcp.currents_source import CurrentsClient
from currents_mcp.server import DEFAULT_SIGNALK_URL, TOOL_NAMES, build_server, dispatch
from currents_mcp.tides_source import TidesClient

# Dodd Narrows station_id; slack at 09:14Z.
CURRENTS_PAYLOAD = {"stations": [
    {"stationId": "63aef1866a2b9417c035030f", "label": "Dodd Narrows",
     "lat": 49.1344, "lon": -123.8171, "events": [
         {"utc": "2026-05-24T09:14:00Z", "kind": "slack", "speedKn": 0.0},
         {"utc": "2026-05-24T12:14:00Z", "kind": "flood", "speedKn": 6.0},
     ]},
]}

# Neaps-shaped /tides/extremes payload (see tides_source).
TIDES_PAYLOAD = {
    "datum": "LAT", "units": "meters",
    "station": {"name": "Montague Harbour BC"}, "distance": 1.42,
    "extremes": [
        {"time": "2026-05-26T09:48:00Z", "level": 3.0, "high": True, "low": False},
        {"time": "2026-05-26T16:31:00Z", "level": 1.2, "high": False, "low": True},
        {"time": "2026-05-26T23:05:00Z", "level": 3.1, "high": True, "low": False},
        {"time": "2026-05-27T05:30:00Z", "level": 0.9, "high": False, "low": True},
    ],
}


def _currents(payload):
    return CurrentsClient("http://signalk:3000", getter=lambda url: payload)


def _tides(payload):
    return TidesClient("http://signalk:3000", getter=lambda url, params: payload)


def test_tool_names():
    assert TOOL_NAMES == ["get_passage_gates", "get_tidal_gate", "list_gates", "get_tide_heights"]


def test_default_signalk_url_targets_the_boat():
    """The mac-dev rig is retired — nothing answers on localhost:3000, and the
    fetch degrades silently to empty windows, so a wrong default looks like
    'no slack windows' rather than an error."""
    assert DEFAULT_SIGNALK_URL == "http://naturalaspi.local:3000"


async def test_build_server_names_it():
    server = build_server(_currents({"stations": []}), _tides(TIDES_PAYLOAD))
    assert server.name == "currents-mcp"


async def test_dispatch_get_tidal_gate():
    result = await dispatch(_currents(CURRENTS_PAYLOAD), _tides(TIDES_PAYLOAD),
                            "get_tidal_gate", {"name": "Dodd Narrows", "date": "2026-05-24"})
    assert result["name"] == "Dodd Narrows"
    assert result["slack_windows"][0]["utc"] == "2026-05-24T09:14:00Z"


async def test_dispatch_get_passage_gates():
    # Open-water destination routes through dispatch with no gates (empty gate list).
    result = await dispatch(_currents({"stations": []}), _tides(TIDES_PAYLOAD),
                            "get_passage_gates", {"destination": "Desolation Sound"})
    assert result["destination"] == "Desolation Sound"
    assert result["gates"] == []


async def test_dispatch_list_gates():
    # Guards against an accidental `await` being added to the sync list_gates branch.
    result = await dispatch(_currents({"stations": []}), _tides(TIDES_PAYLOAD),
                            "list_gates", {})
    assert "coverage" in result and "display" in result


async def test_dispatch_unknown_tool():
    with pytest.raises(ValueError):
        await dispatch(_currents({"stations": []}), _tides(TIDES_PAYLOAD), "nope", {})


async def test_dispatch_get_tide_heights():
    result = await dispatch(
        _currents({"stations": []}), _tides(TIDES_PAYLOAD),
        "get_tide_heights", {"lat": 48.76, "lon": -123.05, "date": "2026-05-26"},
    )
    assert result["station_name"] == "Montague Harbour BC"
    assert [e["type"] for e in result["events"]] == ["high", "low", "high", "low"]
