import httpx
import respx

from tide_mcp.client import RateLimitedClient
from tide_mcp.providers import CurrentEvent, fetch_chs_events, fetch_noaa_events
from datetime import datetime, timezone

CHS_EVENTS = [
    {"eventDate": "2026-05-24T02:39:00Z", "qualifier": "EXTREMA_FLOOD", "value": 6.255},
    {"eventDate": "2026-05-24T06:14:00Z", "qualifier": "SLACK", "value": 0.0},
    {"eventDate": "2026-05-24T09:44:00Z", "qualifier": "EXTREMA_EBB", "value": 5.814},
]


def test_current_event_roundtrips_via_dict():
    e = CurrentEvent(datetime(2026, 5, 24, 6, 14, tzinfo=timezone.utc), "slack", 0.0)
    assert CurrentEvent.from_dict(e.to_dict()) == e


@respx.mock
async def test_fetch_chs_events_parses_qualifiers():
    route = respx.get("https://api-sine.dfo-mpo.gc.ca/api/v1/stations/STN/data").mock(
        return_value=httpx.Response(200, json=CHS_EVENTS)
    )
    client = RateLimitedClient()
    start = datetime(2026, 5, 24, tzinfo=timezone.utc)
    end = datetime(2026, 5, 25, tzinfo=timezone.utc)
    events = await fetch_chs_events(client, "STN", start, end)
    await client.aclose()

    assert route.called
    assert [e.kind for e in events] == ["flood", "slack", "ebb"]
    assert events[1].kind == "slack" and events[1].speed_knots == 0.0
    assert events[0].speed_knots == 6.255
    # request used the wcp1-events time series, not wlp-hilo
    assert route.calls[0].request.url.params["time-series-code"] == "wcp1-events"


@respx.mock
async def test_fetch_chs_events_skips_unknown_qualifiers():
    events_json = [*CHS_EVENTS, {"eventDate": "2026-05-24T12:00:00Z", "qualifier": "OTHER", "value": 3.0}]
    respx.get("https://api-sine.dfo-mpo.gc.ca/api/v1/stations/STN/data").mock(
        return_value=httpx.Response(200, json=events_json)
    )
    client = RateLimitedClient()
    start = datetime(2026, 5, 24, tzinfo=timezone.utc)
    end = datetime(2026, 5, 25, tzinfo=timezone.utc)
    events = await fetch_chs_events(client, "STN", start, end)
    await client.aclose()

    assert len(events) == 3  # the OTHER qualifier row is skipped
    assert [e.kind for e in events] == ["flood", "slack", "ebb"]


NOAA = {"current_predictions": {"cp": [
    {"Type": "slack", "Time": "2026-05-24 00:49", "Velocity_Major": 0,
     "meanFloodDir": 3, "meanEbbDir": 236},
    {"Type": "flood", "Time": "2026-05-24 04:55", "Velocity_Major": 2.88,
     "meanFloodDir": 3, "meanEbbDir": 236},
    {"Type": "ebb", "Time": "2026-05-24 10:58", "Velocity_Major": -1.35,
     "meanFloodDir": 3, "meanEbbDir": 236},
]}}


@respx.mock
async def test_fetch_noaa_events_parses_signed_velocity():
    respx.get(url__regex=r".*api.tidesandcurrents.noaa.gov.*").mock(
        return_value=httpx.Response(200, json=NOAA)
    )
    client = RateLimitedClient()
    start = datetime(2026, 5, 24, tzinfo=timezone.utc)
    end = datetime(2026, 5, 25, tzinfo=timezone.utc)
    events = await fetch_noaa_events(client, "PUG1717", 35, start, end)
    await client.aclose()

    assert [e.kind for e in events] == ["slack", "flood", "ebb"]
    assert events[2].kind == "ebb" and events[2].speed_knots == 1.35  # abs of -1.35
    assert events[0].flood_dir == 3 and events[0].ebb_dir == 236


@respx.mock
async def test_fetch_noaa_events_skips_unknown_type():
    payload = {"current_predictions": {"cp": [
        *NOAA["current_predictions"]["cp"],
        {"Type": "other", "Time": "2026-05-24 14:00", "Velocity_Major": 1.0,
         "meanFloodDir": 3, "meanEbbDir": 236},
    ]}}
    respx.get(url__regex=r".*api.tidesandcurrents.noaa.gov.*").mock(
        return_value=httpx.Response(200, json=payload)
    )
    client = RateLimitedClient()
    start = datetime(2026, 5, 24, tzinfo=timezone.utc)
    end = datetime(2026, 5, 25, tzinfo=timezone.utc)
    events = await fetch_noaa_events(client, "PUG1717", 35, start, end)
    await client.aclose()

    assert len(events) == 3  # the "other" Type row is skipped
    assert [e.kind for e in events] == ["slack", "flood", "ebb"]


def test_tide_height_event_roundtrips_via_dict():
    from tide_mcp.providers import TideHeightEvent
    e = TideHeightEvent(datetime(2026, 5, 26, 9, 48, tzinfo=timezone.utc), "high", 3.05)
    assert TideHeightEvent.from_dict(e.to_dict()) == e


def test_tide_height_event_to_dict_serializes_utc_as_iso():
    from tide_mcp.providers import TideHeightEvent
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
    from tide_mcp.providers import fetch_chs_height_events
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
    from tide_mcp.providers import fetch_chs_height_events
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
    from tide_mcp.providers import fetch_chs_height_events
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
    from tide_mcp.providers import fetch_chs_height_events
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
    from tide_mcp.providers import fetch_chs_stations
    route = respx.get("https://api-sine.dfo-mpo.gc.ca/api/v1/stations").mock(
        return_value=httpx.Response(200, json=STATIONS_JSON)
    )
    client = RateLimitedClient()
    stations = await fetch_chs_stations(client)
    await client.aclose()
    assert route.called
    assert len(stations) == 2
    assert stations[0]["id"] == "AAA"
