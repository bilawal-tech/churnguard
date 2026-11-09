"""Tests for the customer hook (counts, engine run, determinism, resume)."""
import json

import pytest

from simulator.common import load_config
from simulator.core.clock import BANDS_PER_DAY
from simulator.core.engine import Simulator
from simulator.core.state_store import StateStore
from simulator.customers.hook import (
    day_total, make_customer_hook, new_customers_in_band,
)
from simulator.masters.towers import build_towers


@pytest.fixture(scope="module")
def cfg():
    return load_config("config_test.yaml")


@pytest.fixture(scope="module")
def towers(cfg):
    return build_towers(cfg)


def run_sim(cfg, towers, folder, stop_after=None):
    """Run the customer hook through the engine; state and events go to folder."""
    store = StateStore(folder / "s.db")
    hooks = [make_customer_hook(cfg, towers)]
    Simulator(cfg, store, folder / "out", hooks=hooks).run(stop_after=stop_after)
    store.close()


def read_events(folder, topic):
    text = (folder / "out" / f"{topic}.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def expected_total(cfg):
    c = cfg["customers"]
    steady_days = cfg["history_days"] - c["initial_burst_days"]
    return c["initial"] + steady_days * c["new_per_day"]


def test_burst_days_sum_to_initial(cfg):
    c = cfg["customers"]
    burst = [day_total(cfg, d) for d in range(c["initial_burst_days"])]
    assert sum(burst) == c["initial"]


def test_burst_decays_with_real_config():
    real = load_config("config.yaml")
    burst = [day_total(real, d) for d in range(real["customers"]["initial_burst_days"])]
    assert burst == sorted(burst, reverse=True)
    assert burst[0] > burst[-1]
    assert sum(burst) == real["customers"]["initial"]


def test_steady_days_use_new_per_day(cfg):
    c = cfg["customers"]
    first = c["initial_burst_days"]
    for day in (first, first + 3):
        assert day_total(cfg, day) == c["new_per_day"]


def test_band_split_adds_up_to_day_total(cfg):
    for day in range(cfg["history_days"]):
        bands = [new_customers_in_band(cfg, day * BANDS_PER_DAY + b)
                 for b in range(BANDS_PER_DAY)]
        assert sum(bands) == day_total(cfg, day)
        assert max(bands) - min(bands) <= 1


def test_total_over_history(cfg):
    total = sum(new_customers_in_band(cfg, i)
                for i in range(cfg["history_days"] * BANDS_PER_DAY))
    assert total == expected_total(cfg)


def test_engine_run_creates_customers(cfg, towers, tmp_path):
    run_sim(cfg, towers, tmp_path)
    total = expected_total(cfg)
    store = StateStore(tmp_path / "s.db")
    assert store.count_customers() == total
    assert int(store.get_meta("next_customer_no")) == total + 1
    statuses = store.conn.execute(
        "SELECT DISTINCT status FROM customer_state"
    ).fetchall()
    assert [r["status"] for r in statuses] == ["ACTIVE"]
    store.close()
    customers = read_events(tmp_path, "customer_events")
    profiles = read_events(tmp_path, "profile_events")
    assert [e["customer_id"] for e in customers] == [f"C{n:07d}" for n in range(1, total + 1)]
    assert [e["customer_id"] for e in profiles] == [e["customer_id"] for e in customers]


def test_same_run_twice_gives_same_events(cfg, towers, tmp_path):
    run_sim(cfg, towers, tmp_path / "a")
    run_sim(cfg, towers, tmp_path / "b")
    for topic in ("customer_events", "profile_events"):
        a = (tmp_path / "a" / "out" / f"{topic}.jsonl").read_text(encoding="utf-8")
        b = (tmp_path / "b" / "out" / f"{topic}.jsonl").read_text(encoding="utf-8")
        assert a == b


def test_resume_matches_full_run(cfg, towers, tmp_path):
    run_sim(cfg, towers, tmp_path / "full")
    run_sim(cfg, towers, tmp_path / "part", stop_after=7)
    run_sim(cfg, towers, tmp_path / "part")
    for topic in ("customer_events", "profile_events"):
        full = (tmp_path / "full" / "out" / f"{topic}.jsonl").read_text(encoding="utf-8")
        part = (tmp_path / "part" / "out" / f"{topic}.jsonl").read_text(encoding="utf-8")
        assert full == part


def test_home_tower_matches_city_and_no_city_column(cfg, towers, tmp_path):
    run_sim(cfg, towers, tmp_path)
    tower_city = {t["tower_id"]: t["city"] for t in towers}
    for e in read_events(tmp_path, "customer_events"):
        assert tower_city[e["home_tower_id"]] == e["city"]
    store = StateStore(tmp_path / "s.db")
    assert "city" not in store.get_customer("C0000001")
    store.close()