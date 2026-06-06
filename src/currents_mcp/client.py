"""Async HTTP client with a single sliding-window request limiter.

Defaults to 30 requests per 60s to stay under the CHS cap. currents-mcp makes only
1-3 serialized calls per request, so a separate per-second limiter is unneeded.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Awaitable, Callable

import httpx


class RateLimitedClient:
    """Wraps httpx.AsyncClient with a sliding-window request limiter.

    ``now`` and ``sleep`` are injectable for deterministic tests.
    """

    def __init__(
        self,
        http: httpx.AsyncClient | None = None,
        max_calls: int = 30,
        period: float = 60.0,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._http = http or httpx.AsyncClient(timeout=10.0)
        self._max_calls = max_calls
        self._period = period
        self._now = now
        self._sleep = sleep
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def _acquire(self) -> None:
        async with self._lock:
            while True:
                now = self._now()
                while self._calls and now - self._calls[0] >= self._period:
                    self._calls.popleft()
                if len(self._calls) < self._max_calls:
                    self._calls.append(now)
                    return
                await self._sleep(self._period - (now - self._calls[0]))

    async def get(self, url: str, params: dict | None = None) -> httpx.Response:
        await self._acquire()
        return await self._http.get(url, params=params)

    async def aclose(self) -> None:
        await self._http.aclose()
