"""MCP tool implementations + formatting/math helpers.

Display fields are pre-formatted and TTS-safe per docs/agent-lessons.md:
the model never sees raw UTC or SI values to reformat.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from tide_mcp.cache import EventCache
from tide_mcp.client import RateLimitedClient
from tide_mcp.fetch import gate_events, tide_height_events
from tide_mcp.passages import GATES, Gate, PASSAGES, coverage, find_gate, match_destination
from tide_mcp.providers import CurrentEvent, _iso_z, _parse_dt

VICTORIA = (48.42, -123.37)
DEFAULT_SPEED_KNOTS = 6.0
DISPLAY_TZ = ZoneInfo("America/Vancouver")
_OPEN_WATER_SUMMARY = (
    "No tidal gates on the direct route - open-water passage; "
    "wind and weather are the constraint."
)


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


def _fmt_height(utc: datetime, kind: str, height_m: float) -> str:
    """e.g. 'Low 09:31 PDT — 1.2 m'."""
    local = utc.astimezone(DISPLAY_TZ)
    return f"{kind.capitalize()} {local:%H:%M} {local:%Z} — {height_m:.1f} m"


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


def _parse_dt_arg(value: str | None) -> datetime:
    """Parse an optional ISO date/datetime arg; default now (UTC). Date-only -> 00:00Z."""
    if not value:
        return datetime.now(timezone.utc)
    v = value.strip()
    if "T" not in v and " " not in v:
        v = v + "T00:00:00+00:00"
    return _parse_dt(v)


def _gate_suggestions() -> str:
    return "Known gates: " + ", ".join(GATES.keys()) + "."


async def get_tidal_gate(
    client: RateLimitedClient, cache: EventCache, name: str, date: str | None = None
) -> dict:
    """Return the next 3 slack windows for a single named gate."""
    gate = find_gate(name)
    if gate is None:
        return {"unmatched": True, "suggestions_display": _gate_suggestions()}
    after = _parse_dt_arg(date)
    events = await gate_events(client, cache, gate, after)
    return {
        "name": gate.name,
        "slack_windows": _slack_windows(events, 3, after),
        "transit_window_minutes": gate.transit_window_minutes,
    }


def _destination_suggestions() -> str:
    return "Known destinations: " + ", ".join(p.destination for p in PASSAGES) + "."


async def get_passage_gates(
    client: RateLimitedClient,
    cache: EventCache,
    destination: str,
    depart_time: str | None = None,
    from_lat: float | None = None,
    from_lon: float | None = None,
) -> dict:
    """Map a destination to its ordered gates, fetch slack windows, recommend a
    departure for the first gate."""
    passage = match_destination(destination)
    if passage is None:
        return {"unmatched": True, "suggestions_display": _destination_suggestions()}

    depart = _parse_dt_arg(depart_time)
    origin = (from_lat, from_lon) if from_lat is not None and from_lon is not None else VICTORIA

    if not passage.gate_names:
        return {
            "destination": passage.destination,
            "gates": [],
            "summary_display": _OPEN_WATER_SUMMARY,
        }

    gates_out: list[dict] = []
    for idx, gname in enumerate(passage.gate_names):
        gate = GATES[gname]
        events = await gate_events(client, cache, gate, depart)
        entry = {
            "name": gate.name,
            "slack_windows": _slack_windows(events, 3, depart),
            "transit_window_minutes": gate.transit_window_minutes,
        }
        if idx == 0:
            entry["recommended_depart_display"] = _recommended_depart(gate, events, depart, origin)
        else:
            entry["recommended_depart_display"] = None
            entry["note_display"] = (
                "Slack windows shown for planning; the recommended departure covers the first gate only."
            )
        gates_out.append(entry)

    first = gates_out[0]
    lead = (
        first.get("recommended_depart_display")
        or first.get("note_display")
        or "Check the first gate's slack windows."
    )
    summary = f"{len(gates_out)} tidal gate(s). {lead}"
    return {"destination": passage.destination, "gates": gates_out, "summary_display": summary}


def list_gates() -> dict:
    """Return known destinations and the gates they cover."""
    cov = coverage()
    display = "Covered destinations: " + "; ".join(
        f"{c['destination']} ({', '.join(c['gates']) or 'no gates'})" for c in cov
    )
    return {"coverage": cov, "display": display}


async def get_tide_heights(
    client: RateLimitedClient,
    cache: EventCache,
    lat: float,
    lon: float,
    date: str | None = None,
) -> dict:
    """Return high/low tide heights for the nearest CHS water-level station,
    starting at `date` (or now) and covering ~one local-day tide cycle."""
    after = _parse_dt_arg(date)
    # n_days=2 so we don't drop the local-day tail when `after` is late in a
    # UTC day (e.g. evening PDT pushes that night's events into tomorrow UTC).
    info, events = await tide_height_events(client, cache, lat, lon, after, n_days=2)

    out_events = [
        {
            "display": _fmt_height(e.utc, e.kind, e.height_m),
            "type": e.kind,
            "height_m": round(e.height_m, 1),
            "utc": _iso_z(e.utc),
        }
        for e in events if e.utc >= after
    ][:4]

    if not out_events:
        summary = (
            f"Tide heights unavailable for this position "
            f"(nearest station: {info['station_name']})."
        )
        return {
            "station_name": info["station_name"],
            "distance_km": info["distance_km"],
            "events": [],
            "summary_display": summary,
        }

    next_low = next((e for e in out_events if e["type"] == "low"), None)
    next_high = next((e for e in out_events if e["type"] == "high"), None)
    nxt = next_low or next_high
    label = nxt["type"]
    when_height = nxt["display"].split(" ", 1)[1]  # drop the "Low "/"High " prefix
    summary = (
        f"Nearest tide station: {info['station_name']}, "
        f"{info['distance_km']} km from you. Next {label} is {when_height}."
    )
    return {
        "station_name": info["station_name"],
        "distance_km": info["distance_km"],
        "events": out_events,
        "summary_display": summary,
    }
