"""Event dataclasses + CHS tide-height parsers.

Tidal-current predictions now come from the signalk-currents plugin (see
currents_source.CurrentsClient); CurrentEvent remains here as the shared shape.
CHS wlp-hilo high/low water is still fetched directly, pending Phase 2.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from currents_mcp.client import RateLimitedClient

CHS_BASE = "https://api-sine.dfo-mpo.gc.ca/api/v1"


@dataclass(frozen=True)
class CurrentEvent:
    utc: datetime          # tz-aware UTC
    kind: str              # "slack" | "flood" | "ebb"
    speed_knots: float     # magnitude, always positive
    flood_dir: int | None = None
    ebb_dir: int | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["utc"] = self.utc.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "CurrentEvent":
        return cls(
            utc=_parse_dt(d["utc"]),
            kind=d["kind"],
            speed_knots=d["speed_knots"],
            flood_dir=d.get("flood_dir"),
            ebb_dir=d.get("ebb_dir"),
        )


@dataclass(frozen=True)
class TideHeightEvent:
    utc: datetime          # tz-aware UTC
    kind: str              # "high" | "low"
    height_m: float        # metres above chart datum

    def to_dict(self) -> dict:
        d = asdict(self)
        d["utc"] = self.utc.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "TideHeightEvent":
        return cls(
            utc=_parse_dt(d["utc"]),
            kind=d["kind"],
            height_m=d["height_m"],
        )


def _parse_dt(s: str) -> datetime:
    """Parse an ISO8601 timestamp (with Z or offset) to a tz-aware UTC datetime."""
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso_z(dt: datetime) -> str:
    """Format a UTC datetime as the API's expected ...Z string."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _classify_height_kinds(values: list[float]) -> list[str]:
    """Label water-level values high/low by comparing each to its successor
    (the last to its predecessor; single value -> high).

    Real semidiurnal tides alternate, but a dropped CHS event at a day seam
    breaks alternation — pairwise comparison keeps any mislabel local to the
    seam instead of cascading down the rest of the sequence.
    """
    if not values:
        return []
    if len(values) == 1:
        return ["high"]
    kinds = ["high" if v > values[i + 1] else "low"
             for i, v in enumerate(values[:-1])]
    kinds.append("high" if values[-1] > values[-2] else "low")
    return kinds


async def fetch_chs_height_events(
    client: RateLimitedClient, station_id: str, start: datetime, end: datetime
) -> list[TideHeightEvent]:
    """Fetch CHS wlp-hilo (high/low water) for a station over [start, end), classified."""
    url = f"{CHS_BASE}/stations/{station_id}/data"
    params = {
        "time-series-code": "wlp-hilo",
        "from": _iso_z(start),
        "to": _iso_z(end),
    }
    resp = await client.get(url, params=params)
    resp.raise_for_status()
    rows = resp.json()
    kinds = _classify_height_kinds([float(r["value"]) for r in rows])
    return [
        TideHeightEvent(
            utc=_parse_dt(rows[i]["eventDate"]),
            kind=kinds[i],
            height_m=float(rows[i]["value"]),
        )
        for i in range(len(rows))
    ]


async def fetch_chs_stations(client: RateLimitedClient) -> list[dict]:
    """Fetch the full CHS station list (id, name, coords, operating, timeSeries)."""
    resp = await client.get(f"{CHS_BASE}/stations")
    resp.raise_for_status()
    return resp.json()
