import httpx
import respx

from currents_mcp.client import RateLimitedClient


async def test_limiter_sleeps_when_window_full():
    clock = {"t": 0.0}
    slept = []

    def fake_now():
        return clock["t"]

    async def fake_sleep(secs):
        slept.append(secs)
        clock["t"] += secs  # advancing time frees the window

    client = RateLimitedClient(max_calls=2, period=60.0, now=fake_now, sleep=fake_sleep)

    with respx.mock:
        respx.get("https://example.test/x").mock(return_value=httpx.Response(200, json={"ok": True}))
        await client.get("https://example.test/x")
        await client.get("https://example.test/x")
        await client.get("https://example.test/x")  # third call must wait

    assert slept == [60.0], "third call should sleep until the oldest slot ages out"
    await client.aclose()
