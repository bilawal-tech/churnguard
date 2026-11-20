"""Dirty data constants aur har topic ke nullable fields."""

DEFAULT_DIRTY_CONFIG = {
    "enabled": True,
    "null_rate": 0.015,
    "duplicate_rate": 0.005,
    "late_rate": 0.015,
    "late_max_hours": 48,
}

# Common envelope (event_id, event_time, schema_version, source) aur primary keys
# kabhi null nahi hote taake Kafka keys aur deduplication na tootein.
NULLABLE_FIELDS_BY_TOPIC = {
    "customer_events": ("home_tower_id", "city", "acquisition_channel"),
    "profile_events": ("age_band", "gender", "language_pref", "arpu_band", "device_type"),
    "usage_events": ("tower_id", "data_mb_whatsapp", "data_mb_video", "calls_onnet_min", "dropped_calls"),
    "tower_metrics_events": ("signal_dbm", "load", "active_users", "dropped_calls"),
    "network_events": ("cause", "affected_pct"),
    "recharge_events": ("channel",),
    "package_events": ("channel", "validity_days"),
    "lifecycle_events": ("trigger_metric",),
    "offer_events": ("discount_pct", "trigger_rule"),
}