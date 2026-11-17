"""Tests for billing event builders (recharge_events and package_events)."""
import pytest

from simulator.billing.events import (
    build_package_event,
    build_recharge_event,
    subscription_id,
)
from simulator.common import load_config
from simulator.core.clock import SimClock
from simulator.masters.packages import build_packages

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
def packages():
    return build_packages()


def test_subscription_id_format():
    assert subscription_id("C0000001", 5, "PKG_01") == "SUB-C0000001-5-PKG_01"


def test_build_recharge_event_schema_and_determinism(cfg):
    clock = SimClock.from_config(cfg, index=5)
    ev1 = build_recharge_event(cfg, "C0000001", clock, 200, "easypaisa", 30.0, 230.0)
    ev2 = build_recharge_event(cfg, "C0000001", clock, 200, "easypaisa", 30.0, 230.0)

    assert set(ev1) == RECHARGE_KEYS
    assert ev1 == ev2
    assert ev1["customer_id"] == "C0000001"
    assert ev1["amount_pkr"] == 200
    assert ev1["channel"] == "easypaisa"
    assert ev1["balance_before"] == 30.0
    assert ev1["balance_after"] == 230.0


def test_build_package_event_schema_and_seq_uniqueness(cfg, packages):
    clock = SimClock.from_config(cfg, index=5)
    pkg = packages[0]
    sub = subscription_id("C0000001", clock.index, pkg["package_id"])

    ev_off = build_package_event(cfg, "C0000001", clock, sub, "AUTO_RENEW_OFF", pkg, 5.0, seq=1)
    ev_exp = build_package_event(cfg, "C0000001", clock, sub, "EXPIRE", pkg, 5.0, seq=2)

    assert set(ev_off) == PACKAGE_KEYS
    assert set(ev_exp) == PACKAGE_KEYS
    assert ev_off["subscription_id"] == sub
    assert ev_off["price_pkr"] == int(pkg["price_pkr"])
    assert ev_off["validity_days"] == int(pkg["validity_days"])
    assert ev_off["event_id"] != ev_exp["event_id"]