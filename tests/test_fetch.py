from dataclasses import replace
from datetime import datetime, timezone

import httpx
import pytest
import respx

from tide_mcp.cache import EventCache
from tide_mcp.client import RateLimitedClient
from tide_mcp.fetch import ProviderNotImplemented, gate_events
from tide_mcp.passages import GATES

DAY = [
    {"eventDate": "2026-05-24T06:14:00Z", "qualifier": "SLACK", "value": 0.0},
    {"eventDate": "2026-05-24T09:44:00Z", "qualifier": "EXTREMA_EBB", "value": 5.8},
]


@respx.mock
async def test_gate_events_fetches_and_caches(tmp_path):
    route = respx.get("https://api-sine.dfo-mpo.gc.ca/api/v1/stations/63aef1866a2b9417c035030f/data").mock(
        return_value=httpx.Response(200, json=DAY)
    )
    cache = EventCache(str(tmp_path / "c.sqlite"))
    cache.init_schema()
    client = RateLimitedClient()
    start = datetime(2026, 5, 24, 12, 0, tzinfo=timezone.utc)

    first = await gate_events(client, cache, GATES["Dodd Narrows"], start, n_days=1)
    calls_after_first = route.call_count
    second = await gate_events(client, cache, GATES["Dodd Narrows"], start, n_days=1)
    await client.aclose()
    cache.close()

    assert [e.kind for e in first] == ["slack", "ebb"]
    assert second == first
    assert calls_after_first == 1  # first call fetched exactly once
    assert route.call_count == calls_after_first  # second call served from cache


@respx.mock
async def test_gate_events_caches_empty_day(tmp_path):
    # A day with zero events must cache as [] and NOT be re-fetched.
    route = respx.get("https://api-sine.dfo-mpo.gc.ca/api/v1/stations/63aef1866a2b9417c035030f/data").mock(
        return_value=httpx.Response(200, json=[])
    )
    cache = EventCache(str(tmp_path / "c.sqlite"))
    cache.init_schema()
    client = RateLimitedClient()
    start = datetime(2026, 5, 24, 12, 0, tzinfo=timezone.utc)

    first = await gate_events(client, cache, GATES["Dodd Narrows"], start, n_days=1)
    second = await gate_events(client, cache, GATES["Dodd Narrows"], start, n_days=1)
    await client.aclose()
    cache.close()

    assert first == [] and second == []
    assert route.call_count == 1  # empty day cached, not re-fetched


NOAA_DAY = {"current_predictions": {"cp": [
    {"Type": "slack", "Time": "2026-05-24 08:42", "Velocity_Major": 0,
     "meanFloodDir": 3, "meanEbbDir": 236},
]}}


@respx.mock
async def test_gate_events_uses_noaa_for_boundary_pass(tmp_path):
    respx.get(url__regex=r".*api.tidesandcurrents.noaa.gov.*").mock(
        return_value=httpx.Response(200, json=NOAA_DAY)
    )
    cache = EventCache(str(tmp_path / "c.sqlite")); cache.init_schema()
    client = RateLimitedClient()
    events = await gate_events(client, cache, GATES["Boundary Pass"],
                               datetime(2026, 5, 24, tzinfo=timezone.utc), n_days=1)
    await client.aclose(); cache.close()
    assert [e.kind for e in events] == ["slack"]


async def test_gate_events_raises_for_unknown_provider(tmp_path):
    bogus = replace(GATES["Dodd Narrows"], provider="bogus")
    cache = EventCache(str(tmp_path / "c.sqlite")); cache.init_schema()
    client = RateLimitedClient()
    with pytest.raises(ProviderNotImplemented):
        await gate_events(client, cache, bogus, datetime(2026, 5, 24, tzinfo=timezone.utc), n_days=1)
    await client.aclose(); cache.close()
