from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from silver.common import EXPECTED_DISTINCT, clean_events, flag_known, write_table
from silver.schemas import LIFECYCLE_EVENTS_BRONZE
from silver.settings import SilverSettings

VALID_STATUS = ["ACTIVE", "SUSPENDED", "CHURNED", "REACTIVATED"]


def lifecycle_reject_reason():
    return F.when(
        ~F.coalesce(F.col("to_status").isin(*VALID_STATUS), F.lit(False)), "bad_to_status"
    ).when(F.col("from_status") == F.col("to_status"), "same_status")


def build_status_history(dim_customer: DataFrame, lifecycle: DataFrame) -> DataFrame:
    init = dim_customer.select(
        "customer_id",
        F.lit("ACTIVE").alias("status"),
        F.col("signup_date").alias("valid_from"),
        F.lit(None).cast("string").alias("churn_reason"),
        F.lit(None).cast("date").alias("transition_date"),
        F.lit(0).alias("_ord"),
    )
    trans = lifecycle.select(
        "customer_id",
        F.when(F.col("to_status") == "REACTIVATED", "ACTIVE").otherwise(F.col("to_status")).alias("status"),
        F.date_add(F.col("event_date"), 1).alias("valid_from"),
        F.when(F.col("to_status") == "CHURNED", F.col("churn_reason")).alias("churn_reason"),
        F.col("event_date").alias("transition_date"),
        F.lit(1).alias("_ord"),
    )
    w = Window.partitionBy("customer_id").orderBy(
        F.col("valid_from").asc_nulls_first(), F.col("_ord"), F.col("transition_date")
    )
    return (
        init.unionByName(trans)
        .withColumn("valid_to", F.lead("valid_from").over(w))
        .withColumn("is_current", F.col("valid_to").isNull())
        .select("customer_id", "status", "valid_from", "valid_to", "churn_reason", "transition_date", "is_current")
    )


def build_customers_current(dim_customer: DataFrame, history: DataFrame) -> DataFrame:
    cur = history.where("is_current").select(
        "customer_id",
        F.col("status"),
        F.col("valid_from").alias("status_since"),
        F.when(F.col("status") == "CHURNED", F.col("transition_date")).alias("churn_date"),
        "churn_reason",
    )
    return dim_customer.join(cur, "customer_id", "left")


def build_lifecycle(spark: SparkSession, settings: SilverSettings) -> dict[str, dict]:
    sd = settings.silver_dir
    dim_c = spark.read.parquet(str(sd / "dim_customer"))
    out: dict[str, dict] = {}

    df, st = clean_events(spark, settings, "lifecycle_events", LIFECYCLE_EVENTS_BRONZE, lifecycle_reject_reason())
    df = flag_known(df.withColumn("event_date", F.to_date("event_time")), dim_c, "customer_id", "customer_known")
    out["fact_lifecycle_events"] = write_table(df, settings, "fact_lifecycle_events", st, EXPECTED_DISTINCT["lifecycle_events"])

    lc = spark.read.parquet(str(sd / "fact_lifecycle_events"))
    hist = build_status_history(dim_c, lc)
    out["customer_status_history"] = write_table(hist, settings, "customer_status_history", {"started": st["started"]})

    hist = spark.read.parquet(str(sd / "customer_status_history"))
    out["customers_current"] = write_table(build_customers_current(dim_c, hist), settings, "customers_current", {"started": st["started"]})
    return out