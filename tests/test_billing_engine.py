"""Tests for core billing engine logic (selection, quota deduction, balance caps)."""
import pytest

from simulator.billing.engine import (
    RATE_DATA_MB,
    RATE_INTL_MIN,
    RATE_OFFNET_MIN,
    RATE_ONNET_MIN,
    RATE_SMS,
    apply_usage_billing,
    arpu_band_for,
    choose_package,
    choose_recharge,
    eligible_packages,
    has_no_package_habit,
    init_active_package_row,
    is_quota_exhausted,
    package_for_city,
)
from simulator.common import load_config
from simulator.masters.packages import build_packages


@pytest.fixture(scope="module")
def cfg():
    return load_config("config_test.yaml")


@pytest.fixture(scope="module")
def packages():
    return build_packages()


def _sample_usage(
    onnet=10, offnet=4, intl=0, sms=6,
    wa=20.0, soc=10.0, vid=50.0, brw=15.0, oth=5.0,
):
    return {
        "customer_id": "C0000001",
        "event_date": "2026-04-01",
        "time_band": "Morning",
        "tower_id": "T01001",
        "calls_onnet_min": onnet,
        "calls_offnet_min": offnet,
        "calls_intl_min": intl,
        "sms_count": sms,
        "data_mb_whatsapp": wa,
        "data_mb_social": soc,
        "data_mb_video": vid,
        "data_mb_browsing": brw,
        "data_mb_other": oth,
        "dropped_calls": 0,
        "active_package_ids": [],
        "spend_from_package": None,
        "spend_from_balance": None,
    }


def test_region_mapping_and_feature_phone_filter(packages):
    assert eligible_packages(packages, "Karachi", "feature_phone", "data") == []
    assert eligible_packages(packages, "Karachi", "feature_phone", "social") == []
    assert len(eligible_packages(packages, "Karachi", "feature_phone", "voice")) > 0

    sindh_pkg = {"region": ["Sindh"]}
    assert package_for_city(sindh_pkg, "Karachi") is True
    assert package_for_city(sindh_pkg, "Quetta") is False


def test_choose_package_and_recharge_deterministic(cfg, packages):
    assert arpu_band_for(cfg, 1, "prepaid") in ("low", "mid", "high")

    p1 = choose_package(cfg, 1, "prepaid", "Lahore", packages)
    p2 = choose_package(cfg, 1, "prepaid", "Lahore", packages)
    assert p1 is not None
    assert p1["package_id"] == p2["package_id"]

    amt1, ch1 = choose_recharge(cfg, 1, "prepaid", 3)
    amt2, ch2 = choose_recharge(cfg, 1, "prepaid", 3)
    assert (amt1, ch1) == (amt2, ch2)
    assert amt1 in (100, 200, 300, 500, 1000)
    assert ch1 in ("retailer", "easypaisa", "jazzcash", "app", "card")

    no_pkg_rate = sum(has_no_package_habit(cfg, i) for i in range(1, 1001)) / 1000
    assert 0.10 <= no_pkg_rate <= 0.22


def test_choose_package_respects_max_price_fallback_order(cfg, monkeypatch):
    import simulator.billing.engine as billing_engine

    monkeypatch.setattr(billing_engine, "device_type_for", lambda cfg, n: "smartphone")
    monkeypatch.setattr(billing_engine, "persona_for", lambda cfg, n: "call_heavy")
    monkeypatch.setattr(billing_engine, "arpu_band_for", lambda cfg, n, plan: "mid")
    monkeypatch.setattr(billing_engine, "_pick", lambda rng, choices: "voice")
    packages = [
        {"package_id": "VOICE", "package_type": "voice", "price_pkr": 20, "region": ["all"]},
        {"package_id": "COMBO", "package_type": "combo", "price_pkr": 15, "region": ["all"]},
        {"package_id": "SOCIAL", "package_type": "social", "price_pkr": 10, "region": ["all"]},
    ]

    assert choose_package(cfg, 1, "prepaid", "Lahore", packages, max_price=20)["package_id"] == "VOICE"
    assert choose_package(cfg, 1, "prepaid", "Lahore", packages, max_price=15)["package_id"] == "COMBO"
    assert choose_package(cfg, 1, "prepaid", "Lahore", packages, max_price=10)["package_id"] == "SOCIAL"


