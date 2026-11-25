from __future__ import annotations

from pyspark.sql.types import (
    ArrayType,
    BooleanType,
    DateType,
    DoubleType,
    IntegerType,
    StringType,
    StructField,
    StructType,
)

# Masters (raw/masters/<master>/snapshot_date=YYYY-MM-DD/<master>.jsonl.gz)

TOWER_MASTER_SCHEMA = StructType(
    [
        StructField("tower_id", StringType(), False),
        StructField("region", StringType(), True),
        StructField("city", StringType(), True),
        StructField("zone", StringType(), True),
        StructField("lat", DoubleType(), True),
        StructField("lon", DoubleType(), True),
        StructField("tower_type", StringType(), True),
        StructField("capacity_users", IntegerType(), True),
        StructField("neighbor_tower_ids", ArrayType(StringType()), True),
        StructField("install_date", DateType(), True),
        StructField("schema_version", StringType(), True),
        StructField("source", StringType(), True),
    ]
)

PACKAGES_MASTER_SCHEMA = StructType(
    [
        StructField("package_id", StringType(), False),
        StructField("name", StringType(), True),
        StructField("package_type", StringType(), True),
        StructField("price_pkr", IntegerType(), True),
        StructField("validity_days", IntegerType(), True),
        StructField("quota_onnet_min", IntegerType(), True),
        StructField("quota_offnet_min", IntegerType(), True),
        StructField("quota_anynet_min", IntegerType(), True),
        StructField("quota_intl_min", IntegerType(), True),
        StructField("quota_sms", IntegerType(), True),
        StructField("quota_data_mb", IntegerType(), True),
        StructField("quota_social_mb", IntegerType(), True),
        StructField("night_only", BooleanType(), True),
        StructField("region", ArrayType(StringType()), True),
        StructField("auto_renew_allowed", BooleanType(), True),
        StructField("min_balance_required", IntegerType(), True),
        StructField("schema_version", StringType(), True),
        StructField("source", StringType(), True),
    ]
)

FIELD_TEAMS_MASTER_SCHEMA = StructType(
    [
        StructField("team_id", StringType(), False),
        StructField("region", StringType(), True),
        StructField("city", StringType(), True),
        StructField("zone", StringType(), True),
        StructField("base_lat", DoubleType(), True),
        StructField("base_lon", DoubleType(), True),
        StructField("schema_version", StringType(), True),
        StructField("source", StringType(), True),
    ]
)

MASTER_SCHEMAS = {
    "tower_master": TOWER_MASTER_SCHEMA,
    "packages_master": PACKAGES_MASTER_SCHEMA,
    "field_teams_master": FIELD_TEAMS_MASTER_SCHEMA,
}
# Bronze events (event_time / ingest_time pehle string, phir common.py timestamp banata hai)
CUSTOMER_EVENTS_BRONZE = StructType(
    [
        StructField("event_id", StringType(), True),
        StructField("event_time", StringType(), True),
        StructField("schema_version", StringType(), True),
        StructField("source", StringType(), True),
        StructField("ingest_time", StringType(), True),
        StructField("customer_id", StringType(), True),
        StructField("signup_date", StringType(), True),
        StructField("region", StringType(), True),
        StructField("city", StringType(), True),
        StructField("segment", StringType(), True),
        StructField("acquisition_channel", StringType(), True),
        StructField("device_type", StringType(), True),
        StructField("initial_balance", DoubleType(), True),
        StructField("home_tower_id", StringType(), True),
    ]
)

PROFILE_EVENTS_BRONZE = StructType(
    [
        StructField("event_id", StringType(), True),
        StructField("event_time", StringType(), True),
        StructField("schema_version", StringType(), True),
        StructField("source", StringType(), True),
        StructField("ingest_time", StringType(), True),
        StructField("customer_id", StringType(), True),
        StructField("profile_version", IntegerType(), True),
        StructField("age_band", StringType(), True),
        StructField("gender", StringType(), True),
        StructField("phone_masked", StringType(), True),
        StructField("cnic_masked", StringType(), True),
        StructField("language_pref", StringType(), True),
        StructField("arpu_band", StringType(), True),
    ]
)
_ENV = [
    StructField("event_id", StringType(), True),
    StructField("event_time", StringType(), True),
    StructField("schema_version", StringType(), True),
    StructField("source", StringType(), True),
    StructField("ingest_time", StringType(), True),
]

