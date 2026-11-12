import pytest

from simulator.towers import model

CFG = {
    "seed": 42,
    "towers": {
        "degraded_signal_dbm": -95,
        "critical_signal_dbm": -105,
        "critical_load": 1.0,
        "failure_precursor_share": 0.7,
    },
}


def fresh(baseline=-75.0):
    return model.initial_state("T00001", baseline)


def test_baseline_range_and_deterministic():
    tower = {"tower_id": "T00001", "tower_type": "4G"}
    a = model.baseline_signal(CFG, tower)
    assert -80.0 <= a <= -70.0
    assert a == model.baseline_signal(CFG, tower)
    t3 = {"tower_id": "T00002", "tower_type": "3G"}
    assert -83.0 <= model.baseline_signal(CFG, t3) <= -73.0


def test_baseline_unknown_type():
    with pytest.raises(ValueError):
        model.baseline_signal(CFG, {"tower_id": "T1", "tower_type": "6G"})


def test_health_boundaries():
    f = model.health_from_signal
    assert f(CFG, -80) == "HEALTHY"
    assert f(CFG, -95) == "HEALTHY"
    assert f(CFG, -95.1) == "DEGRADED"
    assert f(CFG, -105) == "DEGRADED"
    assert f(CFG, -105.1) == "CRITICAL"


def test_initial_state():
    s = fresh(-76.5)
    assert s["health"] == "HEALTHY"
    assert s["precursor_active"] == 0
    assert s["signal_dbm"] == -76.5
    assert s["down_until_hour"] is None


def test_next_hour_deterministic():
    a = model.next_hour(CFG, "T00001", -75.0, fresh(), 10, 0.5)
    b = model.next_hour(CFG, "T00001", -75.0, fresh(), 10, 0.5)
    assert a == b


def test_down_stays_then_recovers():
    s = fresh()
    s.update(health="DOWN", down_until_hour=100, outage_id="OUT-X",
             outage_cause="hardware", outage_severity=2,
             outage_affected_pct=4.0)
    new, ev = model.next_hour(CFG, "T00001", -75.0, s, 99, 0.5)
    assert new["health"] == "DOWN"
    assert not ev["recovered"]
    new, ev = model.next_hour(CFG, "T00001", -75.0, s, 100, 0.5)
    assert ev["recovered"]
    assert new["health"] == "HEALTHY"
    assert new["down_until_hour"] is None
    assert new["outage_id"] is None
    assert new["outage_cause"] is None


def test_precursor_signal_falls_then_down():
    s = fresh(-75.0)
    s.update(precursor_active=1, precursor_start_hour=0, failure_at=100)
    new, ev = model.next_hour(CFG, "T00001", -75.0, s, 50, 0.5)
    assert -100.0 < new["signal_dbm"] < -85.0
    assert not ev["went_down"]
    new, ev = model.next_hour(CFG, "T00001", -75.0, s, 100, 0.5)
    assert ev["went_down"] and ev["kind"] == "precursor"
    assert new["health"] == "DOWN"
    assert new["precursor_active"] == 0
    assert 103 <= new["down_until_hour"] <= 112


def test_dip_signal_in_range():
    s = fresh()
    s["dip_until_hour"] = 60
    new, ev = model.next_hour(CFG, "T00001", -75.0, s, 50, 0.5)
    assert -103.0 <= new["signal_dbm"] <= -96.0
    assert new["health"] == "DEGRADED"
    assert not ev["went_down"]


def test_sudden_failure(monkeypatch):
    monkeypatch.setattr(model, "SUDDEN_RATE", 1.0)
    new, ev = model.next_hour(CFG, "T00001", -75.0, fresh(), 200, 0.5)
    assert ev["went_down"] and ev["kind"] == "sudden"
    assert new["health"] == "DOWN"
    assert 203 <= new["down_until_hour"] <= 212


def test_precursor_start(monkeypatch):
    monkeypatch.setattr(model, "SUDDEN_RATE", 0.0)
    monkeypatch.setattr(model, "precursor_rate", lambda cfg: 1.0)
    new, ev = model.next_hour(CFG, "T00001", -75.0, fresh(), 300, 0.5)
    assert new["precursor_active"] == 1
    assert new["precursor_start_hour"] == 300
    assert 324 <= new["failure_at"] <= 468
    assert new["health"] == "HEALTHY"


def test_dip_load_multiplier(monkeypatch):
    monkeypatch.setattr(model, "SUDDEN_RATE", 0.0)
    monkeypatch.setattr(model, "precursor_rate", lambda cfg: 0.0)
    monkeypatch.setattr(model, "DIP_RATE", 0.1)

    def count(load):
        n = 0
        for hour in range(300):
            new, _ = model.next_hour(CFG, "T00001", -75.0, fresh(), hour, load)
            if new["dip_until_hour"] is not None:
                n += 1
        return n

    assert count(2.0) > 2 * count(0.5)


def test_outage_cause():
    c = model.outage_cause
    assert c(CFG, "T1", 5, "sudden", [2.0]) in ("power_cut", "fibre_cut")
    assert c(CFG, "T1", 5, "precursor", [0.5, 1.2]) == "congestion"
    assert c(CFG, "T1", 5, "precursor", [0.5] * 6) == "hardware"
    assert c(CFG, "T1", 5, "precursor", [1.5] + [0.5] * 6) == "hardware"


def test_severity_boundaries():
    assert model.severity_from_pct(2.9) == 1
    assert model.severity_from_pct(3.0) == 2
    assert model.severity_from_pct(6.0) == 2
    assert model.severity_from_pct(6.1) == 3


def test_outage_id():
    assert model.outage_id("T02001", 497) == "OUT-T02001-497"