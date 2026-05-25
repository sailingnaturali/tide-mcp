from tide_mcp.cache import EventCache


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
