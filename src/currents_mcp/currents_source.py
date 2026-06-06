"""Reads tidal-current predictions from the signalk-currents plugin's /currents
resource, replacing the MCP's old direct CHS/NOAA fetching."""
from __future__ import annotations

import inspect
import sys
from typing import Awaitable, Callable

import httpx

from currents_mcp.providers import CurrentEvent, _parse_dt

CURRENTS_PATH = "/signalk/v2/api/resources/currents"


def _event_from_plugin(d: dict, flood_dir: int | None, ebb_dir: int | None) -> CurrentEvent:
    """Map a plugin event; flood/ebb set (°true) is station-level config carried
    onto every event (absent from plugin < 0.3.0 payloads -> None)."""
    return CurrentEvent(
        utc=_parse_dt(d["utc"]), kind=d["kind"], speed_knots=float(d["speedKn"]),
        flood_dir=flood_dir, ebb_dir=ebb_dir,
    )


def _dirs_from_station(s: dict) -> dict:
    """Station-level direction metadata for provenance-aware displays."""
    if s.get("floodDir") is None and s.get("ebbDir") is None:
        return {}
    return {
        "flood_dir": s.get("floodDir"),
        "ebb_dir": s.get("ebbDir"),
        "source": s.get("dirsSource"),
        "flood_dir_estimated": bool(s.get("floodDirEstimated")),
        "ebb_dir_estimated": bool(s.get("ebbDirEstimated")),
    }


class CurrentsClient:
    """Fetches /currents once per process lifetime cheaply (in-memory), maps
    stationId -> events (+ direction metadata). `getter` is injectable for tests."""

    def __init__(
        self, signalk_url: str,
        getter: Callable[[str], Awaitable[dict] | dict] | None = None,
    ) -> None:
        self._url = signalk_url.rstrip("/") + CURRENTS_PATH
        self._getter = getter or self._http_get
        self._cache: dict[str, list[CurrentEvent]] | None = None
        self._dirs: dict[str, dict] = {}

    async def _http_get(self, url: str) -> dict:
        # /currents is a SignalK resource (/signalk/v2/api/resources/currents),
        # anonymously readable under allow_readonly — no token needed.
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()

    async def _load(self) -> dict[str, list[CurrentEvent]]:
        if self._cache is not None:
            return self._cache
        try:
            result = self._getter(self._url)
            payload = await result if inspect.isawaitable(result) else result
        except Exception as e:
            # signalk-currents down/unreachable: degrade to no data (gate tools
            # show empty windows) rather than crashing the tool. Not cached, so
            # a later call retries. Logged to stderr (MCP runs over stdio).
            print(f"currents-mcp: /currents fetch failed: {e}", file=sys.stderr)
            return {}
        self._cache = {
            s["stationId"]: sorted(
                (_event_from_plugin(e, s.get("floodDir"), s.get("ebbDir"))
                 for e in s.get("events", [])),
                key=lambda e: e.utc)
            for s in payload.get("stations", [])
        }
        self._dirs = {
            s["stationId"]: _dirs_from_station(s) for s in payload.get("stations", [])
        }
        return self._cache

    async def events_for_station(self, station_id: str) -> list[CurrentEvent]:
        return (await self._load()).get(station_id, [])

    async def dirs_for_station(self, station_id: str) -> dict:
        await self._load()
        return self._dirs.get(station_id, {})
