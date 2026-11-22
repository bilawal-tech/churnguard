"""Kafka topic names, message keys, and raw-data partition values."""
import re

EVENT_TOPICS = (
    "customer_events",
    "profile_events",
    "usage_events",
    "recharge_events",
    "package_events",
    "offer_events",
    "lifecycle_events",
    "network_events",
    "tower_metrics_events",
)
MASTER_TABLES = ("tower_master", "packages_master", "field_teams_master")

_MONTH_PREFIX = re.compile(r"^\d{4}-\d{2}")
_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}")


def key_for(topic: str, event: dict) -> str:
    if topic not in EVENT_TOPICS:
        raise ValueError(f"Unknown event topic: {topic}")

    key_field = {
        "network_events": "region",
        "tower_metrics_events": "tower_id",
    }.get(topic, "customer_id")
    value = event.get(key_field)
    if not isinstance(value, str) or value == "":
        raise ValueError(f"Missing key {key_field} for {topic}")
    return value


def _valid_prefix(value, pattern, length):
    if isinstance(value, str) and pattern.match(value):
        return value[:length]
    return None


def _first_valid_prefix(values, pattern, length):
    for value in values:
        prefix = _valid_prefix(value, pattern, length)
        if prefix is not None:
            return prefix
    return None


def partition_for(topic: str, event: dict) -> tuple[str, str]:
    if topic not in EVENT_TOPICS:
        raise ValueError(f"Unknown event topic: {topic}")

    if topic == "customer_events":
        value = _first_valid_prefix(
            (event.get("signup_date"), event.get("event_time")),
            _MONTH_PREFIX,
            7,
        )
        if value is not None:
            return "signup_month", value
    elif topic == "profile_events":
        value = _valid_prefix(event.get("event_time"), _MONTH_PREFIX, 7)
        if value is not None:
            return "signup_month", value
    else:
        value = _first_valid_prefix(
            (event.get("event_date"), event.get("event_time")),
            _DATE_PREFIX,
            10,
        )
        if value is not None:
            return "event_date", value

    raise ValueError(f"Cannot derive partition for {topic}")
