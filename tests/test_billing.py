"""Unit tests for billing events and core billing engine (Step 7.2)."""
from simulator.billing.engine import (
    RATE_DATA_MB,
    RATE_OFFNET_MIN,
    RATE_ONNET_MIN,
    RATE_SMS,
    apply_usage_billing,
    choose_package,
    choose_recharge,
    eligible_packages,
    has_no_package_habit,
    init_active_package_row,
    is_quota_exhausted,
    package_for_city,
)
from simulator.billing.events import (
    build_package_event,
    build_recharge_event,
    subscription_id,
)
from simulator.common import load_config
from simulator.core.clock import SimClock
from simulator.masters.packages import build_packages


def _cfg():
    return load_config("config_test.yaml")


def _sample_usage(
    onnet=10, offnet=4, intl=0, sms=6,
    wa=20.0, soc=10.0, vid=50.0, brw=15.0, oth=5.0,
):
    return {
        "customer_id": "C0000001",
        "event_date": "2026-01-01",
        "time_band": "Morning",
        "tower_id": "T_KHI_001",
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


def test_recharge_and_package_event_builders():
    cfg = _cfg()
    clock = SimClock.from_config(cfg, index=5)
    pkgs = build_packages()
    pkg = pkgs[0]

    r_ev = build_recharge_event(cfg, "C0000001", clock, 200, "easypaisa", 30.0, 230.0)
    assert r_ev["customer_id"] == "C0000001"
    assert r_ev["amount_pkr"] == 200
    assert r_ev["channel"] == "easypaisa"
    assert r_ev["balance_before"] == 30.0
    assert r_ev["balance_after"] == 230.0
    assert len(r_ev["event_id"]) == 20

    sub = subscription_id("C0000001", clock.index, pkg["package_id"])
    assert sub == f"SUB-C0000001-5-{pkg['package_id']}"

    p_ev = build_package_event(cfg, "C0000001", clock, sub, "PURCHASE", pkg, 120.5)
    assert p_ev["subscription_id"] == sub
    assert p_ev["action"] == "PURCHASE"
    assert p_ev["package_id"] == pkg["package_id"]
    assert p_ev["price_pkr"] == pkg["price_pkr"]
    assert p_ev["validity_days"] == pkg["validity_days"]
    assert p_ev["balance_after"] == 120.5


def test_region_mapping_and_feature_phone_filter():
    pkgs = build_packages()
    # Feature phone should never get data or social packages
    assert eligible_packages(pkgs, "Karachi", "feature_phone", "data") == []
    assert eligible_packages(pkgs, "Karachi", "feature_phone", "social") == []
    assert len(eligible_packages(pkgs, "Karachi", "feature_phone", "voice")) > 0

    # Regional package check: Sindh/Karachi package matches Karachi, not Quetta
    sindh_pkg = {"region": ["Sindh"]}
    assert package_for_city(sindh_pkg, "Karachi") is True
    assert package_for_city(sindh_pkg, "Quetta") is False


def test_choose_package_and_recharge_deterministic():
    cfg = _cfg()
    pkgs = build_packages()
    p1 = choose_package(cfg, 1, "prepaid", "Lahore", pkgs)
    p2 = choose_package(cfg, 1, "prepaid", "Lahore", pkgs)
    assert p1 is not None
    assert p1["package_id"] == p2["package_id"]

    amt1, ch1 = choose_recharge(cfg, 1, "prepaid", 3)
    amt2, ch2 = choose_recharge(cfg, 1, "prepaid", 3)
    assert (amt1, ch1) == (amt2, ch2)
    assert amt1 in (100, 200, 300, 500, 1000)
    assert ch1 in ("retailer", "easypaisa", "jazzcash", "app", "card")

    # ~15% no-package habit across 1000 customers
    no_pkg_rate = sum(has_no_package_habit(cfg, i) for i in range(1, 1001)) / 1000
    assert 0.10 <= no_pkg_rate <= 0.22


def test_quota_deduction_and_option_a_spend():
    cfg = _cfg()
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
    # Everything covered by package -> balance unchanged, spend_from_balance == 0
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


def test_night_only_package_timing():
    cfg = _cfg()
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
    # Afternoon (band 2): night_only gives 0% quota -> paid from balance
    prow = init_active_package_row("C0000001", "SUB-N", night_pkg, band_index=0, auto_renew=False)
    cust = {"customer_id": "C0000001", "plan_type": "prepaid", "balance": 100.0}
    usage = _sample_usage(onnet=0, offnet=0, sms=0, wa=0.0, soc=0.0, vid=50.0, brw=0.0, oth=0.0)
    new_bal, _, _, _ = apply_usage_billing(
        cfg, cust, [prow], {"P_NIGHT": night_pkg}, usage, band_idx_in_day=2, clock_index=2,
    )
    assert usage["spend_from_package"] == 0.0
    assert usage["spend_from_balance"] == 5.0
    assert new_bal == 95.0

    # Morning (band 1): 50% of 100 MB = 50 MB usable -> covers 50 MB video
    usage2 = _sample_usage(onnet=0, offnet=0, sms=0, wa=0.0, soc=0.0, vid=50.0, brw=0.0, oth=0.0)
    new_bal2, rem2, _, _ = apply_usage_billing(
        cfg, cust, [prow], {"P_NIGHT": night_pkg}, usage2, band_idx_in_day=1, clock_index=1,
    )
    assert usage2["spend_from_package"] == 5.0
    assert usage2["spend_from_balance"] == 0.0
    assert rem2[0]["rem_data_mb"] == 50.0
    assert new_bal2 == 100.0


def test_prepaid_balance_floor_and_postpaid_bill():
    cfg = _cfg()
    # Prepaid with only 5 PKR balance facing 25 PKR usage -> balance stops at 0.0
    cust_pre = {"customer_id": "C0000001", "plan_type": "prepaid", "balance": 5.0}
    usage_pre = _sample_usage(onnet=10, offnet=4, sms=0, wa=0.0, soc=0.0, vid=0.0, brw=0.0, oth=0.0)
    bal_pre, _, _, _ = apply_usage_billing(
        cfg, cust_pre, [], {}, usage_pre, band_idx_in_day=2, clock_index=2,
    )
    assert bal_pre == 0.0
    assert usage_pre["spend_from_balance"] == 5.0
    assert usage_pre["calls_onnet_min"] < 10

    # Postpaid stays at 0.0 balance and logs full bill in spend_from_balance
    cust_post = {"customer_id": "C0000002", "plan_type": "postpaid", "balance": 0.0}
    usage_post = _sample_usage(onnet=10, offnet=4, sms=0, wa=0.0, soc=0.0, vid=0.0, brw=0.0, oth=0.0)
    bal_post, _, _, _ = apply_usage_billing(
        cfg, cust_post, [], {}, usage_post, band_idx_in_day=2, clock_index=2,
    )
    assert bal_post == 0.0
    assert usage_post["spend_from_balance"] == 25.0


def test_quota_exhausted_detection():
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
    cfg = _cfg()
    cust = {"customer_id": "C0000001", "plan_type": "prepaid", "balance": 0.0}
    usage = _sample_usage(onnet=5, offnet=0, sms=0, wa=0.0, soc=0.0, vid=0.0, brw=0.0, oth=0.0)
    _, rem_pkgs, exhausted, _ = apply_usage_billing(
        cfg, cust, [prow], {"P_SMALL": pkg}, usage, band_idx_in_day=0, clock_index=0,
    )
    assert len(exhausted) == 1
    assert exhausted[0][0]["subscription_id"] == "SUB-S"
    assert rem_pkgs == []