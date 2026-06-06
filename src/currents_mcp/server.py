"""currents-mcp server. Exposes tidal-gate tools to any MCP client over stdio.

Cache path comes from CURRENTS_CACHE_PATH (default ~/.currents-mcp/cache.sqlite).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from currents_mcp.cache import EventCache
from currents_mcp.client import RateLimitedClient
from currents_mcp.tools import get_passage_gates, get_tidal_gate, get_tide_heights, list_gates

logger = logging.getLogger(__name__)

TOOL_NAMES = ["get_passage_gates", "get_tidal_gate", "list_gates", "get_tide_heights"]


async def dispatch(client: RateLimitedClient, cache: EventCache, name: str, args: dict) -> dict:
    """Route a tool call to its implementation. Shared by the server and tests."""
    if name == "get_passage_gates":
        return await get_passage_gates(
            client, cache,
            destination=args["destination"],
            depart_time=args.get("depart_time"),
            from_lat=args.get("from_lat"),
            from_lon=args.get("from_lon"),
        )
    if name == "get_tidal_gate":
        return await get_tidal_gate(client, cache, name=args["name"], date=args.get("date"))
    if name == "list_gates":
        return list_gates()
    if name == "get_tide_heights":
        return await get_tide_heights(
            client, cache, lat=args["lat"], lon=args["lon"], date=args.get("date")
        )
    raise ValueError(f"Unknown tool: {name}")


def build_server(client: RateLimitedClient, cache: EventCache) -> Server:
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
                description="High/low tide heights for the nearest water-level station to a position.",
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
        result = await dispatch(client, cache, name, args or {})
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    return server


def main() -> None:
    cache_path = os.environ.get("CURRENTS_CACHE_PATH", str(Path.home() / ".currents-mcp" / "cache.sqlite"))
    Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
    cache = EventCache(cache_path)
    cache.init_schema()
    client = RateLimitedClient()
    server = build_server(client, cache)

    async def _run() -> None:
        try:
            async with stdio_server() as (read_stream, write_stream):
                await server.run(read_stream, write_stream, server.create_initialization_options())
        finally:
            await client.aclose()
            cache.close()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
