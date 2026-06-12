"""Reads tide-height extremes from the signalk-tides plugin's offline Neaps
API, replacing the MCP's old direct CHS height fetching."""
from __future__ import annotations

import inspect
import sys
from datetime import datetime
from typing import Awaitable, Callable

import httpx

from currents_mcp.providers import TideHeightEvent, _iso_z, _parse_dt

EXTREMES_PATH = "/signalk/v2/api/tides/extremes"


class TidesClient:
    """Fetches hi/lo extremes for any position from the boat server's Neaps
    engine (signalk-tides >= 2.0.0-beta.1). One LAN GET per call — the engine
    is a local computation, so no cache. `getter` is injectable for tests."""

    def __init__(
        self, signalk_url: str,
        getter: Callable[[str, dict], Awaitable[dict] | dict] | None = None,
    ) -> None:
        self._url = signalk_url.rstrip("/") + EXTREMES_PATH
        self._getter = getter or self._http_get
        # Distinguishes "service unreachable" from "no data for this position"
        # so the agent can say which one happened (R1).
        self.unreachable = False

    async def _http_get(self, url: str, params: dict) -> dict:
        # Served by the tides plugin, anonymously readable under
        # allow_readonly. httpx URL-encodes params — the Neaps API rejects
        # raw ':' in start/end, so never hand-build this query string.
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()

    async def extremes(
        self, lat: float, lon: float, start: datetime, end: datetime
    ) -> tuple[dict | None, list[TideHeightEvent]]:
        """(station info, time-sorted events) — (None, []) when unreachable."""
        params = {
            "latitude": lat, "longitude": lon,
            "start": _iso_z(start), "end": _iso_z(end),
        }
        try:
            result = self._getter(self._url, params)
            payload = await result if inspect.isawaitable(result) else result
        except Exception as e:
            # signalk-tides down/unreachable: degrade rather than crash the
            # tool; the caller words the failure. Logged to stderr (stdio MCP).
            print(f"currents-mcp: tides fetch failed: {e}", file=sys.stderr)
            self.unreachable = True
            return None, []
        self.unreachable = False
        # Per-record degradation (R3): one malformed extreme must not blank
        # the dataset — skip it, warn, keep serving the rest.
        events: list[TideHeightEvent] = []
        for x in payload.get("extremes", []):
            try:
                events.append(TideHeightEvent(
                    utc=_parse_dt(x["time"]),
                    kind="high" if x["high"] else "low",
                    height_m=float(x["level"]),
                ))
            except (KeyError, TypeError, ValueError) as exc:
                print(f"currents-mcp: skipping malformed extreme: {exc!r}",
                      file=sys.stderr)
        events.sort(key=lambda e: e.utc)
        station = payload.get("station") or {}
        info = {
            "station_name": station.get("name", "unknown"),
            # Neaps reports distance in km (e.g. 0.4 for a ~400 m offset).
            "distance_km": round(payload.get("distance") or 0),
        }
        return info, events
