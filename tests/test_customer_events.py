"""Tests for customer_events and profile_events builders."""
import re

import pytest

from simulator.common import load_config
from simulator.core.clock import SimClock
from simulator.customers import events as ev

ENVELOPE_KEYS = {"event_id", "event_time", "schema_version", "source"}
CUSTOMER_KEYS = ENVELOPE_KEYS | {
    "customer_id", "signup_date", "region", "city", "segment",
    "acquisition_channel", "device_type", "initial_balance", "home_tower_id",
}
PROFILE_KEYS = ENVELOPE_KEYS | {
    "customer_id", "profile_version", "age_band", "gender",
    "phone_masked", "cnic_masked", "language_pref", "arpu_band",
}


@pytest.fixture(scope="module")
def cfg():
    return load_config("config_test.yaml")


def make_customer(n, plan_type="prepaid"):
    return {
        "customer_id": f"C{n:07d}",
        "city": "Lahore",
        "plan_type": plan_type,
        "balance": 120.5 if plan_type == "prepaid" else 0.0,
        "home_tower_id": "T02005",
    }


def test_same_inputs_give_same_events(cfg):
    c = make_customer(1)
    assert ev.build_customer_event(cfg, c, 1, 0) == ev.build_customer_event(cfg, c, 1, 0)
    assert ev.build_profile_event(cfg, c, 1, 0) == ev.build_profile_event(cfg, c, 1, 0)


def test_envelope_fields(cfg):
    c = make_customer(1)
    for e in (ev.build_customer_event(cfg, c, 1, 0), ev.build_profile_event(cfg, c, 1, 0)):
        assert ENVELOPE_KEYS <= set(e)
        assert e["schema_version"] == "1.0"
        assert e["source"] == "simulator"
        assert e["event_time"].endswith("+05:00")


def test_event_ids_differ(cfg):
    a1 = ev.build_customer_event(cfg, make_customer(1), 1, 0)
    a2 = ev.build_customer_event(cfg, make_customer(2), 2, 0)
    p1 = ev.build_profile_event(cfg, make_customer(1), 1, 0)
    assert a1["event_id"] != a2["event_id"]
    assert a1["event_id"] != p1["event_id"]


def test_customer_event_fields(cfg):
    c = make_customer(7)
    e = ev.build_customer_event(cfg, c, 7, 0)
    assert set(e) == CUSTOMER_KEYS
    assert "zone" not in e
    assert e["customer_id"] == "C0000007"
    assert e["region"] == e["city"] == "Lahore"
    assert e["segment"] == "prepaid"
    assert e["initial_balance"] == 120.5
    assert e["home_tower_id"] == "T02005"


def test_profile_event_fields(cfg):
    e = ev.build_profile_event(cfg, make_customer(7), 7, 0)
    assert set(e) == PROFILE_KEYS
    assert e["profile_version"] == 1


def test_masking_formats(cfg):
    for n in range(1, 201):
        e = ev.build_profile_event(cfg, make_customer(n), n, 0)
        assert re.fullmatch(r"03\d{2}-xxxx\d{2}", e["phone_masked"])
        assert re.fullmatch(r"xxxxx-xxxxx\d{2}-\d", e["cnic_masked"])
        last = int(e["cnic_masked"][-1])
        assert (last % 2 == 1) == (e["gender"] == "male")


def test_signup_index_sets_time_and_date(cfg):
    for index in (0, 5):
        clock = SimClock.from_config(cfg, index=index)
        e = ev.build_customer_event(cfg, make_customer(1), 1, index)
        assert e["signup_date"] == clock.event_date
        assert e["event_time"] == clock.band_start.isoformat()


def test_gender_and_device_shares(cfg):
    total = 4000
    males = feature = 0
    for n in range(1, total + 1):
        c = make_customer(n)
        males += ev.build_profile_event(cfg, c, n, 0)["gender"] == "male"
        feature += ev.build_customer_event(cfg, c, n, 0)["device_type"] == "feature_phone"
    assert 0.55 < males / total < 0.65
    assert 0.26 < feature / total < 0.34


def test_arpu_prepaid_leans_lower_than_postpaid(cfg):
    total = 2000
    high = {"prepaid": 0, "postpaid": 0}
    for plan in high:
        for n in range(1, total + 1):
            e = ev.build_profile_event(cfg, make_customer(n, plan), n, 0)
            high[plan] += e["arpu_band"] == "high"
    assert high["prepaid"] < high["postpaid"]


def test_device_type_for_is_stable_and_used_in_event(cfg):
    for n in (1, 2, 3, 50):
        device = ev.device_type_for(cfg, n)
        assert device == ev.device_type_for(cfg, n)
        e = ev.build_customer_event(cfg, make_customer(n), n, 0)
        assert e["device_type"] == device


def test_device_type_for_share(cfg):
    total = 4000
    feature = sum(
        ev.device_type_for(cfg, n) == "feature_phone" for n in range(1, total + 1)
    )
    assert 0.26 < feature / total < 0.34