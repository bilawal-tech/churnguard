from simulator.core.state_store import StateStore


def tower(n, health="HEALTHY", **extra):
    row = {
        "tower_id": f"T{n:05d}", "health": health,
        "load": 0.5, "signal_dbm": -75.0,
    }
    row.update(extra)
    return row


def test_tower_roundtrip(tmp_path):
    s = StateStore(tmp_path / "s.db")
    with s.transaction():
        s.upsert_towers([tower(1, signal_dbm=-80.5)])
    t = s.get_tower("T00001")
    assert t["health"] == "HEALTHY"
    assert t["signal_dbm"] == -80.5
    assert s.get_tower("T99999") is None


def test_tower_optional_columns_default(tmp_path):
    s = StateStore(tmp_path / "s.db")
    with s.transaction():
        s.upsert_towers([tower(1)])
    t = s.get_tower("T00001")
    assert t["precursor_active"] == 0
    for col in ("failure_at", "precursor_start_hour", "dip_until_hour",
                "down_until_hour", "outage_id", "outage_cause",
                "outage_severity", "outage_affected_pct"):
        assert t[col] is None


def test_tower_upsert_updates_not_duplicates(tmp_path):
    s = StateStore(tmp_path / "s.db")
    with s.transaction():
        s.upsert_towers([tower(1), tower(2)])
        s.upsert_towers([tower(1, health="DOWN", down_until_hour=500,
                               outage_id="OUT-T00001-497")])
    assert len(s.all_towers()) == 2
    t = s.get_tower("T00001")
    assert t["health"] == "DOWN"
    assert t["down_until_hour"] == 500
    assert t["outage_id"] == "OUT-T00001-497"


def test_tower_rollback_on_error(tmp_path):
    s = StateStore(tmp_path / "s.db")
    try:
        with s.transaction():
            s.upsert_towers([tower(1)])
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert s.get_tower("T00001") is None


def test_tower_survives_reopen(tmp_path):
    p = tmp_path / "s.db"
    s = StateStore(p)
    with s.transaction():
        s.upsert_towers([tower(1, precursor_active=1, failure_at=700)])
    s.close()
    s2 = StateStore(p)
    t = s2.get_tower("T00001")
    assert t["precursor_active"] == 1
    assert t["failure_at"] == 700
    assert [x["tower_id"] for x in s2.all_towers()] == ["T00001"]