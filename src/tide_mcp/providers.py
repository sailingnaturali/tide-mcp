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


NOAA_BASE = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"


def _parse_noaa_time(s: str) -> datetime:
    """NOAA 'YYYY-MM-DD HH:MM' is UTC when requested with time_zone=gmt."""
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)


async def fetch_noaa_events(
    client: RateLimitedClient, station_id: str, bin_n: int, start: datetime, end: datetime
) -> list[CurrentEvent]:
    """Fetch NOAA CO-OPS current predictions (slack/flood/ebb) for a station+bin."""
    params = {
        "product": "currents_predictions",
        "interval": "MAX_SLACK",
        "time_zone": "gmt",
        "units": "english",
        "format": "json",
        "application": "tide-mcp",
        "station": station_id,
        "bin": str(bin_n),
        "begin_date": start.astimezone(timezone.utc).strftime("%Y%m%d"),
        "end_date": end.astimezone(timezone.utc).strftime("%Y%m%d"),
    }
    resp = await client.get(NOAA_BASE, params=params)
    resp.raise_for_status()
    cp = resp.json().get("current_predictions", {}).get("cp", [])
    events: list[CurrentEvent] = []
    for row in cp:
        kind = str(row.get("Type", "")).lower()
        if kind not in ("slack", "flood", "ebb"):
            continue
        events.append(
            CurrentEvent(
                utc=_parse_noaa_time(row["Time"]),
                kind=kind,
                speed_knots=abs(float(row["Velocity_Major"])),
                flood_dir=row.get("meanFloodDir"),
                ebb_dir=row.get("meanEbbDir"),
            )
        )
    return events


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