def test_quota_deduction_and_option_a_spend(cfg):
    pkg = {
        "package_id": "P_TEST_1",
        "price_pkr": 100,
        "validity_days": 7,
        "quota_onnet_min": 20,
        "quota_offnet_min": 10,
        "quota_anynet_min": 0,
        "quota_intl_min": 0,
        "quota_sms": 10,
        "quota_data_mb": 200,
        "quota_social_mb": 50,
        "night_only": False,
    }
    prow = init_active_package_row("C0000001", "SUB-1", pkg, band_index=0, auto_renew=True)
    cust = {"customer_id": "C0000001", "plan_type": "prepaid", "balance": 150.0}
    usage = _sample_usage(onnet=10, offnet=4, sms=6, wa=20.0, soc=10.0, vid=50.0, brw=15.0, oth=5.0)

    new_bal, rem_pkgs, exhausted, addons = apply_usage_billing(
        cfg, cust, [prow], {"P_TEST_1": pkg}, usage, band_idx_in_day=1, clock_index=1,
    )
    assert new_bal == 150.0
    assert usage["spend_from_balance"] == 0.0
    assert usage["active_package_ids"] == ["P_TEST_1"]
    expected_pkg_val = round(
        10 * RATE_ONNET_MIN + 4 * RATE_OFFNET_MIN + 6 * RATE_SMS + 100.0 * RATE_DATA_MB, 2
    )
    assert usage["spend_from_package"] == expected_pkg_val
    assert rem_pkgs[0]["rem_onnet_min"] == 10.0
    assert rem_pkgs[0]["rem_social_mb"] == 20.0
    assert rem_pkgs[0]["rem_data_mb"] == 130.0
    assert exhausted == []
    assert addons == []


def test_anynet_and_intl_quota_fallback(cfg):
    pkg = {
        "package_id": "P_ANYNET",
        "price_pkr": 150,
        "validity_days": 7,
        "quota_onnet_min": 2,
        "quota_offnet_min": 1,
        "quota_anynet_min": 10,
        "quota_intl_min": 5,
        "quota_sms": 0,
        "quota_data_mb": 0,
        "quota_social_mb": 0,
        "night_only": False,
    }
    prow = init_active_package_row("C0000001", "SUB-ANY", pkg, band_index=0, auto_renew=False)
    cust = {"customer_id": "C0000001", "plan_type": "prepaid", "balance": 100.0}
    usage = _sample_usage(onnet=5, offnet=4, intl=3, sms=0, wa=0.0, soc=0.0, vid=0.0, brw=0.0, oth=0.0)

    new_bal, rem_pkgs, _, _ = apply_usage_billing(
        cfg, cust, [prow], {"P_ANYNET": pkg}, usage, band_idx_in_day=2, clock_index=2,
    )
    assert new_bal == 100.0
    assert usage["spend_from_balance"] == 0.0
    expected_pkg_val = round(
        5 * RATE_ONNET_MIN + 4 * RATE_OFFNET_MIN + 3 * RATE_INTL_MIN, 2
    )
    assert usage["spend_from_package"] == expected_pkg_val
    assert rem_pkgs[0]["rem_onnet_min"] == 0.0
    assert rem_pkgs[0]["rem_offnet_min"] == 0.0
    assert rem_pkgs[0]["rem_anynet_min"] == 4.0
    assert rem_pkgs[0]["rem_intl_min"] == 2.0


def test_night_only_package_timing(cfg):
    night_pkg = {
        "package_id": "P_NIGHT",
        "price_pkr": 50,
        "validity_days": 1,
        "quota_onnet_min": 0,
        "quota_offnet_min": 0,
        "quota_anynet_min": 0,
        "quota_intl_min": 0,
        "quota_sms": 0,
        "quota_data_mb": 100,
        "quota_social_mb": 0,
        "night_only": True,
    }
    prow = init_active_package_row("C0000001", "SUB-N", night_pkg, band_index=0, auto_renew=False)
    cust = {"customer_id": "C0000001", "plan_type": "prepaid", "balance": 100.0}
    usage = _sample_usage(onnet=0, offnet=0, sms=0, wa=0.0, soc=0.0, vid=50.0, brw=0.0, oth=0.0)
    new_bal, _, _, _ = apply_usage_billing(
        cfg, cust, [prow], {"P_NIGHT": night_pkg}, usage, band_idx_in_day=2, clock_index=2,
    )
    assert usage["spend_from_package"] == 0.0
    assert usage["spend_from_balance"] == 5.0
    assert new_bal == 95.0

    usage2 = _sample_usage(onnet=0, offnet=0, sms=0, wa=0.0, soc=0.0, vid=50.0, brw=0.0, oth=0.0)
    new_bal2, rem2, _, _ = apply_usage_billing(
        cfg, cust, [prow], {"P_NIGHT": night_pkg}, usage2, band_idx_in_day=1, clock_index=1,
    )
    assert usage2["spend_from_package"] == 5.0
    assert usage2["spend_from_balance"] == 0.0
    assert rem2[0]["rem_data_mb"] == 50.0
    assert new_bal2 == 100.0


