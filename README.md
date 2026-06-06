# currents-mcp

MCP server exposing Pacific Northwest tidal-gate slack windows to agents. Tidal-current predictions are read from the [`signalk-currents`](https://github.com/sailingnaturali) plugin's `/currents` resource (the plugin owns CHS/NOAA fetching and caching); this server maps named gates and destination passages onto those predictions and reports next slack windows, transit windows, and recommended departure times.

Design notes live in the private `sailingnaturali` repo at `docs/superpowers/specs/2026-05-24-tide-mcp-design.md`; the rename/refactor plan is `docs/superpowers/plans/2026-06-05-currents-mcp.md`.

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
      "note_display": "Slack windows shown for planning; the recommended departure covers the first gate only."
    }
  ],
  "summary_display": "2 tidal gate(s). Depart by 18:45 PDT to hit Gillard Passage at slack."
}
```

### `get_tidal_gate(name, date?)`

Returns the next 3 slack windows for a single named gate: `{"name", "slack_windows", "transit_window_minutes"}`. Unknown gate name returns `{"unmatched": true, "suggestions_display": ...}`.

### `list_gates()`

Returns all covered destinations and the gates they route through: `{"coverage": [{"destination", "aliases", "gates"}, ...], "display": "..."}`.

### `get_tide_heights(lat, lon, date?)`

Returns high/low tide height events from the nearest CHS water-level station. Use for anchor planning ("when is low tide here?") and any question about tidal range.

> **Vestigial pending Phase 2.** Heights are still fetched from CHS directly inside this server (the only remaining direct-fetch path). Phase 2 moves heights into `signalk-tides`/`signalk-currents` and removes this tool from `currents-mcp`.

- `lat`, `lon`: vessel or target position in decimal degrees
- `date`: optional ISO date string (defaults to today)

Example response:

```json
{
  "station_name": "Tsawwassen",
  "distance_km": 18.3,
  "events": [
    {"display": "Low 06:14 PDT — 0.9 m", "type": "low", "height_m": 0.9, "utc": "2026-05-26T13:14:00Z"},
    {"display": "High 12:38 PDT — 3.8 m", "type": "high", "height_m": 3.8, "utc": "2026-05-26T19:38:00Z"},
    {"display": "Low 18:47 PDT — 1.0 m", "type": "low", "height_m": 1.0, "utc": "2026-05-27T01:47:00Z"}
  ],
  "summary_display": "Nearest tide station: Tsawwassen, 18.3 km from you. Next low is 06:14 PDT — 0.9 m."
}
```

Data source: CHS IWLS water-level (`wlp-hilo`) stations. Station list cached 24 h; per-day predictions cached indefinitely (immutable). Two UTC days are queried so the local-day tail isn't dropped when called late in a PDT day; the next ~4 events at/after the query time are returned.

## Coverage

**Destinations** (resolvable via `get_passage_gates`):

- Gated: Nanaimo, Discovery Islands, Johnstone Strait via Discovery Passage, Cordero Channel, Friday Harbor.
- Open water (no gates): Gulf Islands, Desolation Sound, Cortes Island, Campbell River.

**Named tidal gates** (resolvable via `get_tidal_gate`):

- BC: Dodd Narrows, Active Pass, Porlier Pass, Gabriola Passage, Seymour Narrows, Beazley Passage (Surge Narrows), Hole in the Wall, Gillard Passage, Dent Rapids.
- US: Boundary Pass (San Juans / Friday Harbor).

Active Pass, Porlier Pass, Gabriola Passage, and Hole in the Wall are addressable by name but are not yet wired into any Victoria-origin passage.

The gate-to-station mapping lives in `passages.py`; the `signalk-currents` plugin must be configured with the matching station list so every gate's `station_id` is present in `/currents`. A gate whose station is missing from the payload returns no slack windows.

## Data sources

- `signalk-currents` plugin `/currents` resource (CHS `wcp1-events` BC + NOAA CO-OPS US, fetched/cached by the plugin) — tidal gate slack windows
- CHS IWLS water-level stations (`wlp-hilo`, BC) — tide heights (fetched directly here, pending Phase 2)

Current speeds in knots. Heights in metres. Times rendered in America/Vancouver (PDT/PST).

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SIGNALK_URL` | `http://localhost:3000` | Base URL of the SignalK server running `signalk-currents`; the gate tools GET `/plugins/signalk-currents/currents` from here |
| `CURRENTS_CACHE_PATH` | `~/.currents-mcp/cache.sqlite` | Path to the SQLite response cache (tide-height predictions) |

## Run

    SIGNALK_URL=http://naturalaspi.local:3000 uv run currents-mcp

## Test

    uv run pytest -v --ignore=tests/test_integration_chs.py
