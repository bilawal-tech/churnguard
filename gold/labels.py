from __future__ import annotations

from pyspark.sql import DataFrame
from pyspark.sql import functions as F

CUTOFF_DATE = "2026-07-28"
LABEL_WINDOW_DAYS = 60


def active_customers_at_cutoff(
    status_history: DataFrame,
    cutoff_date: str = CUTOFF_DATE,
) -> DataFrame:
    cutoff = F.lit(cutoff_date).cast("date")
    return (
        status_history.where(
            (F.col("status") == "ACTIVE")
            & (F.col("valid_from") <= cutoff)
            & (F.col("valid_to").isNull() | (F.col("valid_to") > cutoff))
        )
        .select("customer_id")
        .distinct()
    )


def build_churn_labels(
    active_customers: DataFrame,
    status_history: DataFrame,
    cutoff_date: str = CUTOFF_DATE,
    label_window_days: int = LABEL_WINDOW_DAYS,
) -> DataFrame:
    start = F.date_add(F.lit(cutoff_date).cast("date"), 1)
    end = F.date_add(F.lit(cutoff_date).cast("date"), label_window_days)
    churned = (
        status_history.where(
            (F.col("status") == "CHURNED")
            & (F.col("valid_from") >= start)
            & (F.col("valid_from") <= end)
        )
        .select("customer_id")
        .distinct()
        .withColumn("churned_60d", F.lit(1))
    )
    return (
        active_customers.join(churned, "customer_id", "left")
        .withColumn("churned_60d", F.coalesce(F.col("churned_60d"), F.lit(0)))
    )
