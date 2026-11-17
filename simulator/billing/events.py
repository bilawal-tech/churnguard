"""Event builders for recharge_events and package_events."""
from simulator.customers.events import SCHEMA_VERSION, SOURCE, _event_id


def subscription_id(customer_id, band_index, package_id):
    return f"SUB-{customer_id}-{band_index}-{package_id}"


def build_recharge_event(
    cfg, customer_id, clock, amount_pkr, channel, balance_before, balance_after,
):
    return {
        "event_id": _event_id(
            cfg["seed"], "recharge_events", customer_id, clock.index
        ),
        "event_time": clock.band_start.isoformat(),
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE,
        "customer_id": customer_id,
        "event_date": clock.event_date,
        "amount_pkr": int(amount_pkr),
        "channel": channel,
        "balance_before": round(float(balance_before), 2),
        "balance_after": round(float(balance_after), 2),
    }


def build_package_event(
    cfg, customer_id, clock, sub_id, action, pkg, balance_after, seq=0,
):
    return {
        "event_id": _event_id(
            cfg["seed"], "package_events", customer_id, clock.index, action, pkg["package_id"], seq
        ),
        "event_time": clock.band_start.isoformat(),
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE,
        "customer_id": customer_id,
        "event_date": clock.event_date,
        "subscription_id": sub_id,
        "action": action,
        "package_id": pkg["package_id"],
        "price_pkr": int(pkg["price_pkr"]),
        "validity_days": int(pkg["validity_days"]),
        "balance_after": round(float(balance_after), 2),
    }