def test_prepaid_balance_floor_and_postpaid_bill(cfg):
    cust_pre = {"customer_id": "C0000001", "plan_type": "prepaid", "balance": 5.0}
    usage_pre = _sample_usage(onnet=10, offnet=4, sms=0, wa=0.0, soc=0.0, vid=0.0, brw=0.0, oth=0.0)
    bal_pre, _, _, _ = apply_usage_billing(
        cfg, cust_pre, [], {}, usage_pre, band_idx_in_day=2, clock_index=2,
    )
    assert bal_pre == 0.0
    assert usage_pre["spend_from_balance"] == 5.0
    assert usage_pre["calls_onnet_min"] < 10

    cust_post = {"customer_id": "C0000002", "plan_type": "postpaid", "balance": 0.0}
    usage_post = _sample_usage(onnet=10, offnet=4, sms=0, wa=0.0, soc=0.0, vid=0.0, brw=0.0, oth=0.0)
    bal_post, _, _, _ = apply_usage_billing(
        cfg, cust_post, [], {}, usage_post, band_idx_in_day=2, clock_index=2,
    )
    assert bal_post == 0.0
    assert usage_post["spend_from_balance"] == 25.0


def test_quota_exhausted_detection(cfg):
    pkg = {
        "package_id": "P_SMALL",
        "price_pkr": 50,
        "validity_days": 1,
        "quota_onnet_min": 5,
        "quota_offnet_min": 0,
        "quota_anynet_min": 0,
        "quota_intl_min": 0,
        "quota_sms": 0,
        "quota_data_mb": 0,
        "quota_social_mb": 0,
        "night_only": False,
    }
    prow = init_active_package_row("C0000001", "SUB-S", pkg, band_index=0, auto_renew=False)
    assert is_quota_exhausted(prow) is False
    cust = {"customer_id": "C0000001", "plan_type": "prepaid", "balance": 0.0}
    usage = _sample_usage(onnet=5, offnet=0, sms=0, wa=0.0, soc=0.0, vid=0.0, brw=0.0, oth=0.0)
    _, rem_pkgs, exhausted, _ = apply_usage_billing(
        cfg, cust, [prow], {"P_SMALL": pkg}, usage, band_idx_in_day=0, clock_index=0,
    )
    assert len(exhausted) == 1
    assert exhausted[0][0]["subscription_id"] == "SUB-S"
    assert rem_pkgs == []

def test_dropped_calls_scale_with_minutes(cfg):
     def run(balance):
        cust = {"customer_id": "C0000001", "plan_type": "prepaid", "balance": balance}
        usage = _sample_usage(onnet=10, offnet=4, sms=0, wa=0.0, soc=0.0,
                              vid=0.0, brw=0.0, oth=0.0)
        usage["dropped_calls"] = 4
        apply_usage_billing(cfg, cust, [], {}, usage, band_idx_in_day=2, clock_index=2)
        return usage

     assert run(1000.0)["dropped_calls"] == 4   # balance kaafi, koi scale nahi
     u = run(5.0)                               # 25 PKR kharcha, balance 5
     assert u["calls_onnet_min"] + u["calls_offnet_min"] == 3
     assert u["dropped_calls"] == 1             # 4 x 3/14 = 0.86, round 1
     assert run(0.0)["dropped_calls"] == 0      # balance 0, minutes 0

def _pkg(pid, **quota):
    base = {
        "package_id": pid, "price_pkr": 100, "validity_days": 7,
        "quota_onnet_min": 0, "quota_offnet_min": 0, "quota_anynet_min": 0,
        "quota_intl_min": 0, "quota_sms": 0, "quota_data_mb": 0,
        "quota_social_mb": 0, "night_only": False,
    }
    base.update(quota)
    return base


