"""Reads tidal-current predictions from the signalk-currents plugin's /currents
resource, replacing the MCP's old direct CHS/NOAA fetching."""
from __future__ import annotations

import inspect
import os
from typing import Awaitable, Callable

import httpx

from currents_mcp.providers import CurrentEvent, _parse_dt

CURRENTS_PATH = "/plugins/signalk-currents/currents"


def _event_from_plugin(d: dict) -> CurrentEvent:
    return CurrentEvent(utc=_parse_dt(d["utc"]), kind=d["kind"], speed_knots=float(d["speedKn"]))


class CurrentsClient:
    """Fetches /currents once per process lifetime cheaply (in-memory), maps
    stationId -> events. `getter` is injectable for tests."""

    def __init__(
        self, signalk_url: str,
        getter: Callable[[str], Awaitable[dict] | dict] | None = None,
    ) -> None:
        self._url = signalk_url.rstrip("/") + CURRENTS_PATH
        self._getter = getter or self._http_get
        self._cache: dict[str, list[CurrentEvent]] | None = None

    async def _http_get(self, url: str) -> dict:
        # SignalK requires auth for plugin routes (even with allow_readonly), so
        # /currents needs a token. A read-only SignalK token in SIGNALK_TOKEN is
        # enough.
        headers = {}
        token = os.environ.get("SIGNALK_TOKEN", "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def _load(self) -> dict[str, list[CurrentEvent]]:
        if self._cache is None:
            result = self._getter(self._url)
            payload = await result if inspect.isawaitable(result) else result
            self._cache = {
                s["stationId"]: sorted((_event_from_plugin(e) for e in s.get("events", [])),
                                       key=lambda e: e.utc)
                for s in payload.get("stations", [])
            }
        return self._cache

    async def events_for_station(self, station_id: str) -> list[CurrentEvent]:
        return (await self._load()).get(station_id, [])
