from simulator.common import load_config
from simulator.core.clock import SimClock
from simulator.core.engine import BandContext
from simulator.core.state_store import StateStore
from simulator.masters.packages import build_packages
from simulator.offers.engine import is_control
from simulator.offers.hooks import make_offer_hook


def _treatment_cid(seed):
    for i in range(1, 50):
        cid = f"C{i:07d}"
        if not is_control(seed, cid):
            return cid
    raise AssertionError("No treatment customer found")


def _seed_customer(store, cid, balance=40.0, plan_type="prepaid", status="ACTIVE"):
    store.upsert_customers([{
        "customer_id": cid,
        "plan_type": plan_type,
        "status": status,
        "status_since": 0,
        "balance": balance,
        "home_tower_id": "T01001",
        "last_active": 0,
        "at_risk": 0,
        "zero_balance_since": None,
        "at_risk_since": None,
    }])
    store.conn.commit()


def test_non_evening_records_activity_and_returns_empty(tmp_path):
    cfg = load_config("config_test.yaml")
    packages = build_packages()
    store = StateStore(str(tmp_path / "sim.db"))
    cid = _treatment_cid(cfg["seed"])
    _seed_customer(store, cid, balance=20.0)

    store.insert_offer({
        "offer_id": f"OFR-{cid}-0-RECHARGE_BONUS",
        "customer_id": cid,
        "offer_type": "RECHARGE_BONUS",
        "grp": "treatment",
        "sent_date": "2026-04-01",
        "window_end_date": "2026-04-08",
        "status": "OPEN",
        "recharge_target": 300.0,
        "recharge_total": 100.0,
    })
    store.conn.commit()

    clock = SimClock(cfg["start_date"], cfg["history_days"], index=1)  # Morning
    ctx = BandContext(clock=clock, store=store, next_customer_no=1)
    ctx.band_events.append(("usage_events", {
        "customer_id": cid,
        "data_mb_whatsapp": 50.0,
        "data_mb_social": 25.0,
        "data_mb_video": 0.0,
        "data_mb_browsing": 10.0,
        "data_mb_other": 5.0,
        "calls_offnet_min": 4.0,
        "calls_intl_min": 1.0,
    }))
    ctx.band_events.append(("recharge_events", {
        "customer_id": cid,
        "amount_pkr": 200,
    }))

    hook = make_offer_hook(cfg, packages)
    out = hook(ctx)
    store.conn.commit()

    assert out == []
    daily = store.get_offer_daily(cid, "2026-04-01")
    assert len(daily) == 1
    assert daily[0]["data_mb"] == 90.0
    assert daily[0]["call_min"] == 5.0
    assert store.get_offer(f"OFR-{cid}-0-RECHARGE_BONUS")["recharge_total"] == 300.0
    store.close()


def test_evening_sends_recharge_offer_and_respects_gap(tmp_path):
    cfg = load_config("config_test.yaml")
    packages = build_packages()
    store = StateStore(str(tmp_path / "sim.db"))
    cid = _treatment_cid(cfg["seed"])
    _seed_customer(store, cid, balance=30.0)

    hook = make_offer_hook(cfg, packages)

    # Day 0 Evening (index = 3)
    ctx0 = BandContext(clock=SimClock(cfg["start_date"], cfg["history_days"], index=3), store=store, next_customer_no=1)
    ev0 = hook(ctx0)
    store.conn.commit()

    assert len(ev0) == 1
    topic, payload = ev0[0]
    assert topic == "offer_events"
    assert payload["offer_type"] == "RECHARGE_BONUS"
    assert payload["action"] == "SENT"
    assert payload["group"] == "treatment"

    # Day 1 Evening (index = 7): still OPEN, so no duplicate offer
    ctx1 = BandContext(clock=SimClock(cfg["start_date"], cfg["history_days"], index=7), store=store, next_customer_no=1)
    assert hook(ctx1) == []
    store.close()


def test_recharge_offer_accepts_and_grants_free_package(tmp_path):
    cfg = load_config("config_test.yaml")
    packages = build_packages()
    store = StateStore(str(tmp_path / "sim.db"))
    cid = _treatment_cid(cfg["seed"])
    _seed_customer(store, cid, balance=250.0)

    oid = f"OFR-{cid}-3-RECHARGE_BONUS"
    store.insert_offer({
        "offer_id": oid,
        "customer_id": cid,
        "offer_type": "RECHARGE_BONUS",
        "grp": "treatment",
        "sent_date": "2026-04-01",
        "window_end_date": "2026-04-08",
        "status": "OPEN",
        "recharge_target": 300.0,
        "recharge_total": 300.0,
    })
    store.conn.commit()

    hook = make_offer_hook(cfg, packages)
    ctx = BandContext(clock=SimClock(cfg["start_date"], cfg["history_days"], index=7), store=store, next_customer_no=1)
    events = hook(ctx)
    store.conn.commit()

    offer_evs = [e for t, e in events if t == "offer_events"]
    pkg_evs = [e for t, e in events if t == "package_events"]
    assert len(offer_evs) == 1
    assert offer_evs[0]["action"] == "ACCEPTED"
    assert len(pkg_evs) == 1
    assert pkg_evs[0]["action"] == "PURCHASE"
    assert pkg_evs[0]["price_pkr"] == 0
    assert store.get_offer(oid)["status"] == "ACCEPTED"
    active = store.get_active_packages(cid)
    assert len(active) == 1
    assert active[0]["auto_renew"] == 0
    store.close()


def test_expired_offer_closes_after_window(tmp_path):
    cfg = load_config("config_test.yaml")
    packages = build_packages()
    store = StateStore(str(tmp_path / "sim.db"))
    cid = _treatment_cid(cfg["seed"])
    _seed_customer(store, cid, balance=250.0)

    oid = f"OFR-{cid}-3-RECHARGE_BONUS"
    store.insert_offer({
        "offer_id": oid,
        "customer_id": cid,
        "offer_type": "RECHARGE_BONUS",
        "grp": "treatment",
        "sent_date": "2026-04-01",
        "window_end_date": "2026-04-08",
        "status": "OPEN",
        "recharge_target": 600.0,
        "recharge_total": 100.0,
    })
    store.conn.commit()

    # 2026-04-09 is day index 8 -> Evening band = 8*4 + 3 = 35
    hook = make_offer_hook(cfg, packages)
    ctx = BandContext(clock=SimClock(cfg["start_date"], cfg["history_days"], index=35), store=store, next_customer_no=1)
    events = hook(ctx)
    store.conn.commit()

    assert len(events) == 1
    assert events[0][0] == "offer_events"
    assert events[0][1]["action"] == "EXPIRED"
    assert store.get_offer(oid)["status"] == "EXPIRED"
    store.close()