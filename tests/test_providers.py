import httpx
import respx

from currents_mcp.client import RateLimitedClient
from currents_mcp.providers import CurrentEvent
from datetime import datetime, timezone


def test_current_event_roundtrips_via_dict():
    e = CurrentEvent(datetime(2026, 5, 24, 6, 14, tzinfo=timezone.utc), "slack", 0.0)
    assert CurrentEvent.from_dict(e.to_dict()) == e


def test_tide_height_event_roundtrips_via_dict():
    from currents_mcp.providers import TideHeightEvent
    e = TideHeightEvent(datetime(2026, 5, 26, 9, 48, tzinfo=timezone.utc), "high", 3.05)
    assert TideHeightEvent.from_dict(e.to_dict()) == e


def test_tide_height_event_to_dict_serializes_utc_as_iso():
    from currents_mcp.providers import TideHeightEvent
    e = TideHeightEvent(datetime(2026, 5, 26, 9, 48, tzinfo=timezone.utc), "low", 1.2)
    d = e.to_dict()
    assert d["utc"] == "2026-05-26T09:48:00+00:00"
    assert d["kind"] == "low"
    assert d["height_m"] == 1.2


HILO_STARTS_HIGH = [
    {"eventDate": "2026-05-26T09:48:00Z", "value": 3.05},
    {"eventDate": "2026-05-26T16:31:00Z", "value": 1.2},
    {"eventDate": "2026-05-26T23:05:00Z", "value": 2.7},
    {"eventDate": "2026-05-27T04:58:00Z", "value": 0.4},
]


@respx.mock
async def test_fetch_chs_height_events_classifies_starting_high():
    from currents_mcp.providers import fetch_chs_height_events
    route = respx.get("https://api-sine.dfo-mpo.gc.ca/api/v1/stations/STN/data").mock(
        return_value=httpx.Response(200, json=HILO_STARTS_HIGH)
    )
    client = RateLimitedClient()
    start = datetime(2026, 5, 26, tzinfo=timezone.utc)
    end = datetime(2026, 5, 27, tzinfo=timezone.utc)
    events = await fetch_chs_height_events(client, "STN", start, end)
    await client.aclose()

    assert [e.kind for e in events] == ["high", "low", "high", "low"]
    assert events[0].height_m == 3.05
    # request used the wlp-hilo time series, not wcp1-events
    assert route.calls[0].request.url.params["time-series-code"] == "wlp-hilo"


@respx.mock
async def test_fetch_chs_height_events_classifies_starting_low():
    from currents_mcp.providers import fetch_chs_height_events
    payload = [
        {"eventDate": "2026-05-26T07:00:00Z", "value": 0.5},
        {"eventDate": "2026-05-26T13:00:00Z", "value": 3.1},
    ]
    respx.get("https://api-sine.dfo-mpo.gc.ca/api/v1/stations/STN/data").mock(
        return_value=httpx.Response(200, json=payload)
    )
    client = RateLimitedClient()
    events = await fetch_chs_height_events(
        client, "STN", datetime(2026, 5, 26, tzinfo=timezone.utc),
        datetime(2026, 5, 27, tzinfo=timezone.utc),
    )
    await client.aclose()
    assert [e.kind for e in events] == ["low", "high"]


@respx.mock
async def test_fetch_chs_height_events_single_event_is_high():
    from currents_mcp.providers import fetch_chs_height_events
    respx.get("https://api-sine.dfo-mpo.gc.ca/api/v1/stations/STN/data").mock(
        return_value=httpx.Response(200, json=[{"eventDate": "2026-05-26T07:00:00Z", "value": 2.0}])
    )
    client = RateLimitedClient()
    events = await fetch_chs_height_events(
        client, "STN", datetime(2026, 5, 26, tzinfo=timezone.utc),
        datetime(2026, 5, 27, tzinfo=timezone.utc),
    )
    await client.aclose()
    assert [e.kind for e in events] == ["high"]


@respx.mock
async def test_fetch_chs_height_events_empty():
    from currents_mcp.providers import fetch_chs_height_events
    respx.get("https://api-sine.dfo-mpo.gc.ca/api/v1/stations/STN/data").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = RateLimitedClient()
    events = await fetch_chs_height_events(
        client, "STN", datetime(2026, 5, 26, tzinfo=timezone.utc),
        datetime(2026, 5, 27, tzinfo=timezone.utc),
    )
    await client.aclose()
    assert events == []


STATIONS_JSON = [
    {"id": "AAA", "officialName": "Near Station", "latitude": 48.76, "longitude": -123.05,
     "operating": True, "timeSeries": [{"code": "wlp-hilo"}]},
    {"id": "BBB", "officialName": "Current Only", "latitude": 49.0, "longitude": -123.5,
     "operating": True, "timeSeries": [{"code": "wcp1-events"}]},
]


@respx.mock
async def test_fetch_chs_stations_returns_raw_list():
    from currents_mcp.providers import fetch_chs_stations
    route = respx.get("https://api-sine.dfo-mpo.gc.ca/api/v1/stations").mock(
        return_value=httpx.Response(200, json=STATIONS_JSON)
    )
    client = RateLimitedClient()
    stations = await fetch_chs_stations(client)
    await client.aclose()
    assert route.called
    assert len(stations) == 2
    assert stations[0]["id"] == "AAA"


def test_classify_height_kinds_alternating():
    from currents_mcp.providers import _classify_height_kinds
    assert _classify_height_kinds([3.0, 1.0, 2.9, 1.1]) == ["high", "low", "high", "low"]
    assert _classify_height_kinds([1.0, 3.0]) == ["low", "high"]
    assert _classify_height_kinds([3.0]) == ["high"]
    assert _classify_height_kinds([]) == []


def test_classify_height_kinds_dropped_event_does_not_cascade():
    from currents_mcp.providers import _classify_height_kinds
    # A low was dropped after 3.1; the mislabel must stay at the seam, not
    # flip every label after it.
    kinds = _classify_height_kinds([3.0, 1.0, 3.1, 3.2, 1.1, 3.3])
    assert kinds[:2] == ["high", "low"]
    assert kinds[3:] == ["high", "low", "high"]   # downstream labels correct