USAGE_EVENTS_BRONZE = StructType(
    _ENV
    + [
        StructField("customer_id", StringType(), True),
        StructField("time_band", StringType(), True),
        StructField("tower_id", StringType(), True),
        StructField("calls_onnet_min", IntegerType(), True),
        StructField("calls_offnet_min", IntegerType(), True),
        StructField("calls_intl_min", IntegerType(), True),
        StructField("sms_count", IntegerType(), True),
        StructField("data_mb_whatsapp", DoubleType(), True),
        StructField("data_mb_social", DoubleType(), True),
        StructField("data_mb_video", DoubleType(), True),
        StructField("data_mb_browsing", DoubleType(), True),
        StructField("data_mb_other", DoubleType(), True),
        StructField("dropped_calls", IntegerType(), True),
        StructField("active_package_ids", ArrayType(StringType()), True),
        StructField("spend_from_package", DoubleType(), True),
        StructField("spend_from_balance", DoubleType(), True),
    ]
)

RECHARGE_EVENTS_BRONZE = StructType(
    _ENV
    + [
        StructField("customer_id", StringType(), True),
        StructField("amount_pkr", IntegerType(), True),
        StructField("channel", StringType(), True),
        StructField("balance_before", DoubleType(), True),
        StructField("balance_after", DoubleType(), True),
    ]
)

PACKAGE_EVENTS_BRONZE = StructType(
    _ENV
    + [
        StructField("customer_id", StringType(), True),
        StructField("subscription_id", StringType(), True),
        StructField("action", StringType(), True),
        StructField("package_id", StringType(), True),
        StructField("price_pkr", DoubleType(), True),
        StructField("validity_days", IntegerType(), True),
        StructField("balance_after", DoubleType(), True),
    ]
)

OFFER_EVENTS_BRONZE = StructType(
    _ENV
    + [
        StructField("customer_id", StringType(), True),
        StructField("offer_id", StringType(), True),
        StructField("offer_type", StringType(), True),
        StructField("action", StringType(), True),
        StructField("group", StringType(), True),
        StructField("trigger_rule", StringType(), True),
        StructField("campaign_name", StringType(), True),
        StructField("package_id", StringType(), True),
        StructField("discount_pct", DoubleType(), True),
    ]
)
LIFECYCLE_EVENTS_BRONZE = StructType(
    _ENV
    + [
        StructField("customer_id", StringType(), True),
        StructField("from_status", StringType(), True),
        StructField("to_status", StringType(), True),
        StructField("churn_reason", StringType(), True),
        StructField("inactivity_days", IntegerType(), True),
    ]
)

NETWORK_EVENTS_BRONZE = StructType(
    _ENV
    + [
        StructField("outage_id", StringType(), True),
        StructField("region", StringType(), True),
        StructField("tower_id", StringType(), True),
        StructField("status", StringType(), True),
        StructField("severity", IntegerType(), True),
        StructField("affected_pct", DoubleType(), True),
        StructField("cause", StringType(), True),
    ]
)

TOWER_METRICS_EVENTS_BRONZE = StructType(
    _ENV
    + [
        StructField("tower_id", StringType(), True),
        StructField("health", StringType(), True),
        StructField("signal_dbm", DoubleType(), True),
        StructField("load", DoubleType(), True),
        StructField("active_users", IntegerType(), True),
        StructField("total_minutes", IntegerType(), True),
        StructField("total_data_mb", DoubleType(), True),
        StructField("dropped_calls", IntegerType(), True),
    ]
)