from datetime import timedelta

import pytest

from simulator.common import load_config
from simulator.core.clock import SimClock
from simulator.core.engine import BandContext
from simulator.core.state_store import StateStore
from simulator.towers import hook as hook_mod
from simulator.towers import model
from simulator.towers.hook import make_tower_hook

CFG = load_config("config_test.yaml")
TOWERS = [
    {"tower_id": "T00001", "region": "A", "city": "A",
     "tower_type": "4G", "capacity_users": 400},
    {"tower_id": "T00002", "region": "A", "city": "A",
     "tower_type": "4G", "capacity_users": 400},
    {"tower_id": "T00003", "region": "B", "city": "B",
     "tower_type": "3G", "capacity_users": 200},
]
COUNTS = {"T00001": 300, "T00002": 100, "T00003": 50}


def quiet(monkeypatch):
    monkeypatch.setattr(model, "SUDDEN_RATE", 0.0)
    monkeypatch.setattr(model, "DIP_RATE", 0.0)
    monkeypatch.setattr(model, "precursor_rate", lambda cfg: 0.0)


def make_usage(counts, drops=None):
    drops = drops or {}
    events = []
    for tid, n in counts.items():
        for i in range(n):
            events.append({
                "tower_id": tid, "calls_onnet_min": 10, "calls_offnet_min": 5,
                "calls_intl_min": 1, "data_mb_whatsapp": 0, "data_mb_social": 0,
                "data_mb_video": 0, "data_mb_browsing": 0, "data_mb_other": 100,
                "dropped_calls": drops.get(tid, 0) if i == 0 else 0,
            })
    return events


def run_band(store, counts=COUNTS, drops=None, index=0, towers=TOWERS):
    ctx = BandContext(SimClock.from_config(CFG, index=index), store, 1)
    ctx.band_events = [("usage_events", e) for e in make_usage(counts, drops)]
    return make_tower_hook(CFG, towers)(ctx)


def of(out, topic, tid=None):
    return [e for t, e in out if t == topic and (tid is None or e["tower_id"] == tid)]


def preset(store, tid, **fields):
    tower = next(t for t in TOWERS if t["tower_id"] == tid)
    state = model.initial_state(tid, model.baseline_signal(CFG, tower))
    state.update(fields)
    store.upsert_towers([state])


def test_weights_sum_to_one():
    assert len(hook_mod.BAND_WEIGHTS) == 4
    for w in hook_mod.BAND_WEIGHTS:
        assert len(w) == 6 and abs(sum(w) - 1.0) < 1e-9


def test_first_band_creates_states_and_metrics(tmp_path, monkeypatch):
    quiet(monkeypatch)
    store = StateStore(tmp_path / "s.db")
    out = run_band(store)
    assert {t for t, _ in out} == {"tower_metrics_events"}
    assert len(out) == 18
    assert all(e["health"] == "HEALTHY" for _, e in out)
    assert all("precursor_active" not in e and "failure_at" not in e for _, e in out)
    assert len(store.all_towers()) == 3


def test_band_totals_are_split_over_hours(tmp_path, monkeypatch):
    quiet(monkeypatch)
    store = StateStore(tmp_path / "s.db")
    out = run_band(store, drops={"T00001": 10})
    ev = of(out, "tower_metrics_events", "T00001")
    assert len(ev) == 6
    assert sum(e["dropped_calls"] for e in ev) == 10
    assert abs(sum(e["total_minutes"] for e in ev) - 4800) <= 3
    assert abs(sum(e["total_data_mb"] for e in ev) - 30000) < 1.0
    assert abs(sum(e["active_users"] for e in ev) / 6 - 300) <= 30


def test_deterministic(tmp_path):
    a = StateStore(tmp_path / "a.db")
    b = StateStore(tmp_path / "b.db")
    assert run_band(a) == run_band(b)
    assert a.all_towers() == b.all_towers()


def test_sudden_failure_start_events(tmp_path, monkeypatch):
    monkeypatch.setattr(model, "SUDDEN_RATE", 1.0)
    store = StateStore(tmp_path / "s.db")
    out = run_band(store)
    band_start = SimClock.from_config(CFG, index=0).band_start.isoformat()
    for tid in COUNTS:
        first = of(out, "network_events", tid)[0]
        assert first["status"] == "START"
        assert first["outage_id"] == f"OUT-{tid}-0"
        assert first["event_time"] == band_start
        assert first["cause"] in ("power_cut", "fibre_cut")
        hour0 = [e for e in of(out, "tower_metrics_events", tid)
                 if e["event_time"] == band_start]
        assert hour0 == []
    b = of(out, "network_events", "T00003")[0]
    assert b["affected_pct"] == 100.0 and b["severity"] == 3
    a = of(out, "network_events", "T00001")[0]
    assert 60 < a["affected_pct"] < 90 and a["severity"] == 3
    assert a["region"] == "A"


def test_down_tower_recovers_with_end_event(tmp_path, monkeypatch):
    quiet(monkeypatch)
    store = StateStore(tmp_path / "s.db")
    preset(store, "T00001", health="DOWN", down_until_hour=2,
           outage_id="OUT-T00001-X", outage_cause="hardware",
           outage_severity=2, outage_affected_pct=4.0)
    out = run_band(store)
    net = of(out, "network_events", "T00001")
    assert len(net) == 1
    assert net[0]["status"] == "END"
    assert net[0]["outage_id"] == "OUT-T00001-X"
    assert net[0]["severity"] == 2 and net[0]["cause"] == "hardware"
    met = of(out, "tower_metrics_events", "T00001")
    assert len(met) == 4
    start = SimClock.from_config(CFG, index=0).band_start
    assert met[0]["event_time"] == (start + timedelta(hours=2)).isoformat()
    assert len(of(out, "tower_metrics_events", "T00002")) == 6
    t = store.get_tower("T00001")
    assert t["health"] != "DOWN" and t["outage_id"] is None


def test_over_load_hour_saved(tmp_path, monkeypatch):
    quiet(monkeypatch)
    store = StateStore(tmp_path / "s.db")
    run_band(store, counts={"T00001": 900, "T00002": 10, "T00003": 10})
    assert store.get_tower("T00001")["last_over_load_hour"] == 5
    assert store.get_tower("T00003")["last_over_load_hour"] is None


def test_precursor_failure_congestion_cause(tmp_path, monkeypatch):
    quiet(monkeypatch)
    store = StateStore(tmp_path / "s.db")
    preset(store, "T00001", precursor_active=1, precursor_start_hour=0,
           failure_at=3)
    out = run_band(store, counts={"T00001": 900, "T00002": 10, "T00003": 10})
    start = of(out, "network_events", "T00001")[0]
    assert start["status"] == "START" and start["cause"] == "congestion"
    assert start["outage_id"] == "OUT-T00001-3"


def test_precursor_failure_hardware_cause(tmp_path, monkeypatch):
    quiet(monkeypatch)
    store = StateStore(tmp_path / "s.db")
    preset(store, "T00001", precursor_active=1, precursor_start_hour=0,
           failure_at=3)
    out = run_band(store, counts={"T00001": 10, "T00002": 10, "T00003": 10})
    start = of(out, "network_events", "T00001")[0]
    assert start["cause"] == "hardware"


def test_unknown_tower_raises(tmp_path, monkeypatch):
    quiet(monkeypatch)
    store = StateStore(tmp_path / "s.db")
    with pytest.raises(ValueError):
        run_band(store, counts={"T99999": 1})