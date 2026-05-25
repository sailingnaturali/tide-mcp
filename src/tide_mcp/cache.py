"""Disk-backed cache for current-prediction events.

Keyed `provider:station:utc_date`. Predictions for a given station-day are
immutable, so entries never expire.
"""

from __future__ import annotations

import json
import sqlite3


class EventCache:
    """SQLite key->JSON store. Call init_schema() once before get/put.

    All access is synchronous and expected on a single thread (the MCP server's
    event-loop thread).
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self._conn = sqlite3.connect(path)

    def init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS events_cache (
                key     TEXT PRIMARY KEY,
                payload TEXT NOT NULL
            );
            """
        )
        self._conn.commit()

    def get(self, key: str) -> list[dict] | None:
        cur = self._conn.execute("SELECT payload FROM events_cache WHERE key = ?", (key,))
        row = cur.fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, payload: list[dict]) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO events_cache (key, payload) VALUES (?, ?)",
            (key, json.dumps(payload)),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
