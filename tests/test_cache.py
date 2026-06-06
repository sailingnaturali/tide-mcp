import time

from currents_mcp.cache import EventCache


def test_get_missing_returns_none(tmp_path):
    cache = EventCache(str(tmp_path / "c.sqlite"))
    cache.init_schema()
    assert cache.get("chs:STN:2026-05-24") is None
    cache.close()


def test_put_then_get_roundtrips(tmp_path):
    cache = EventCache(str(tmp_path / "c.sqlite"))
    cache.init_schema()
    payload = [{"utc": "2026-05-24T06:14:00+00:00", "kind": "slack", "speed_knots": 0.0,
                "flood_dir": None, "ebb_dir": None}]
    cache.put("chs:STN:2026-05-24", payload)
    assert cache.get("chs:STN:2026-05-24") == payload
    cache.close()


def test_persists_across_instances(tmp_path):
    path = str(tmp_path / "c.sqlite")
    c1 = EventCache(path)
    c1.init_schema()
    c1.put("chs:STN:2026-05-24", [{"x": 1}])
    c1.close()
    c2 = EventCache(path)
    c2.init_schema()
    assert c2.get("chs:STN:2026-05-24") == [{"x": 1}]
    c2.close()


def test_put_with_ttl_roundtrips_within_ttl(tmp_path):
    cache = EventCache(str(tmp_path / "c.sqlite"))
    cache.init_schema()
    cache.put_with_ttl("chs:stations:wlp-hilo", [{"id": "AAA"}])
    assert cache.get_with_ttl("chs:stations:wlp-hilo", 3600) == [{"id": "AAA"}]
    cache.close()


def test_get_with_ttl_expires(tmp_path):
    cache = EventCache(str(tmp_path / "c.sqlite"))
    cache.init_schema()
    cache.put_with_ttl("k", [{"x": 1}])
    # A zero-second TTL means anything written before "now" is already stale.
    time.sleep(0.01)
    assert cache.get_with_ttl("k", 0) is None
    cache.close()


def test_immutable_get_put_still_work_after_ttl_columns(tmp_path):
    cache = EventCache(str(tmp_path / "c.sqlite"))
    cache.init_schema()
    cache.put("chs:STN:2026-05-26", [{"kind": "slack"}])
    assert cache.get("chs:STN:2026-05-26") == [{"kind": "slack"}]
    # immutable entries have no written_at, so get_with_ttl never returns them
    assert cache.get_with_ttl("chs:STN:2026-05-26", 3600) is None
    cache.close()


def test_init_schema_upgrades_legacy_db(tmp_path):
    # Simulate a v0.1.0 cache file that predates the written_at column.
    import sqlite3
    path = str(tmp_path / "legacy.sqlite")
    legacy = sqlite3.connect(path)
    legacy.executescript(
        "CREATE TABLE events_cache (key TEXT PRIMARY KEY, payload TEXT NOT NULL);"
    )
    legacy.execute("INSERT INTO events_cache (key, payload) VALUES (?, ?)",
                   ("chs:STN:2026-05-26", '[{"kind": "slack"}]'))
    legacy.commit()
    legacy.close()

    cache = EventCache(path)
    cache.init_schema()  # must ALTER TABLE to add written_at, idempotently
    # legacy immutable data survives
    assert cache.get("chs:STN:2026-05-26") == [{"kind": "slack"}]
    # and the new TTL API works against the upgraded schema
    cache.put_with_ttl("k", [{"x": 1}])
    assert cache.get_with_ttl("k", 3600) == [{"x": 1}]
    # calling init_schema again is a no-op (no duplicate-column error)
    cache.init_schema()
    cache.close()
