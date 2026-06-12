"""Event dataclasses + shared time parsing.

Tidal-current predictions come from the signalk-currents plugin (see
currents_source.CurrentsClient); tide-height extremes come from the
signalk-tides plugin's Neaps engine (see tides_source.TidesClient).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone


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
    height_m: float        # metres above datum (LAT, from Neaps)


def _parse_dt(s: str) -> datetime:
    """Parse an ISO8601 timestamp (with Z or offset) to a tz-aware UTC datetime."""
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso_z(dt: datetime) -> str:
    """Format a UTC datetime as the API's expected ...Z string."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
