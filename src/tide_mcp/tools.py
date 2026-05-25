"""MCP tool implementations + formatting/math helpers.

Display fields are pre-formatted and TTS-safe per docs/agent-lessons.md:
the model never sees raw UTC or SI values to reformat.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from tide_mcp.passages import Gate
from tide_mcp.providers import CurrentEvent, _iso_z

VICTORIA = (48.42, -123.37)
DEFAULT_SPEED_KNOTS = 6.0
DISPLAY_TZ = ZoneInfo("America/Vancouver")


def _haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in nautical miles."""
    r_nm = 3440.065
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r_nm * math.asin(math.sqrt(a))


_OPPOSITE = {"flood": "ebb", "ebb": "flood"}


def _direction_label(prev_kind: str | None, next_kind: str | None) -> str:
    """Turn the surrounding extrema into a 'ebb→flood' style slack label.

    If only one neighbor is known, infer the other as the opposite phase.
    """
    if prev_kind and next_kind:
        return f"{prev_kind}→{next_kind}"
    if prev_kind:
        return f"{prev_kind}→{_OPPOSITE[prev_kind]}"
    if next_kind:
        return f"{_OPPOSITE[next_kind]}→{next_kind}"
    return "slack"


def _fmt_slack(utc: datetime, direction: str) -> str:
    """e.g. 'Sun 21:14 PDT (slack, ebb→flood)'."""
    local = utc.astimezone(DISPLAY_TZ)
    return f"{local:%a %H:%M} {local:%Z} (slack, {direction})"


def _slack_windows(events: list[CurrentEvent], limit: int, after: datetime) -> list[dict]:
    """Assemble up to `limit` slack windows at/after `after`, labeling direction
    from the nearest flood/ebb extrema on either side."""
    windows: list[dict] = []
    for i, e in enumerate(events):
        if e.kind != "slack" or e.utc < after:
            continue
        prev_kind = next((events[j].kind for j in range(i - 1, -1, -1)
                          if events[j].kind in ("flood", "ebb")), None)
        next_kind = next((events[j].kind for j in range(i + 1, len(events))
                          if events[j].kind in ("flood", "ebb")), None)
        windows.append({
            "display": _fmt_slack(e.utc, _direction_label(prev_kind, next_kind)),
            "utc": _iso_z(e.utc),
        })
        if len(windows) >= limit:
            break
    return windows


def _recommended_depart(
    gate: Gate, events: list[CurrentEvent], depart_time: datetime, origin: tuple[float, float]
) -> str | None:
    """Recommend a departure time to hit the FIRST gate at its next reachable slack.

    v1 estimate: great-circle distance from origin at a fixed 6 knots.
    """
    dist_nm = _haversine_nm(origin[0], origin[1], gate.latitude, gate.longitude)
    travel = timedelta(hours=dist_nm / DEFAULT_SPEED_KNOTS)
    earliest_arrival = depart_time + travel
    slack = next((e for e in events if e.kind == "slack" and e.utc >= earliest_arrival), None)
    if slack is None:
        return None
    depart_by = (slack.utc - travel).astimezone(DISPLAY_TZ)
    return f"Depart by {depart_by:%H:%M} {depart_by:%Z} to hit {gate.name} at slack."
