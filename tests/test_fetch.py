from datetime import datetime, timezone

import httpx
import respx

from currents_mcp.cache import EventCache
from currents_mcp.client import RateLimitedClient

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
    from currents_mcp.fetch import get_cached_stations
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
    from currents_mcp.fetch import _nearest_height_station
    stations = [
        {"id": "AAA", "officialName": "Near", "latitude": 48.76, "longitude": -123.05},
        {"id": "BBB", "officialName": "Far", "latitude": 50.0, "longitude": -125.0},
    ]
    nearest = _nearest_height_station(48.76, -123.05, stations)
    assert nearest["id"] == "AAA"


@respx.mock
async def test_tide_height_events_orchestrates(tmp_path):
    from currents_mcp.fetch import tide_height_events
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
    from currents_mcp.fetch import tide_height_events
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
    from currents_mcp.fetch import tide_height_events
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
