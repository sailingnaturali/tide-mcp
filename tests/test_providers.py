from datetime import datetime, timezone

from currents_mcp.providers import CurrentEvent


def test_current_event_roundtrips_via_dict():
    e = CurrentEvent(datetime(2026, 5, 24, 6, 14, tzinfo=timezone.utc), "slack", 0.0)
    assert CurrentEvent.from_dict(e.to_dict()) == e
