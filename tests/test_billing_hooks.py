"""Tests for billing hooks (package lifecycle and prepaid recharges)."""
import json
from types import SimpleNamespace

import pytest

from simulator.billing.engine import init_active_package_row
from simulator.billing.hooks import make_package_hook, make_recharge_hook
from simulator.common import load_config
from simulator.core.clock import BANDS_PER_DAY, SimClock
from simulator.core.engine import Simulator
from simulator.core.state_store import StateStore
from simulator.customers.hook import make_customer_hook
from simulator.masters.packages import build_packages
from simulator.masters.towers import add_neighbors, build_towers
from simulator.usage.hook import make_usage_hook

RECHARGE_KEYS = {
    "event_id", "event_time", "schema_version", "source",
    "customer_id", "event_date", "amount_pkr", "channel",
    "balance_before", "balance_after",
}

PACKAGE_KEYS = {
    "event_id", "event_time", "schema_version", "source",
    "customer_id", "event_date", "subscription_id", "action",
    "package_id", "price_pkr", "validity_days", "balance_after",
}


@pytest.fixture(scope="module")
def cfg():
    return load_config("config_test.yaml")


@pytest.fixture(scope="module")
def towers(cfg):
    return add_neighbors(build_towers(cfg))


@pytest.fixture(scope="module")
def packages():
    return build_packages()


def run_billing_sim(cfg, towers, packages, folder, stop_after=None):
    store = StateStore(folder / "s.db")
    hooks = [
        make_customer_hook(cfg, towers),
        make_package_hook(cfg, towers, packages),
        make_recharge_hook(cfg),
        make_usage_hook(cfg, towers, packages=packages),
    ]
    Simulator(cfg, store, folder / "out", hooks=hooks).run(stop_after=stop_after)
    store.close()


def read_events(folder, topic):
    path = folder / "out" / f"{topic}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _cust_row(cid, plan_type="prepaid", status="ACTIVE", balance=100.0, home="T01001"):
    return {
        "customer_id": cid,
        "plan_type": plan_type,
        "status": status,
        "status_since": 0,
        "balance": balance,
        "home_tower_id": home,
        "last_active": 0,
        "at_risk": 0,
    }


def test_recharge_hook_only_tops_up_low_prepaid_active(cfg, tmp_path):
    store = StateStore(tmp_path / "s.db")
    store.upsert_customers([
        _cust_row("C0000001", plan_type="prepaid", status="ACTIVE", balance=20.0),
        _cust_row("C0000002", plan_type="prepaid", status="ACTIVE", balance=150.0),
        _cust_row("C0000003", plan_type="postpaid", status="ACTIVE", balance=0.0),
        _cust_row("C0000004", plan_type="prepaid", status="SUSPENDED", balance=10.0),
    ])
    ctx = SimpleNamespace(clock=SimClock.from_config(cfg, index=0), store=store)
    with store.transaction():
        events = make_recharge_hook(cfg)(ctx)

    assert len(events) == 1
    topic, ev = events[0]
    assert topic == "recharge_events"
    assert set(ev) == RECHARGE_KEYS
    assert ev["customer_id"] == "C0000001"
    assert store.get_customer("C0000001")["balance"] >= 120.0
    store.close()


def test_package_hook_expiry_and_auto_renew(cfg, towers, packages, tmp_path):
    store = StateStore(tmp_path / "s.db")
    home = towers[0]["tower_id"]
    pkg = packages[0]
    expired_band = -(int(pkg["validity_days"]) * BANDS_PER_DAY)

    store.upsert_customers([
        _cust_row("C0000001", balance=float(pkg["price_pkr"]) + 500.0, home=home),
        _cust_row("C0000002", balance=5.0, home=home),
    ])
    store.upsert_active_package(
        init_active_package_row("C0000001", "SUB-RENEW", pkg, band_index=expired_band, auto_renew=True)
    )
    store.upsert_active_package(
        init_active_package_row("C0000002", "SUB-FAIL", pkg, band_index=expired_band, auto_renew=True)
    )

    ctx = SimpleNamespace(clock=SimClock.from_config(cfg, index=0), store=store)
    with store.transaction():
        events = make_package_hook(cfg, towers, packages)(ctx)

    for topic, ev in events:
        if topic == "package_events":
            assert set(ev) == PACKAGE_KEYS

    actions = [(e["customer_id"], e["action"]) for _, e in events]
    assert ("C0000001", "AUTO_RENEW") in actions
    assert ("C0000002", "AUTO_RENEW_OFF") in actions
    assert ("C0000002", "EXPIRE") in actions
    assert store.get_active_packages("C0000002") == []
    store.close()


def test_same_billing_run_twice_gives_same_events(cfg, towers, packages, tmp_path):
    run_billing_sim(cfg, towers, packages, tmp_path / "a", stop_after=8)
    run_billing_sim(cfg, towers, packages, tmp_path / "b", stop_after=8)
    for topic in ("recharge_events", "package_events", "usage_events"):
        assert read_events(tmp_path / "a", topic) == read_events(tmp_path / "b", topic)