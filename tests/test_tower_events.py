from datetime import timedelta

import pytest

from simulator.common import load_config
from simulator.core.clock import SimClock
from simulator.towers import events

CFG = load_config("config_test.yaml")

METRICS_KEYS = {
    "event_id", "event_time", "schema_version", "source", "tower_id",
    "event_date", "health", "signal_dbm", "load", "active_users",
    "total_minutes", "total_data_mb", "dropped_calls",
}
NETWORK_KEYS = {
    "event_id", "event_time", "schema_version", "source", "outage_id",
    "region", "tower_id", "event_date", "status", "severity",
    "affected_pct", "cause",
}
TOWER = {"tower_id": "T01001", "region": "Karachi"}


def metrics(band=5, hour=2, tower="T01001", **over):
    args = dict(
        health="DEGRADED", signal_dbm=-97.123, load=0.91234,
        active_users=273, total_minutes=4100.4, total_data_mb=150000.456,
        dropped_calls=38,
    )
    args.update(over)
    return events.build_metrics_event(CFG, tower, band, hour, **args)


def network(band=5, hour=3, status="START", outage_id="OUT-T01001-33"):
    return events.build_network_event(
        CFG, TOWER, band, hour, status, outage_id, 2, 3.456, "hardware"
    )


def test_metrics_event_fields_and_hidden_state():
    ev = metrics()
    assert set(ev) == METRICS_KEYS
    assert "precursor_active" not in ev and "failure_at" not in ev


def test_metrics_event_time_and_date():
    clock = SimClock.from_config(CFG, index=5)
    ev = metrics(band=5, hour=2)
    assert ev["event_time"] == (clock.band_start + timedelta(hours=2)).isoformat()
    assert ev["event_time"].endswith("+05:00")
    assert ev["event_date"] == clock.event_date
    assert ev["schema_version"] == "1.0"
    assert ev["source"] == "simulator"


def test_metrics_event_rounding_and_types():
    ev = metrics()
    assert ev["signal_dbm"] == -97.1
    assert ev["load"] == 0.912
    assert ev["total_data_mb"] == 150000.46
    assert ev["active_users"] == 273 and isinstance(ev["active_users"], int)
    assert ev["total_minutes"] == 4100 and isinstance(ev["total_minutes"], int)
    assert ev["dropped_calls"] == 38 and isinstance(ev["dropped_calls"], int)


def test_metrics_event_deterministic_and_unique_ids():
    a = metrics()
    assert a == metrics()
    ids = {
        a["event_id"],
        metrics(hour=3)["event_id"],
        metrics(tower="T01002")["event_id"],
        metrics(band=6)["event_id"],
    }
    assert len(ids) == 4


def test_metrics_event_rejects_down_and_bad_hour():
    with pytest.raises(ValueError):
        metrics(health="DOWN")
    with pytest.raises(ValueError):
        metrics(hour=6)
    with pytest.raises(ValueError):
        metrics(hour=-1)


def test_network_start_and_end():
    start = network(band=5, hour=3, status="START")
    end = network(band=6, hour=1, status="END")
    assert set(start) == NETWORK_KEYS and set(end) == NETWORK_KEYS
    assert "precursor_active" not in start and "failure_at" not in start
    assert start["outage_id"] == end["outage_id"] == "OUT-T01001-33"
    assert start["event_id"] != end["event_id"]
    assert start["region"] == "Karachi" and start["tower_id"] == "T01001"
    assert start["status"] == "START" and end["status"] == "END"
    assert start["affected_pct"] == 3.46
    assert start["severity"] == 2 and start["cause"] == "hardware"
    clock = SimClock.from_config(CFG, index=6)
    assert end["event_time"] == (clock.band_start + timedelta(hours=1)).isoformat()


def test_network_event_bad_status():
    with pytest.raises(ValueError):
        network(status="STOP")