"""Tests for the usage generator (one customer, one band)."""
import pytest

from simulator.common import customer_id, load_config
from simulator.core.clock import SimClock
from simulator.customers.events import device_type_for
from simulator.masters.towers import add_neighbors, build_towers
from simulator.usage import generator as g

USAGE_KEYS = {
    "event_id", "event_time", "schema_version", "source",
    "customer_id", "event_date", "time_band", "tower_id",
    "calls_onnet_min", "calls_offnet_min", "calls_intl_min", "sms_count",
    "data_mb_whatsapp", "data_mb_social", "data_mb_video",
    "data_mb_browsing", "data_mb_other",
    "dropped_calls", "active_package_ids",
    "spend_from_package", "spend_from_balance",
}
DATA_KEYS = [k for k in USAGE_KEYS if k.startswith("data_mb_")]


@pytest.fixture(scope="module")
def cfg():
    return load_config("config_test.yaml")


@pytest.fixture(scope="module")
def towers(cfg):
    return add_neighbors(build_towers(cfg))


@pytest.fixture(scope="module")
def neighbors(towers):
    return g.neighbor_map(towers)


def home_of(towers, n):
    return towers[n % len(towers)]["tower_id"]


def make_event(cfg, towers, neighbors, n, index, home=None):
    clock = SimClock.from_config(cfg, index=index)
    home = home or home_of(towers, n)
    return g.build_usage_event(cfg, customer_id(cfg, n), home, neighbors, clock)


def total_data(event):
    return sum(event[k] for k in DATA_KEYS)


def test_same_inputs_give_same_event(cfg, towers, neighbors):
    a = make_event(cfg, towers, neighbors, 7, 3)
    b = make_event(cfg, towers, neighbors, 7, 3)
    assert a == b


def test_fields_and_envelope(cfg, towers, neighbors):
    e = make_event(cfg, towers, neighbors, 1, 0)
    assert set(e) == USAGE_KEYS
    assert e["schema_version"] == "1.0"
    assert e["source"] == "simulator"
    assert e["event_time"].endswith("+05:00")
    assert e["customer_id"] == "C0000001"


def test_time_fields_follow_clock(cfg, towers, neighbors):
    for index in range(8):
        clock = SimClock.from_config(cfg, index=index)
        e = make_event(cfg, towers, neighbors, 1, index)
        assert e["event_date"] == clock.event_date
        assert e["time_band"] == clock.band_name
        assert e["event_time"] == clock.band_start.isoformat()


def test_event_ids_differ(cfg, towers, neighbors):
    ids = {
        make_event(cfg, towers, neighbors, 1, 0)["event_id"],
        make_event(cfg, towers, neighbors, 1, 1)["event_id"],
        make_event(cfg, towers, neighbors, 2, 0)["event_id"],
    }
    assert len(ids) == 3


def test_spend_and_packages_are_empty(cfg, towers, neighbors):
    e = make_event(cfg, towers, neighbors, 1, 0)
    assert e["active_package_ids"] == []
    assert e["spend_from_package"] is None
    assert e["spend_from_balance"] is None


def test_values_are_valid(cfg, towers, neighbors):
    for n in range(1, 101):
        for index in range(4):
            e = make_event(cfg, towers, neighbors, n, index)
            for key in ("calls_onnet_min", "calls_offnet_min", "calls_intl_min",
                        "sms_count", "dropped_calls"):
                assert isinstance(e[key], int) and e[key] >= 0
            assert all(e[k] >= 0 for k in DATA_KEYS)


def test_feature_phone_has_almost_no_data(cfg, towers, neighbors):
    feature = [n for n in range(1, 400) if device_type_for(cfg, n) == "feature_phone"]
    assert len(feature) > 20
    for n in feature[:30]:
        assert g.persona_for(cfg, n) in ("call_heavy", "sms_heavy")
        for index in range(4):
            e = make_event(cfg, towers, neighbors, n, index)
            assert e["data_mb_whatsapp"] == e["data_mb_social"] == 0.0
            assert e["data_mb_video"] == e["data_mb_browsing"] == 0.0
            assert e["data_mb_other"] <= 20 * max(g.BAND_SHARE) + 0.01


def test_persona_follows_device(cfg):
    for n in range(1, 301):
        persona = g.persona_for(cfg, n)
        if device_type_for(cfg, n) == "feature_phone":
            assert persona in ("call_heavy", "sms_heavy")
        else:
            assert persona != "sms_heavy"


def test_customer_factor_in_range_and_stable(cfg):
    for n in range(1, 501):
        f = g.customer_factor(cfg, n)
        assert g.FACTOR_MIN <= f <= g.FACTOR_MAX
        assert f == g.customer_factor(cfg, n)


def test_tower_is_home_or_neighbor(cfg, towers, neighbors):
    for n in range(1, 201):
        home = home_of(towers, n)
        allowed = {home} | set(neighbors[home])
        for index in range(4):
            assert make_event(cfg, towers, neighbors, n, index)["tower_id"] in allowed


def test_no_neighbors_means_home_tower(cfg, towers):
    for n in range(1, 50):
        e = make_event(cfg, towers, {}, n, 2, home="T01001")
        assert e["tower_id"] == "T01001"


def test_roaming_share(cfg, towers, neighbors):
    homes = [t["tower_id"] for t in towers if t["neighbor_tower_ids"]]
    assert homes
    moved = total = 0
    for n in range(1, 751):
        home = homes[n % len(homes)]
        for index in range(4):
            e = make_event(cfg, towers, neighbors, n, index, home=home)
            moved += e["tower_id"] != home
            total += 1
    assert 0.10 < moved / total < 0.20


def test_drop_rate(cfg, towers, neighbors):
    calls = drops = 0
    for n in range(1, 1001):
        for index in range(4):
            e = make_event(cfg, towers, neighbors, n, index)
            minutes = e["calls_onnet_min"] + e["calls_offnet_min"] + e["calls_intl_min"]
            calls += int(round(minutes / g.MINUTES_PER_CALL))
            drops += e["dropped_calls"]
    assert calls > 0
    assert 0.010 < drops / calls < 0.021


def test_evening_busier_than_night(cfg, towers, neighbors):
    night = sum(total_data(make_event(cfg, towers, neighbors, n, 0)) for n in range(1, 301))
    evening = sum(total_data(make_event(cfg, towers, neighbors, n, 3)) for n in range(1, 301))
    assert evening > night


def test_customer_no_and_neighbor_map(cfg, towers, neighbors):
    assert g.customer_no(cfg, "C0000012") == 12
    for t in towers:
        assert neighbors[t["tower_id"]] == t["neighbor_tower_ids"]