def _zero_usage(**kw):
    args = dict(onnet=0, offnet=0, sms=0, wa=0.0, soc=0.0, vid=0.0, brw=0.0, oth=0.0)
    args.update(kw)
    return _sample_usage(**args)


def test_night_only_package_covers_night_band(cfg):
    pkg = _pkg("P_NIGHT", quota_data_mb=100, night_only=True)
    prow = init_active_package_row("C0000001", "SUB-N", pkg, band_index=0, auto_renew=False)
    cust = {"customer_id": "C0000001", "plan_type": "prepaid", "balance": 100.0}
    usage = _zero_usage(vid=50.0)
    new_bal, rem, _, _ = apply_usage_billing(
        cfg, cust, [prow], {"P_NIGHT": pkg}, usage, band_idx_in_day=0, clock_index=0,
    )
    assert usage["spend_from_package"] == 5.0
    assert usage["spend_from_balance"] == 0.0
    assert rem[0]["rem_data_mb"] == 50.0
    assert new_bal == 100.0


def test_exhausted_package_without_addon_leaves_rest_to_balance(monkeypatch):
    import simulator.billing.engine as be
    monkeypatch.setattr(be, "ADDON_BUY_CHANCE", 0.0)
    cfg = load_config("config_test.yaml")
    pa = _pkg("P_A", quota_onnet_min=5)
    pb = _pkg("P_B", quota_onnet_min=5)
    rows = [
        init_active_package_row("C0000001", "SUB-A", pa, band_index=0, auto_renew=False),
        init_active_package_row("C0000001", "SUB-B", pb, band_index=0, auto_renew=False),
    ]
    cust = {"customer_id": "C0000001", "plan_type": "prepaid", "balance": 100.0}
    usage = _zero_usage(onnet=8)
    new_bal, rem, exhausted, addons = apply_usage_billing(
        cfg, cust, rows, {"P_A": pa, "P_B": pb}, usage, band_idx_in_day=1, clock_index=1,
    )
    assert usage["spend_from_balance"] == 0.0
    assert usage["spend_from_package"] == 12.0
    assert sum(r["rem_onnet_min"] for r in rem) == 2.0
    assert len(exhausted) == 1 and addons == []
    assert new_bal == 100.0


def test_postpaid_uses_package_then_bills_the_rest(monkeypatch):
    import simulator.billing.engine as be
    monkeypatch.setattr(be, "ADDON_BUY_CHANCE", 0.0)
    cfg = load_config("config_test.yaml")
    pkg = _pkg("P_POST", quota_onnet_min=5)
    prow = init_active_package_row("C0000009", "SUB-P", pkg, band_index=0, auto_renew=False)
    cust = {"customer_id": "C0000009", "plan_type": "postpaid", "balance": 0.0}
    usage = _zero_usage(onnet=8)
    new_bal, rem, exhausted, addons = apply_usage_billing(
        cfg, cust, [prow], {"P_POST": pkg}, usage, band_idx_in_day=1, clock_index=1,
    )
    assert usage["spend_from_package"] == 7.5
    assert usage["spend_from_balance"] == 4.5
    assert new_bal == 0.0
    assert rem == [] and len(exhausted) == 1 and addons == []


def test_addon_rebuys_package_and_covers_rest(monkeypatch):
    import simulator.billing.engine as be
    monkeypatch.setattr(be, "ADDON_BUY_CHANCE", 1.0)
    cfg = load_config("config_test.yaml")
    pkg = _pkg("P_ADD", quota_onnet_min=5)
    prow = init_active_package_row("C0000001", "SUB-X", pkg, band_index=0, auto_renew=False)
    cust = {"customer_id": "C0000001", "plan_type": "prepaid", "balance": 150.0}
    usage = _zero_usage(onnet=8)
    new_bal, rem, exhausted, addons = apply_usage_billing(
        cfg, cust, [prow], {"P_ADD": pkg}, usage, band_idx_in_day=1, clock_index=1,
    )
    assert len(addons) == 1 and len(exhausted) == 1
    assert usage["spend_from_package"] == 12.0
    assert usage["spend_from_balance"] == 0.0
    assert new_bal == 50.0                      # 150 - package price 100
    assert rem[0]["rem_onnet_min"] == 2.0       # naye row se 3 minute kate