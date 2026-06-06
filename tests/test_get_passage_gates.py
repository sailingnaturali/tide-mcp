from currents_mcp.currents_source import CurrentsClient
from currents_mcp.tools import get_passage_gates

# Gillard Passage is ~137 nm from Victoria -> ~23h at 6 kn. Departing 2026-05-24T00:00Z,
# the earliest reachable slack must be ~23h out, so the slack lands on 2026-05-25.
# /currents is keyed by station_id: Gillard 5dd3064fe0fdc4b9b4be6978, Dent 63af06d56a2b9417c0353451.
_DAY = [
    {"utc": "2026-05-25T00:00:00Z", "kind": "ebb", "speedKn": 5.0},
    {"utc": "2026-05-25T02:00:00Z", "kind": "slack", "speedKn": 0.0},
    {"utc": "2026-05-25T05:00:00Z", "kind": "flood", "speedKn": 6.0},
]
PAYLOAD = {"stations": [
    {"stationId": "5dd3064fe0fdc4b9b4be6978", "label": "Gillard Passage",
     "lat": 50.3933, "lon": -125.1567, "events": _DAY},
    {"stationId": "63af06d56a2b9417c0353451", "label": "Dent Rapids",
     "lat": 50.4100, "lon": -125.2117, "events": _DAY},
]}


def _client(payload):
    return CurrentsClient("http://signalk:3000", getter=lambda url: payload)


async def test_passage_multi_gate_first_gets_departure():
    currents = _client(PAYLOAD)
    result = await get_passage_gates(currents, "Cordero Channel",
                                     depart_time="2026-05-24T00:00:00Z")

    assert result["destination"] == "Cordero Channel"
    assert [g["name"] for g in result["gates"]] == ["Gillard Passage", "Dent Rapids"]
    assert result["gates"][0]["recommended_depart_display"] is not None
    assert result["gates"][1]["recommended_depart_display"] is None
    assert "note_display" in result["gates"][1]


async def test_passage_open_water_returns_empty_gates():
    currents = _client({"stations": []})
    result = await get_passage_gates(currents, "Desolation Sound")
    assert result["gates"] == []
    assert "open-water" in result["summary_display"].lower()


async def test_passage_unknown_destination():
    currents = _client({"stations": []})
    result = await get_passage_gates(currents, "Atlantis")
    assert result.get("unmatched") is True
    assert "suggestions_display" in result


# Boundary Pass (Friday Harbor) now sourced from /currents like every other gate.
FRIDAY_PAYLOAD = {"stations": [
    {"stationId": "PUG1717", "label": "Boundary Pass",
     "lat": 48.6912, "lon": -123.2450, "events": [
         {"utc": "2026-05-24T06:00:00Z", "kind": "ebb", "speedKn": 2.0},
         {"utc": "2026-05-24T09:00:00Z", "kind": "slack", "speedKn": 0.0},
         {"utc": "2026-05-24T12:00:00Z", "kind": "flood", "speedKn": 2.0},
     ]},
]}


async def test_passage_friday_harbor():
    currents = _client(FRIDAY_PAYLOAD)
    result = await get_passage_gates(currents, "Friday Harbor",
                                     depart_time="2026-05-24T00:00:00Z")
    assert result["gates"][0]["name"] == "Boundary Pass"
    assert len(result["gates"][0]["slack_windows"]) >= 1
    assert "not yet available" not in result["summary_display"]
