# tide-mcp

MCP server exposing Pacific Northwest tidal-gate slack windows (CHS current predictions) to agents.

See `docs/superpowers/specs/2026-05-24-tide-mcp-design.md` in the `sailingnaturali` repo for design.

## Run

    uv run tide-mcp

## Test

    uv run pytest -v --ignore=tests/test_integration_chs.py
