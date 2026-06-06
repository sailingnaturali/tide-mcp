"""Orchestration for CHS tide-height predictions, with per-UTC-day caching.

(Tidal-current events now come from the signalk-currents plugin via
CurrentsClient; only the height path remains here, pending Phase 2.)
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

from currents_mcp.cache import EventCache
from currents_mcp.client import RateLimitedClient
from currents_mcp.providers import (
    TideHeightEvent,
    _classify_height_kinds,
    fetch_chs_height_events,
    fetch_chs_stations,
)


def _query_days(start: datetime, n: int) -> list[date]:
    base = start.astimezone(timezone.utc).date()
    return [base + timedelta(days=i) for i in range(n)]


STATIONS_TTL_SECONDS = 86_400  # 24h
STATIONS_CACHE_KEY = "chs:stations:wlp-hilo"


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    r_km = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return r_km * 2 * math.asin(math.sqrt(a))


async def get_cached_stations(client: RateLimitedClient, cache: EventCache) -> list[dict]:
    """Return CHS height stations (operating, wlp-hilo), cached 24h."""
    cached = cache.get_with_ttl(STATIONS_CACHE_KEY, STATIONS_TTL_SECONDS)
    if cached is not None:
        return cached
    raw = await fetch_chs_stations(client)
    height = [
        {"id": s["id"], "officialName": s["officialName"],
         "latitude": s["latitude"], "longitude": s["longitude"]}
        for s in raw
        if s.get("operating")
        and any(ts.get("code") == "wlp-hilo" for ts in s.get("timeSeries", []))
    ]
    cache.put_with_ttl(STATIONS_CACHE_KEY, height)
    return height


def _nearest_height_station(lat: float, lon: float, stations: list[dict]) -> dict:
    """Closest station by great-circle distance. Stations are pre-filtered."""
    return min(stations, key=lambda s: _haversine_km(lat, lon, s["latitude"], s["longitude"]))


async def tide_height_events(
    client: RateLimitedClient,
    cache: EventCache,
    lat: float,
    lon: float,
    start: datetime,
    n_days: int = 1,
) -> tuple[dict, list[TideHeightEvent]]:
    """Nearest height station + classified high/low events over n_days, cached per day."""
    stations = await get_cached_stations(client, cache)
    station = _nearest_height_station(lat, lon, stations)
    out: list[TideHeightEvent] = []
    for day in _query_days(start, n_days):
        key = f"chs-height:{station['id']}:{day.isoformat()}"
        cached = cache.get(key)
        if cached is None:
            day_start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
            day_end = day_start + timedelta(days=1)
            events = await fetch_chs_height_events(client, station["id"], day_start, day_end)
            cache.put(key, [e.to_dict() for e in events])
        else:
            events = [TideHeightEvent.from_dict(x) for x in cached]
        out.extend(events)
    out.sort(key=lambda e: e.utc)
    # Each day is classified independently in cache; re-classify across the
    # joined sequence so a one-event day can't break alternation at the seam.
    if len(out) > 1:
        kinds = _classify_height_kinds([e.height_m for e in out])
        out = [TideHeightEvent(utc=e.utc, kind=k, height_m=e.height_m)
               for e, k in zip(out, kinds)]
    info = {
        "station_name": station["officialName"],
        "distance_km": round(_haversine_km(lat, lon, station["latitude"], station["longitude"])),
    }
    return info, out
