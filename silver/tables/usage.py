from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from silver.common import EXPECTED_DISTINCT, clean_events, flag_known, write_table
from silver.schemas import USAGE_EVENTS_BRONZE
from silver.settings import SilverSettings

CALLS = ["calls_onnet_min", "calls_offnet_min", "calls_intl_min"]
DATA = ["data_mb_whatsapp", "data_mb_social", "data_mb_video", "data_mb_browsing", "data_mb_other"]
MEASURES = CALLS + ["sms_count"] + DATA + ["dropped_calls"]
SPEND = ["spend_from_package", "spend_from_balance"]


def usage_reject_reason():
    cols = [F.coalesce(F.col(c), F.lit(0)) for c in MEASURES + SPEND]
    return F.when(F.least(*cols) < 0, "negative_measure")


def _sum0(cols):
    out = F.lit(0)
    for c in cols:
        out = out + F.coalesce(F.col(c), F.lit(0))
    return out


def derive_usage(df: DataFrame) -> DataFrame:
    h = F.hour("event_time")
    has_null = F.lit(False)
    for c in MEASURES:
        has_null = has_null | F.col(c).isNull()
    return (
        df.withColumn(
            "band",
            F.when(h < 6, "Night").when(h < 12, "Morning").when(h < 18, "Afternoon").otherwise("Evening"),
        )
        .withColumn("total_data_mb", F.round(_sum0(DATA), 2))
        .withColumn("total_call_min", _sum0(CALLS))
        .withColumn("total_spend", F.round(_sum0(SPEND), 2))
        .withColumn("has_null_measure", has_null)
    )


def build_usage(spark: SparkSession, settings: SilverSettings) -> dict[str, dict]:
    dim_c = spark.read.parquet(str(settings.silver_dir / "dim_customer"))
    dim_t = spark.read.parquet(str(settings.silver_dir / "dim_tower"))
    df, stats = clean_events(spark, settings, "usage_events", USAGE_EVENTS_BRONZE, usage_reject_reason())
    df = df.withColumn("event_date", F.to_date("event_time"))
    df = derive_usage(df)
    df = flag_known(df, dim_c, "customer_id", "customer_known")
    df = flag_known(df, dim_t, "tower_id", "tower_known")
    dq = write_table(df, settings, "fact_usage", stats, EXPECTED_DISTINCT["usage_events"], partition_by="event_date")
    return {"fact_usage": dq}