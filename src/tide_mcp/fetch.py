"""Orchestration: fetch current events for a gate, with per-UTC-day caching
and provider dispatch.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from tide_mcp.cache import EventCache
from tide_mcp.client import RateLimitedClient
from tide_mcp.passages import Gate
from tide_mcp.providers import CurrentEvent, fetch_chs_events


class ProviderNotImplemented(Exception):
    """Raised when a gate's provider has no fetcher wired up yet (e.g. NOAA in v1)."""


def _query_days(start: datetime, n: int) -> list[date]:
    base = start.astimezone(timezone.utc).date()
    return [base + timedelta(days=i) for i in range(n)]


async def gate_events(
    client: RateLimitedClient,
    cache: EventCache,
    gate: Gate,
    start: datetime,
    n_days: int = 3,
) -> list[CurrentEvent]:
    """Return CurrentEvents for `gate` across `n_days` UTC days from `start`, cached per day."""
    out: list[CurrentEvent] = []
    for day in _query_days(start, n_days):
        key = f"{gate.provider}:{gate.station_id}:{day.isoformat()}"
        cached = cache.get(key)
        if cached is None:
            if gate.provider != "chs":
                raise ProviderNotImplemented(gate.provider)
            day_start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
            events = await fetch_chs_events(client, gate.station_id, day_start, day_start + timedelta(days=1))
            cache.put(key, [e.to_dict() for e in events])
        else:
            events = [CurrentEvent.from_dict(x) for x in cached]
        out.extend(events)
    out.sort(key=lambda e: e.utc)
    return out
