"""Live integration test. Hits a real signalk-currents /currents resource.

Enable with: CURRENTS_TEST_LIVE=1 SIGNALK_URL=http://naturalaspi.local:3000 \
    uv run pytest tests/test_integration_chs.py -v
"""

import os
from datetime import datetime, timezone

import pytest

from currents_mcp.currents_source import CurrentsClient
from currents_mcp.server import DEFAULT_SIGNALK_URL
from currents_mcp.tools import get_tidal_gate

pytestmark = pytest.mark.skipif(
    os.environ.get("CURRENTS_TEST_LIVE") != "1",
    reason="Set CURRENTS_TEST_LIVE=1 (and SIGNALK_URL) to run the live /currents test.",
)


async def test_boundary_pass_returns_slack_today():
    # Boundary Pass: in the Pi's station config and the vessel's (mocked) home
    # waters. Dodd Narrows is a known gate but not a configured station, so it
    # returns no windows live.
    currents = CurrentsClient(os.environ.get("SIGNALK_URL", DEFAULT_SIGNALK_URL))
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    result = await get_tidal_gate(currents, "Boundary Pass", date=today)
    assert result["name"] == "Boundary Pass"
    assert len(result["slack_windows"]) >= 1
    assert "slack" in result["slack_windows"][0]["display"]
    assert result["sets_display"] is not None  # plugin >= 0.3.0 deployed
