import httpx
import respx

from tide_mcp.client import RateLimitedClient
from tide_mcp.providers import CurrentEvent, fetch_chs_events
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
