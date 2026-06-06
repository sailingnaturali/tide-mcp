import pytest
from currents_mcp.currents_source import CurrentsClient
from currents_mcp.providers import CurrentEvent

PAYLOAD = {"stations": [
    {"stationId": "g", "label": "Gillard", "lat": 50.39, "lon": -125.15, "events": [
        {"utc": "2026-06-06T04:14:00.000Z", "kind": "slack", "speedKn": 0},
        {"utc": "2026-06-06T05:40:00.000Z", "kind": "flood", "speedKn": 4.1},
    ]},
]}


@pytest.mark.asyncio
async def test_events_for_station_parses_payload():
    calls = {"n": 0}
    async def fake_get(url):  # injected fetcher
        calls["n"] += 1
        return PAYLOAD
    c = CurrentsClient("http://signalk:3000", getter=fake_get)
    ev = await c.events_for_station("g")
    assert [(e.kind, e.speed_knots) for e in ev] == [("slack", 0.0), ("flood", 4.1)]
    assert isinstance(ev[0], CurrentEvent)
    await c.events_for_station("g")            # cached
    assert calls["n"] == 1                      # fetched once


@pytest.mark.asyncio
async def test_unknown_station_returns_empty():
    c = CurrentsClient("http://signalk:3000", getter=lambda url: PAYLOAD)
    assert await c.events_for_station("missing") == []


@pytest.mark.asyncio
async def test_unreachable_degrades_to_empty():
    """A down/unreachable signalk-currents yields [] (no crash), not an exception."""
    def boom(url):
        raise RuntimeError("plugin down")
    c = CurrentsClient("http://signalk:3000", getter=boom)
    assert await c.events_for_station("g") == []
