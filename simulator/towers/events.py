"""Tower ke events: tower_metrics_events (har ghante) aur network_events (outage).

precursor_active aur failure_at kisi event mein nahi jate (simulator ki chhupi
state, sirf SQLite mein). DOWN ke ghanton mein tower_metrics_events nahi banta.
"""
from datetime import timedelta

from simulator.core.clock import SimClock
from simulator.customers.events import SCHEMA_VERSION, SOURCE, _event_id

METRICS_HEALTH = ("HEALTHY", "DEGRADED", "CRITICAL")
NETWORK_STATUS = ("START", "END")


def _envelope(cfg, topic, band_index, hour_in_band, *id_parts):
    """Common fields; event_time = band ka aaghaz plus ghante ka farq."""
    if not 0 <= hour_in_band <= 5:
        raise ValueError(f"hour_in_band must be 0..5, got {hour_in_band}")
    clock = SimClock.from_config(cfg, index=band_index)
    event_time = clock.band_start + timedelta(hours=hour_in_band)
    envelope = {
        "event_id": _event_id(cfg["seed"], topic, *id_parts),
        "event_time": event_time.isoformat(),
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE,
    }
    return envelope, clock.event_date


def build_metrics_event(cfg, tower_id, band_index, hour_in_band, *, health,
                        signal_dbm, load, active_users, total_minutes,
                        total_data_mb, dropped_calls):
    """tower_metrics_events record: ek tower, ek ghanta (DOWN na ho)."""
    if health not in METRICS_HEALTH:
        raise ValueError(f"health must be one of {METRICS_HEALTH}, got {health!r}")
    hour_index = band_index * 6 + hour_in_band
    event, event_date = _envelope(
        cfg, "tower_metrics_events", band_index, hour_in_band,
        tower_id, hour_index,
    )
    event.update({
        "tower_id": tower_id,
        "event_date": event_date,
        "health": health,
        "signal_dbm": round(float(signal_dbm), 1),
        "load": round(float(load), 3),
        "active_users": int(active_users),
        "total_minutes": int(round(total_minutes)),
        "total_data_mb": round(float(total_data_mb), 2),
        "dropped_calls": int(round(dropped_calls)),
    })
    return event


def build_network_event(cfg, tower, band_index, hour_in_band, status,
                        outage_id, severity, affected_pct, cause):
    """network_events record: outage START ya END (tower-level)."""
    if status not in NETWORK_STATUS:
        raise ValueError(f"status must be one of {NETWORK_STATUS}, got {status!r}")
    event, event_date = _envelope(
        cfg, "network_events", band_index, hour_in_band, outage_id, status,
    )
    event.update({
        "outage_id": outage_id,
        "region": tower["region"],
        "tower_id": tower["tower_id"],
        "event_date": event_date,
        "status": status,
        "severity": int(severity),
        "affected_pct": round(float(affected_pct), 2),
        "cause": cause,
    })
    return event