import re
from datetime import datetime, timezone

from tide_mcp.passages import GATES
from tide_mcp.providers import CurrentEvent
from tide_mcp.tools import (
    VICTORIA,
    _direction_label,
    _fmt_slack,
    _haversine_nm,
    _recommended_depart,
    _slack_windows,
)


def test_direction_label_no_neighbors():
    assert _direction_label(None, None) == "slack"


def test_fmt_slack_string():
    # DISPLAY_TZ is hardcoded to America/Vancouver, so this is locale-independent.
    utc = datetime(2026, 5, 24, 13, 14, tzinfo=timezone.utc)
    assert _fmt_slack(utc, "ebb→flood") == "Sun 06:14 PDT (slack, ebb→flood)"


def test_haversine_zero_distance():
    assert _haversine_nm(48.42, -123.37, 48.42, -123.37) == 0.0


def test_haversine_known_distance():
    # Victoria (48.42,-123.37) to Dodd Narrows (49.1344,-123.8171) ~ 47 nm great-circle
    nm = _haversine_nm(48.42, -123.37, 49.1344, -123.8171)
    assert 40 < nm < 55


def _ev(h, kind, spd=1.0):
    return CurrentEvent(datetime(2026, 5, 24, h, 0, tzinfo=timezone.utc), kind, spd)


def test_slack_windows_label_direction_from_neighbors():
    events = [_ev(2, "ebb", 5.0), _ev(6, "slack", 0.0), _ev(9, "flood", 6.0), _ev(13, "slack", 0.0)]
    after = datetime(2026, 5, 24, 0, 0, tzinfo=timezone.utc)
    windows = _slack_windows(events, 5, after)
    assert len(windows) == 2
    assert "ebb→flood" in windows[0]["display"]
    assert "flood→ebb" in windows[1]["display"]
    assert windows[0]["utc"] == "2026-05-24T06:00:00Z"


def test_slack_windows_respects_after_and_limit():
    events = [_ev(2, "slack"), _ev(8, "slack"), _ev(14, "slack")]
    after = datetime(2026, 5, 24, 6, 0, tzinfo=timezone.utc)
    windows = _slack_windows(events, 1, after)
    assert len(windows) == 1
    assert windows[0]["utc"] == "2026-05-24T08:00:00Z"


def test_recommended_depart_backs_off_travel_time():
    # Gate ~47 nm from Victoria at 6 kn -> ~7.8 h travel.
    # Slack at 20:00 UTC; leaving now (00:00) arrives ~07:48, before slack,
    # so recommended depart = slack - travel ~= 12:12 UTC.
    gate = GATES["Dodd Narrows"]
    slack = datetime(2026, 5, 24, 20, 0, tzinfo=timezone.utc)
    events = [CurrentEvent(slack, "slack", 0.0)]
    depart = datetime(2026, 5, 24, 0, 0, tzinfo=timezone.utc)
    text = _recommended_depart(gate, events, depart, VICTORIA)
    assert text is not None
    assert "Dodd Narrows" in text and "Depart by" in text
    # The slack is 20:00 UTC = 13:00 PDT; the back-off must put departure earlier.
    hhmm = re.search(r"Depart by (\d{2}:\d{2})", text).group(1)
    assert hhmm < "13:00"


def test_recommended_depart_none_when_no_reachable_slack():
    gate = GATES["Dodd Narrows"]
    # Only slack is in the past relative to arrival.
    events = [CurrentEvent(datetime(2026, 5, 24, 1, 0, tzinfo=timezone.utc), "slack", 0.0)]
    depart = datetime(2026, 5, 24, 0, 0, tzinfo=timezone.utc)
    assert _recommended_depart(gate, events, depart, VICTORIA) is None
