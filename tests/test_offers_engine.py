from datetime import date

import pytest

from simulator.offers import engine as e


def pk(pid, price, data=0, onnet=0, offnet=0, anynet=0, ptype="combo",
       region=("all",), night=False):
    return {
        "package_id": pid, "price_pkr": price, "quota_data_mb": data,
        "quota_onnet_min": onnet, "quota_offnet_min": offnet,
        "quota_anynet_min": anynet, "package_type": ptype,
        "region": list(region), "night_only": night,
    }


PKGS = [
    pk("A", 209, data=2048, onnet=2000, offnet=30),
    pk("B", 521, data=10240, onnet=1000, offnet=120),
    pk("C", 217, ptype="voice", onnet=120, offnet=50),
    pk("D", 304, data=5120, anynet=1000, region=("Karachi",)),
    pk("E", 30, data=5000, night=True, region=("Sindh",)),
    pk("F", 695, data=102400, onnet=2000, offnet=600),
    pk("G", 103, data=1024, onnet=1000, offnet=10),
    pk("S", 104, ptype="social"),
]
SEED = 42
CID = "C0000001"


def test_unit_random_deterministic_and_in_range():
    a = e.unit_random(SEED, "x", CID)
    assert a == e.unit_random(SEED, "x", CID)
    assert 0.0 <= a < 1.0
    assert a != e.unit_random(SEED, "y", CID)


def test_is_control_about_10_percent():
    ids = [f"C{i:07d}" for i in range(1, 5001)]
    frac = sum(e.is_control(SEED, c) for c in ids) / len(ids)
    assert 0.08 < frac < 0.12


def test_weekly_rise_value():
    vals = {d: 10.0 for d in range(21)}
    vals.update({d: 20.0 for d in range(21, 28)})
    assert e.weekly_rise(vals, 27) == pytest.approx(1.6)


def test_weekly_rise_short_history_is_none():
    assert e.weekly_rise({d: 5.0 for d in range(5)}, 4) is None


def test_weekly_rise_zero_average_is_none():
    assert e.weekly_rise({d: 0.0 for d in range(28)}, 27) is None


def test_weekend_and_events_due():
    assert e.weekend_due(date(2026, 8, 14))
    assert not e.weekend_due(date(2026, 8, 13))
    assert e.events_due(date(2026, 5, 24)) == [("EVENT_OFFER", "Eid_ul_Adha", date(2026, 5, 27))]
    assert e.events_due(date(2026, 5, 2)) == [("CRICKET_PACK", "PSL11_Final", date(2026, 5, 3))]
    assert e.events_due(date(2026, 8, 11))[0][1] == "Independence_Day"
    assert e.events_due(date(2026, 8, 18))[0][1] == "England_Test1"
    assert e.events_due(date(2026, 6, 1)) == []


def test_window_end():
    assert e.window_end("WEEKEND_SPECIAL", date(2026, 4, 3)) == date(2026, 4, 5)
    assert e.window_end("DATA_BOOST", date(2026, 4, 10)) == date(2026, 4, 13)
    assert e.window_end("RECHARGE_BONUS", date(2026, 4, 10)) == date(2026, 4, 17)
    assert e.window_end("EVENT_OFFER", date(2026, 5, 24), date(2026, 5, 27)) == date(2026, 5, 28)


def test_planned_accept_rate_and_window():
    sent, end = date(2026, 4, 10), date(2026, 4, 13)
    plans = [e.planned_accept_date(SEED, f"O{i}", "DATA_BOOST", sent, end) for i in range(2000)]
    got = [p for p in plans if p is not None]
    assert 0.09 < len(got) / 2000 < 0.15
    assert all(date(2026, 4, 11) <= p <= end for p in got)
    assert e.planned_accept_date(SEED, "O1", "RECHARGE_BONUS", sent, end) is None


def test_choose_offer_package():
    ch = lambda t, band, active=frozenset(): e.choose_offer_package(SEED, CID, t, PKGS, band, active)
    assert ch("DATA_BOOST", "low")["package_id"] == "A"
    assert ch("DATA_BOOST", "mid")["package_id"] == "B"
    assert ch("DATA_BOOST", "high")["package_id"] == "F"
    assert ch("CALL_BUNDLE", "low")["package_id"] == "C"
    assert ch("WEEKEND_SPECIAL", "low")["package_id"] in {"A", "G"}
    assert ch("DATA_BOOST", "mid", {"B"}) is None
    assert ch("CALL_BUNDLE", "low", {"C"}) is None


def test_discounted_package_is_a_copy():
    base = PKGS[0]
    d = e.discounted_package(base, 0.30)
    assert d["price_pkr"] == pytest.approx(146.3)
    assert base["price_pkr"] == 209


def test_reward_package():
    assert e.reward_package(PKGS, "low", "android", set())["package_id"] == "G"
    assert e.reward_package(PKGS, "low", "feature_phone", set())["package_id"] == "G"
    assert e.reward_package(PKGS, "mid", "android", set())["package_id"] == "A"
    assert e.reward_package(PKGS, "mid", "feature_phone", set())["package_id"] == "A"
    assert e.reward_package(PKGS, "mid", "android", {"A"})["package_id"] == "G"
    assert e.reward_package(PKGS, "mid", "android", set())["price_pkr"] == 0.0


def test_recharge_helpers():
    assert e.recharge_offer_due("prepaid", 80)
    assert not e.recharge_offer_due("prepaid", 100)
    assert not e.recharge_offer_due("postpaid", 0)
    assert e.recharge_target_reached(600, "mid")
    assert not e.recharge_target_reached(599, "mid")


def test_can_send_gap_and_cap():
    today = date(2026, 4, 20)
    assert e.can_send([], today)
    assert not e.can_send([date(2026, 4, 15)], today)
    assert e.can_send([date(2026, 4, 13)], today)
    three = [date(2026, 4, 1), date(2026, 4, 8), date(2026, 4, 14)]
    assert not e.can_send(three, date(2026, 4, 21))


def test_pick_offer_priority():
    assert e.pick_offer({"DATA_BOOST", "WEEKEND_SPECIAL"}) == "DATA_BOOST"
    assert e.pick_offer({"WEEKEND_SPECIAL", "EVENT_OFFER"}) == "EVENT_OFFER"
    assert e.pick_offer(set()) is None