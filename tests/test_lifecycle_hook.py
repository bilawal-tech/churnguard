from types import SimpleNamespace

import pytest

from simulator.common import load_config
from simulator.core.clock import SimClock
from simulator.core.state_store import StateStore
from simulator.lifecycle import model as m
from simulator.lifecycle.hooks import make_lifecycle_hook


@pytest.fixture(scope="module")
def cfg():
    return load_config("config_test.yaml")


def _row(cid, plan="prepaid", status="ACTIVE", balance=100.0, last_active=0):
    return {
        "customer_id": cid, "plan_type": plan, "status": status,
        "status_since": 0, "balance": balance, "home_tower_id": "T01001",
        "last_active": last_active, "at_risk": 0,
    }


def _usage(cid, pkg=4.0, bal=6.0, onnet=3, offnet=3, dropped=1):
    return {
        "customer_id": cid, "spend_from_package": pkg, "spend_from_balance": bal,
        "calls_onnet_min": onnet, "calls_offnet_min": offnet, "calls_intl_min": 0,
        "dropped_calls": dropped,
    }


def _ctx(cfg, store, index, usage=()):
    return SimpleNamespace(
        clock=SimClock.from_config(cfg, index=index), store=store,
        band_events_for=lambda topic: list(usage) if topic == "usage_events" else [],
    )


def _evening(day):
    return day * 4 + 3


def test_records_daily_usage_and_waits_for_evening(cfg, tmp_path):
    store = StateStore(tmp_path / "s.db")
    hook = make_lifecycle_hook(cfg)
    assert hook(_ctx(cfg, store, 0, [_usage("C0000001")])) == []
    assert hook(_ctx(cfg, store, 1, [_usage("C0000001", pkg=10.0, bal=10.0,
                                            onnet=6, dropped=0)])) == []
    row = store.conn.execute(
        "SELECT usage, calls, dropped_calls FROM customer_daily "
        "WHERE customer_id='C0000001' AND day=0").fetchone()
    assert row["usage"] == pytest.approx(30.0)
    assert row["calls"] == 5
    assert row["dropped_calls"] == 1


def test_inactivity_suspend_then_churn(cfg, tmp_path):
    store = StateStore(tmp_path / "s.db")
    store.upsert_customers([_row("C0000001", last_active=0)])
    hook = make_lifecycle_hook(cfg)

    events = hook(_ctx(cfg, store, _evening(14)))
    ev = [x for t, x in events if t == "lifecycle_events"][0]
    assert (ev["from_status"], ev["to_status"]) == ("ACTIVE", "SUSPENDED")
    assert ev["inactivity_days"] == 14 and ev["churn_reason"] is None
    assert store.get_customer("C0000001")["status"] == "SUSPENDED"

    events = hook(_ctx(cfg, store, _evening(30)))
    ev = [x for t, x in events if t == "lifecycle_events"][0]
    assert (ev["from_status"], ev["to_status"]) == ("SUSPENDED", "CHURNED")
    assert ev["churn_reason"] == m.INACTIVITY and ev["inactivity_days"] == 30
    assert store.get_customer("C0000001")["status"] == "CHURNED"


def test_postpaid_never_suspended(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(m, "BASE_DAILY_CHURN", 0.0)
    store = StateStore(tmp_path / "s.db")
    store.upsert_customers([_row("C0000001", plan="postpaid", balance=0.0)])
    events = make_lifecycle_hook(cfg)(_ctx(cfg, store, _evening(40)))
    assert events == []
    assert store.get_customer("C0000001")["status"] == "ACTIVE"


def test_forced_risk_churn(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(m, "BASE_DAILY_CHURN", 10.0)
    monkeypatch.setattr(m, "NOISE_SD", 0.0)
    store = StateStore(tmp_path / "s.db")
    store.upsert_customers([_row("C0000001", last_active=_evening(5))])
    events = make_lifecycle_hook(cfg)(_ctx(cfg, store, _evening(5)))
    ev = [x for t, x in events if t == "lifecycle_events"][0]
    assert (ev["from_status"], ev["to_status"]) == ("ACTIVE", "CHURNED")
    assert ev["churn_reason"] in (m.HIGH_PRICE, m.COMPETITOR_OFFER)
    assert ev["inactivity_days"] is None
    assert store.get_customer("C0000001")["status"] == "CHURNED"


def test_reactivation(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(m, "REACTIVATE_CHANCE_PER_DAY", 1.0)
    store = StateStore(tmp_path / "s.db")
    store.upsert_customers([_row("C0000001", status="SUSPENDED", balance=5.0)])
    events = make_lifecycle_hook(cfg)(_ctx(cfg, store, _evening(20)))
    topics = [t for t, _ in events]
    assert sorted(topics) == ["lifecycle_events", "recharge_events"]
    life = [x for t, x in events if t == "lifecycle_events"][0]
    rech = [x for t, x in events if t == "recharge_events"][0]
    assert (life["from_status"], life["to_status"]) == ("SUSPENDED", "REACTIVATED")
    assert rech["amount_pkr"] > 0
    assert rech["balance_after"] == pytest.approx(rech["balance_before"] + rech["amount_pkr"])
    c = store.get_customer("C0000001")
    assert c["status"] == "ACTIVE" and c["last_active"] == _evening(20)
    assert c["at_risk"] == 0 and c["balance"] == pytest.approx(rech["balance_after"])


def test_last_active_from_usage(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(m, "BASE_DAILY_CHURN", 0.0)
    store = StateStore(tmp_path / "s.db")
    store.upsert_customers([_row("C0000001", last_active=0)])
    events = make_lifecycle_hook(cfg)(_ctx(cfg, store, 3, [_usage("C0000001")]))
    assert events == []
    assert store.get_customer("C0000001")["last_active"] == 3


def test_zero_balance_since(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(m, "BASE_DAILY_CHURN", 0.0)
    store = StateStore(tmp_path / "s.db")
    store.upsert_customers([_row("C0000001", balance=0.0, last_active=_evening(3))])
    hook = make_lifecycle_hook(cfg)
    hook(_ctx(cfg, store, _evening(3)))
    assert store.get_customer("C0000001")["zero_balance_since"] == 3

    store.conn.execute("UPDATE customer_state SET balance=50.0 WHERE customer_id='C0000001'")
    hook(_ctx(cfg, store, _evening(4)))
    assert store.get_customer("C0000001")["zero_balance_since"] is None