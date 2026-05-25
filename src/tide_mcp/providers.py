"""Provider HTTP parsers. Each returns provider-agnostic CurrentEvent objects.

CHS IWLS current stations expose slack/flood/ebb as `wcp1-events`. Values are
current speed in knots (the API does not declare units; verified empirically).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from tide_mcp.client import RateLimitedClient

CHS_BASE = "https://api-sine.dfo-mpo.gc.ca/api/v1"

_CHS_KIND = {
    "SLACK": "slack",
    "EXTREMA_FLOOD": "flood",
    "EXTREMA_EBB": "ebb",
}


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


def _parse_dt(s: str) -> datetime:
    """Parse an ISO8601 timestamp (with Z or offset) to a tz-aware UTC datetime."""
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso_z(dt: datetime) -> str:
    """Format a UTC datetime as the API's expected ...Z string."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def fetch_chs_events(
    client: RateLimitedClient, station_id: str, start: datetime, end: datetime
) -> list[CurrentEvent]:
    """Fetch CHS wcp1-events (slack/flood/ebb) for a station over [start, end)."""
    url = f"{CHS_BASE}/stations/{station_id}/data"
    params = {
        "time-series-code": "wcp1-events",
        "from": _iso_z(start),
        "to": _iso_z(end),
    }
    resp = await client.get(url, params=params)
    resp.raise_for_status()
    events: list[CurrentEvent] = []
    for row in resp.json():
        kind = _CHS_KIND.get(row.get("qualifier"))
        if kind is None:
            continue
        events.append(
            CurrentEvent(
                utc=_parse_dt(row["eventDate"]),
                kind=kind,
                speed_knots=abs(float(row["value"])),
            )
        )
    return events
