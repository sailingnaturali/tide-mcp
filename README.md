# tide-mcp

MCP server exposing Pacific Northwest tidal-gate slack windows to agents. Covers CHS current-prediction stations (BC waters) and NOAA CO-OPS (US waters). Reports next slack windows, transit windows, and recommended departure times for named tidal gates and destination passages.

See `docs/superpowers/specs/2026-05-24-tide-mcp-design.md` in the `sailingnaturali` repo for design.

## Tools

### `get_passage_gates(destination, depart_time?, from_lat?, from_lon?)`

Maps a destination string to its ordered tidal gates, returns next slack windows for each gate, and a recommended departure time for the first gate.

- Unknown destination: returns `{"unmatched": true, "suggestions_display": ...}`
- Open-water destination (no gates): returns `{"destination", "gates": [], "summary_display": "No tidal gates on the direct route - open-water passage; wind and weather are the constraint."}`

Example response:

```json
{
  "destination": "Cordero Channel",
  "gates": [
    {
      "name": "Gillard Passage",
      "slack_windows": [
        {"display": "Sun 21:14 PDT (slack, ebb→flood)", "utc": "2026-05-25T04:14:00Z"}
      ],
      "transit_window_minutes": 20,
      "recommended_depart_display": "Depart by 18:45 PDT to hit Gillard Passage at slack."
    },
    {
      "name": "Dent Rapids",
      "slack_windows": [
        {"display": "Mon 02:10 PDT (slack, ebb→flood)", "utc": "2026-05-25T09:10:00Z"}
      ],
      "transit_window_minutes": 20,
      "recommended_depart_display": null,
      "note_display": "Slack windows shown for planning; v1 does not compute multi-gate departure."
    }
  ],
  "summary_display": "2 tidal gate(s). Depart by 18:45 PDT to hit Gillard Passage at slack."
}
```

### `get_tidal_gate(name, date?)`

Returns the next 3 slack windows for a single named gate: `{"name", "slack_windows", "transit_window_minutes"}`. Unknown gate name returns `{"unmatched": true, "suggestions_display": ...}`.

### `list_gates()`

Returns all covered destinations and the gates they route through: `{"coverage": [{"destination", "aliases", "gates"}, ...], "display": "..."}`.

## Coverage

CHS (BC): Dodd Narrows, Active Pass, Porlier Pass, Gabriola Passage, Seymour Narrows, Beazley Passage (Surge Narrows), Hole in the Wall, Gillard Passage, Dent Rapids.

NOAA (US): Boundary Pass (San Juans / Friday Harbor).

Open-water destinations (no gates): Desolation Sound, Cortes Island, Campbell River, Gulf Islands.

## Data sources

- CHS IWLS current stations (BC)
- NOAA CO-OPS (US)

Current speeds in knots. Times rendered in America/Vancouver (PDT/PST).

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `TIDE_CACHE_PATH` | `~/.tide-mcp/cache.sqlite` | Path to the SQLite response cache |

## Run

    uv run tide-mcp

## Test

    uv run pytest -v --ignore=tests/test_integration_chs.py
