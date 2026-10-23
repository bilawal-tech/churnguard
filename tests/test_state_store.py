from simulator.core.state_store import StateStore


def cust(n, balance=100.0):
    return {
        "customer_id": f"C{n:07d}", "plan_type": "prepaid",
        "status": "ACTIVE", "status_since": 0, "balance": balance,
        "home_tower_id": "T01001", "last_active": 0, "at_risk": 0,
    }


def test_meta_roundtrip(tmp_path):
    s = StateStore(tmp_path / "s.db")
    assert s.get_meta("index") is None
    s.set_meta("index", 7)
    s.set_meta("index", 8)
    assert s.get_meta("index") == "8"


def test_upsert_updates_not_duplicates(tmp_path):
    s = StateStore(tmp_path / "s.db")
    s.upsert_customers([cust(1), cust(2)])
    s.upsert_customers([cust(1, balance=55.0)])
    assert s.count_customers() == 2
    assert s.get_customer("C0000001")["balance"] == 55.0


def test_rollback_on_error(tmp_path):
    s = StateStore(tmp_path / "s.db")
    try:
        with s.transaction():
            s.upsert_customers([cust(1)])
            s.set_meta("index", 5)
            raise RuntimeError("crash")
    except RuntimeError:
        pass
    assert s.count_customers() == 0
    assert s.get_meta("index") is None


def test_survives_reopen(tmp_path):
    p = tmp_path / "s.db"
    s = StateStore(p)
    with s.transaction():
        s.upsert_customers([cust(1)])
        s.set_meta("index", 12)
    s.close()
    s2 = StateStore(p)
    assert s2.count_customers() == 1
    assert s2.get_meta("index") == "12"