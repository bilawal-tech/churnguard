"""lifecycle_events ka record banana (pure function)."""
from simulator.customers.events import SCHEMA_VERSION, SOURCE, _event_id


def build_lifecycle_event(cfg, customer_id, clock, from_status, to_status,
                          churn_reason=None, inactivity_days=None):
    return {
        "event_id": _event_id(
            cfg["seed"], "lifecycle_events", customer_id, clock.index, to_status
        ),
        "event_time": clock.band_start.isoformat(),
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE,
        "customer_id": customer_id,
        "event_date": clock.event_date,
        "from_status": from_status,
        "to_status": to_status,
        "churn_reason": churn_reason,
        "inactivity_days": inactivity_days,
    }