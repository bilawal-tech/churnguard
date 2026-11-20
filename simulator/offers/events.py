"""Event builder for offer_events."""
from simulator.customers.events import SCHEMA_VERSION, SOURCE, _event_id


def make_offer_id(customer_id, band_index, offer_type):
    return f"OFR-{customer_id}-{band_index}-{offer_type}"


def build_offer_event(
    cfg,
    customer_id,
    clock,
    offer_id,
    offer_type,
    action,
    group,
    trigger_rule,
    campaign_name=None,
    package_id=None,
    discount_pct=None,
):
    return {
        "event_id": _event_id(
            cfg["seed"], "offer_events", offer_id, clock.index, action
        ),
        "event_time": clock.band_start.isoformat(),
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE,
        "customer_id": customer_id,
        "event_date": clock.event_date,
        "offer_id": offer_id,
        "offer_type": offer_type,
        "action": action,
        "group": group,
        "trigger_rule": trigger_rule,
        "campaign_name": campaign_name,
        "package_id": package_id,
        "discount_pct": round(float(discount_pct), 4) if discount_pct is not None else None,
    }
