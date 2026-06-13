"""currents-mcp server. Exposes tidal-gate tools to any MCP client over stdio."""

from __future__ import annotations

import asyncio
import json
import logging
import os

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from currents_mcp.currents_source import CurrentsClient
from currents_mcp.tides_source import TidesClient
from currents_mcp.tools import get_passage_gates, get_tidal_gate, get_tide_heights, list_gates

logger = logging.getLogger(__name__)

TOOL_NAMES = ["get_passage_gates", "get_tidal_gate", "list_gates", "get_tide_heights"]

# The boat's SignalK server (Pi 5). Not localhost: the mac-dev rig is retired,
# and an unreachable /currents degrades silently to empty slack windows.
DEFAULT_SIGNALK_URL = "http://naturalaspi.local:3000"


async def dispatch(
    currents: CurrentsClient, tides: TidesClient, name: str, args: dict
) -> dict:
    """Route a tool call to its implementation. Shared by the server and tests."""
    if name == "get_passage_gates":
        return await get_passage_gates(
            currents,
            destination=args["destination"],
            depart_time=args.get("depart_time"),
            from_lat=args.get("from_lat"),
            from_lon=args.get("from_lon"),
        )
    if name == "get_tidal_gate":
        return await get_tidal_gate(currents, name=args["name"], date=args.get("date"))
    if name == "list_gates":
        return list_gates()
    if name == "get_tide_heights":
        return await get_tide_heights(
            tides, lat=args["lat"], lon=args["lon"], date=args.get("date")
        )
    raise ValueError(f"Unknown tool: {name}")


def build_server(currents: CurrentsClient, tides: TidesClient) -> Server:
    server = Server("currents-mcp")

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name="get_passage_gates",
                description="Tidal gates, slack windows, and a recommended departure for a destination.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "destination": {"type": "string", "description": "e.g. 'Desolation Sound', 'Nanaimo'."},
                        "depart_time": {"type": "string", "description": "ISO8601; defaults to now."},
                        "from_lat": {"type": "number", "description": "Current latitude (decimal degrees)."},
                        "from_lon": {"type": "number", "description": "Current longitude (decimal degrees)."},
                    },
                    "required": ["destination"],
                },
            ),
            types.Tool(
                name="get_tidal_gate",
                description="Next 3 slack windows for a single named tidal gate.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Gate name, e.g. 'Dodd Narrows'."},
                        "date": {"type": "string", "description": "ISO date; defaults to today."},
                    },
                    "required": ["name"],
                },
            ),
            types.Tool(
                name="list_gates",
                description="Known destinations and the tidal gates they cover.",
                inputSchema={"type": "object", "properties": {}},
            ),
            types.Tool(
                name="get_tide_heights",
                description=(
                    "High/low tide heights for the nearest tide station to a position. "
                    "Offline predictions from the boat server (signalk-tides/Neaps), "
                    "relative to LAT — chart datum sits above LAT by up to ~0.4 m at "
                    "some stations, so these read higher than official tide tables by "
                    "that fixed offset."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "lat": {"type": "number", "description": "Latitude (decimal degrees)."},
                        "lon": {"type": "number", "description": "Longitude (decimal degrees)."},
                        "date": {"type": "string", "description": "ISO date; defaults to today."},
                    },
                    "required": ["lat", "lon"],
                },
            ),
        ]

    @server.call_tool()
    async def _call_tool(name: str, args: dict | None) -> list[types.TextContent]:
        result = await dispatch(currents, tides, name, args or {})
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    return server


def main() -> None:
    signalk_url = os.environ.get("SIGNALK_URL", DEFAULT_SIGNALK_URL)
    currents = CurrentsClient(signalk_url)
    tides = TidesClient(signalk_url)
    server = build_server(currents, tides)

    async def _run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(_run())


if __name__ == "__main__":
    main()
