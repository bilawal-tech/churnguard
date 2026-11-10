"""Tests for the usage hook (active customers only, counts, signup band, resume)."""
import json
from types import SimpleNamespace

import pytest

from simulator.common import load_config
from simulator.core.clock import BANDS_PER_DAY, SimClock
from simulator.core.engine import Simulator
from simulator.core.state_store import StateStore
from simulator.customers.hook import make_customer_hook, new_customers_in_band
from simulator.masters.towers import add_neighbors, build_towers
from simulator.usage.hook import make_usage_hook

USAGE_KEYS = {
    "event_id", "event_time", "schema_version", "source",
    "customer_id", "event_date", "time_band", "tower_id",
    "calls_onnet_min", "calls_offnet_min", "calls_intl_min", "sms_count",
    "data_mb_whatsapp", "data_mb_social", "data_mb_video",
    "data_mb_browsing", "data_mb_other",
    "dropped_calls", "active_package_ids",
    "spend_from_package", "spend_from_balance",
}


@pytest.fixture(scope="module")
def cfg():
    return load_config("config_test.yaml")


@pytest.fixture(scope="module")
def towers(cfg):
    return add_neighbors(build_towers(cfg))


def run_sim(cfg, towers, folder, stop_after=None):
    """Customer hook first, then usage hook; state and events go to folder."""
    store = StateStore(folder / "s.db")
    hooks = [make_customer_hook(cfg, towers), make_usage_hook(cfg, towers)]
    Simulator(cfg, store, folder / "out", hooks=hooks).run(stop_after=stop_after)
    store.close()


def read_events(folder, topic):
    text = (folder / "out" / f"{topic}.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def expected_usage_total(cfg):
    """Active customers per band, added up over the whole history."""
    signed = 0
    total = 0
    for index in range(cfg["history_days"] * BANDS_PER_DAY):
        signed += new_customers_in_band(cfg, index)
        total += signed
    return total


def test_usage_hook_needs_neighbors(cfg):
    bare = [{"tower_id": "T00001", "city": "Lahore"}]
    with pytest.raises(ValueError):
        make_usage_hook(cfg, bare)


def test_only_active_customers_get_usage(cfg, towers, tmp_path):
    store = StateStore(tmp_path / "s.db")
    home = towers[0]["tower_id"]

    def row(n, status):
        return {
            "customer_id": f"C{n:07d}", "plan_type": "prepaid", "status": status,
            "status_since": 0, "balance": 100.0, "home_tower_id": home,
            "last_active": 0, "at_risk": 0,
        }

    store.upsert_customers([row(3, "ACTIVE"), row(1, "SUSPENDED"), row(2, "ACTIVE")])
    ctx = SimpleNamespace(clock=SimClock.from_config(cfg, index=0), store=store)
    events = make_usage_hook(cfg, towers)(ctx)
    assert [topic for topic, _ in events] == ["usage_events", "usage_events"]
    assert [e["customer_id"] for _, e in events] == ["C0000002", "C0000003"]
    store.close()


def test_usage_count_matches_active_customers(cfg, towers, tmp_path):
    run_sim(cfg, towers, tmp_path)
    assert len(read_events(tmp_path, "usage_events")) == expected_usage_total(cfg)


def test_one_event_per_customer_per_band(cfg, towers, tmp_path):
    run_sim(cfg, towers, tmp_path)
    events = read_events(tmp_path, "usage_events")
    keys = {(e["customer_id"], e["event_time"]) for e in events}
    assert len(keys) == len(events)
    assert len({e["event_id"] for e in events}) == len(events)


def test_usage_starts_in_signup_band(cfg, towers, tmp_path):
    run_sim(cfg, towers, tmp_path)
    signup = {
        e["customer_id"]: e["event_time"]
        for e in read_events(tmp_path, "customer_events")
    }
    first = {}
    for e in read_events(tmp_path, "usage_events"):
        first.setdefault(e["customer_id"], e["event_time"])
    assert set(first) == set(signup)
    assert first == signup


def test_towers_are_known_and_fields_complete(cfg, towers, tmp_path):
    run_sim(cfg, towers, tmp_path)
    known = {t["tower_id"] for t in towers}
    for e in read_events(tmp_path, "usage_events"):
        assert set(e) == USAGE_KEYS
        assert e["tower_id"] in known


def test_same_run_twice_gives_same_usage(cfg, towers, tmp_path):
    run_sim(cfg, towers, tmp_path / "a")
    run_sim(cfg, towers, tmp_path / "b")
    a = (tmp_path / "a" / "out" / "usage_events.jsonl").read_text(encoding="utf-8")
    b = (tmp_path / "b" / "out" / "usage_events.jsonl").read_text(encoding="utf-8")
    assert a == b


def test_resume_matches_full_run(cfg, towers, tmp_path):
    run_sim(cfg, towers, tmp_path / "full")
    run_sim(cfg, towers, tmp_path / "part", stop_after=7)
    run_sim(cfg, towers, tmp_path / "part")
    for topic in ("usage_events", "customer_events"):
        full = (tmp_path / "full" / "out" / f"{topic}.jsonl").read_text(encoding="utf-8")
        part = (tmp_path / "part" / "out" / f"{topic}.jsonl").read_text(encoding="utf-8")
        assert full == part