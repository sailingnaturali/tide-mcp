"""Live CHS integration test. Hits the real API.

Enable with: TIDE_TEST_LIVE=1 uv run pytest tests/test_integration_chs.py -v
"""

import os
from datetime import datetime, timezone

import pytest

from tide_mcp.cache import EventCache
from tide_mcp.client import RateLimitedClient
from tide_mcp.tools import get_tidal_gate

pytestmark = pytest.mark.skipif(
    os.environ.get("TIDE_TEST_LIVE") != "1",
    reason="Set TIDE_TEST_LIVE=1 to run live CHS integration tests.",
)


async def test_dodd_narrows_returns_slack_today(tmp_path):
    cache = EventCache(str(tmp_path / "c.sqlite")); cache.init_schema()
    client = RateLimitedClient()
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        result = await get_tidal_gate(client, cache, "Dodd Narrows", date=today)
        assert result["name"] == "Dodd Narrows"
        assert len(result["slack_windows"]) >= 1
        assert "slack" in result["slack_windows"][0]["display"]
    finally:
        await client.aclose(); cache.close()
