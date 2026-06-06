from currents_mcp.currents_source import CurrentsClient
from currents_mcp.tools import get_tidal_gate

# /currents payload keyed by station_id (the plugin's contract). Dodd Narrows is
# 63aef1866a2b9417c035030f; the slack at 09:14Z is preceded by an ebb and followed
# by a flood, so its direction label is ebb->flood.
PAYLOAD = {"stations": [
    {"stationId": "63aef1866a2b9417c035030f", "label": "Dodd Narrows",
     "lat": 49.1344, "lon": -123.8171, "events": [
         {"utc": "2026-05-24T06:14:00Z", "kind": "ebb", "speedKn": 5.0},
         {"utc": "2026-05-24T09:14:00Z", "kind": "slack", "speedKn": 0.0},
         {"utc": "2026-05-24T12:14:00Z", "kind": "flood", "speedKn": 6.0},
     ]},
]}


def _client(payload):
    return CurrentsClient("http://signalk:3000", getter=lambda url: payload)


async def test_get_tidal_gate_returns_slack_windows():
    currents = _client(PAYLOAD)
    result = await get_tidal_gate(currents, "Dodd Narrows", date="2026-05-24")

    assert result["name"] == "Dodd Narrows"
    assert result["transit_window_minutes"] == 30
    assert result["slack_windows"][0]["utc"] == "2026-05-24T09:14:00Z"
    assert "ebb→flood" in result["slack_windows"][0]["display"]


async def test_get_tidal_gate_unknown_name_suggests():
    currents = _client(PAYLOAD)
    result = await get_tidal_gate(currents, "Nowhere Narrows")
    assert result.get("unmatched") is True
    assert "Dodd Narrows" in result["suggestions_display"]


# Boundary Pass (NOAA station PUG1717) now comes from the same /currents resource;
# the MCP no longer cares about the provider — it just looks up by station_id.
BOUNDARY_PAYLOAD = {"stations": [
    {"stationId": "PUG1717", "label": "Boundary Pass",
     "lat": 48.6912, "lon": -123.2450, "events": [
         {"utc": "2026-05-24T06:00:00Z", "kind": "ebb", "speedKn": 2.0},
         {"utc": "2026-05-24T09:00:00Z", "kind": "slack", "speedKn": 0.0},
         {"utc": "2026-05-24T12:00:00Z", "kind": "flood", "speedKn": 2.0},
     ]},
]}


async def test_get_tidal_gate_boundary_pass():
    currents = _client(BOUNDARY_PAYLOAD)
    result = await get_tidal_gate(currents, "Boundary Pass", date="2026-05-24")
    assert result["name"] == "Boundary Pass"
    assert result["slack_windows"][0]["utc"] == "2026-05-24T09:00:00Z"
