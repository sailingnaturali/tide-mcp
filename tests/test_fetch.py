from dataclasses import replace
from datetime import datetime, timezone

import httpx
import pytest
import respx

from tide_mcp.cache import EventCache
from tide_mcp.client import RateLimitedClient
from tide_mcp.fetch import ProviderNotImplemented, gate_events
from tide_mcp.passages import GATES

HEIGHT_STATIONS = [
    {"id": "AAA", "officialName": "Near Station", "latitude": 48.76, "longitude": -123.05,
     "operating": True, "timeSeries": [{"code": "wlp-hilo"}]},
    {"id": "BBB", "officialName": "Far Station", "latitude": 50.0, "longitude": -125.0,
     "operating": True, "timeSeries": [{"code": "wlp-hilo"}]},
    {"id": "CCC", "officialName": "Current Only", "latitude": 48.77, "longitude": -123.06,
     "operating": True, "timeSeries": [{"code": "wcp1-events"}]},
    {"id": "DDD", "officialName": "Not Operating", "latitude": 48.76, "longitude": -123.05,
     "operating": False, "timeSeries": [{"code": "wlp-hilo"}]},
]

HILO_DAY = [
    {"eventDate": "2026-05-26T09:48:00Z", "value": 3.0},
    {"eventDate": "2026-05-26T16:31:00Z", "value": 1.2},
]


@respx.mock
async def test_get_cached_stations_filters_and_caches(tmp_path):
    from tide_mcp.fetch import get_cached_stations
    route = respx.get("https://api-sine.dfo-mpo.gc.ca/api/v1/stations").mock(
        return_value=httpx.Response(200, json=HEIGHT_STATIONS)
    )
    cache = EventCache(str(tmp_path / "c.sqlite")); cache.init_schema()
    client = RateLimitedClient()

    first = await get_cached_stations(client, cache)
    second = await get_cached_stations(client, cache)
    await client.aclose(); cache.close()

    # only operating wlp-hilo stations survive the filter (AAA, BBB)
    ids = sorted(s["id"] for s in first)
    assert ids == ["AAA", "BBB"]
    # 24h TTL means the station list is fetched exactly once across two calls
    assert route.call_count == 1
    assert second == first


def test_nearest_height_station_picks_closest():
    from tide_mcp.fetch import _nearest_height_station
    stations = [
        {"id": "AAA", "officialName": "Near", "latitude": 48.76, "longitude": -123.05},
        {"id": "BBB", "officialName": "Far", "latitude": 50.0, "longitude": -125.0},
    ]
    nearest = _nearest_height_station(48.76, -123.05, stations)
    assert nearest["id"] == "AAA"


@respx.mock
async def test_tide_height_events_orchestrates(tmp_path):
    from tide_mcp.fetch import tide_height_events
    respx.get("https://api-sine.dfo-mpo.gc.ca/api/v1/stations").mock(
        return_value=httpx.Response(200, json=HEIGHT_STATIONS)
    )
    respx.get("https://api-sine.dfo-mpo.gc.ca/api/v1/stations/AAA/data").mock(
        return_value=httpx.Response(200, json=HILO_DAY)
    )
    cache = EventCache(str(tmp_path / "c.sqlite")); cache.init_schema()
    client = RateLimitedClient()
    start = datetime(2026, 5, 26, 12, 0, tzinfo=timezone.utc)

    info, events = await tide_height_events(client, cache, 48.76, -123.05, start, n_days=1)
    await client.aclose(); cache.close()

    assert info["station_name"] == "Near Station"
    assert info["distance_km"] >= 0
    assert [e.kind for e in events] == ["high", "low"]


@respx.mock
async def test_tide_height_events_reclassifies_across_days(tmp_path):
    """Each cached day is classified independently; a one-event day at the seam
    would mis-alternate without the orchestrator-level reclassify."""
    from tide_mcp.fetch import tide_height_events
    respx.get("https://api-sine.dfo-mpo.gc.ca/api/v1/stations").mock(
        return_value=httpx.Response(200, json=HEIGHT_STATIONS)
    )

    def by_day(request):
        from_str = request.url.params.get("from", "")
        if from_str.startswith("2026-05-26"):
            # Day ends with a HIGH at 22:00Z.
            return httpx.Response(200, json=[
                {"eventDate": "2026-05-26T16:00:00Z", "value": 0.8},
                {"eventDate": "2026-05-26T22:00:00Z", "value": 3.5},
            ])
        # Day 2 has a single event — per-day classification would call this a
        # "high" by default. Joined with day 1's trailing high, it must be a low.
        return httpx.Response(200, json=[{"eventDate": "2026-05-27T04:00:00Z", "value": 1.0}])

    respx.get("https://api-sine.dfo-mpo.gc.ca/api/v1/stations/AAA/data").mock(side_effect=by_day)
    cache = EventCache(str(tmp_path / "c.sqlite")); cache.init_schema()
    client = RateLimitedClient()
    start = datetime(2026, 5, 26, tzinfo=timezone.utc)
    _, events = await tide_height_events(client, cache, 48.76, -123.05, start, n_days=2)
    await client.aclose(); cache.close()

    assert [e.kind for e in events] == ["low", "high", "low"]


@respx.mock
async def test_tide_height_events_caches_day(tmp_path):
    from tide_mcp.fetch import tide_height_events
    respx.get("https://api-sine.dfo-mpo.gc.ca/api/v1/stations").mock(
        return_value=httpx.Response(200, json=HEIGHT_STATIONS)
    )
    data_route = respx.get("https://api-sine.dfo-mpo.gc.ca/api/v1/stations/AAA/data").mock(
        return_value=httpx.Response(200, json=HILO_DAY)
    )
    cache = EventCache(str(tmp_path / "c.sqlite")); cache.init_schema()
    client = RateLimitedClient()
    start = datetime(2026, 5, 26, 12, 0, tzinfo=timezone.utc)

    await tide_height_events(client, cache, 48.76, -123.05, start, n_days=1)
    await tide_height_events(client, cache, 48.76, -123.05, start, n_days=1)
    await client.aclose(); cache.close()

    # per-day height predictions are immutable -> fetched once
    assert data_route.call_count == 1

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
