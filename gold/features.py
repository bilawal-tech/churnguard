from __future__ import annotations

from pyspark.sql import DataFrame, Window
from pyspark.sql import functions as F

from gold.labels import CUTOFF_DATE

USAGE_MEASURES = (
    "total_data_mb",
    "total_call_min",
    "sms_count",
    "total_spend",
    "dropped_calls",
)
CATEGORICAL_FEATURES = ("segment", "arpu_band", "device_type", "age_band", "city")
EVENT_TIME_ACTIONS = ("PURCHASE", "AUTO_RENEW", "ADDON_PURCHASE")


def _sum_if(condition, column: str):
    return F.sum(
        F.when(condition, F.coalesce(F.col(column), F.lit(0))).otherwise(F.lit(0))
    )


def _join_aggregate(base: DataFrame, aggregate: DataFrame) -> DataFrame:
    return base.join(aggregate, "customer_id", "left")


def build_churn_features(
    active_customers: DataFrame,
    dim_customer: DataFrame,
    fact_usage: DataFrame,
    fact_recharge: DataFrame,
    fact_package_events: DataFrame,
    subscriptions: DataFrame,
    offers: DataFrame,
    fact_offer_events: DataFrame,
    outages: DataFrame,
    fact_tower_metrics: DataFrame,
    cutoff_date: str = CUTOFF_DATE,
) -> DataFrame:
    cutoff = F.lit(cutoff_date).cast("date")
    day_7_start = F.date_sub(cutoff, 7)
    day_30_start = F.date_sub(cutoff, 30)
    previous_28_start = F.date_sub(cutoff, 35)

    profile = dim_customer.select(
        "customer_id",
        "home_tower_id",
        "signup_date",
        *CATEGORICAL_FEATURES,
    )
    base = active_customers.join(profile, "customer_id", "left").withColumn(
        "tenure_days",
        F.greatest(F.datediff(cutoff, F.col("signup_date")), F.lit(0)),
    ).drop("signup_date")

    usage = fact_usage.where(F.col("event_date") < cutoff)
    in_7d = F.col("event_date") >= day_7_start
    in_30d = F.col("event_date") >= day_30_start
    in_previous_28d = (
        (F.col("event_date") >= previous_28_start)
        & (F.col("event_date") < day_7_start)
    )
    usage_aggs = [
        _sum_if(in_7d, column).alias(f"{column}_7d")
        for column in USAGE_MEASURES
    ] + [
        _sum_if(in_30d, column).alias(f"{column}_30d")
        for column in USAGE_MEASURES
    ]
    usage_aggs.extend(
        [
            F.countDistinct(F.when(in_30d, F.col("event_date"))).alias(
                "active_days_30d"
            ),
            _sum_if(in_7d, "total_data_mb").alias("_data_7d"),
            _sum_if(in_7d, "total_call_min").alias("_calls_7d"),
            _sum_if(in_previous_28d, "total_data_mb").alias("_data_previous_28d"),
            _sum_if(in_previous_28d, "total_call_min").alias("_calls_previous_28d"),
        ]
    )
    usage_agg = usage.groupBy("customer_id").agg(*usage_aggs)
    base = _join_aggregate(base, usage_agg)
    previous_weekly_average = (
        F.coalesce(F.col("_data_previous_28d"), F.lit(0))
        + F.coalesce(F.col("_calls_previous_28d"), F.lit(0))
    ) / F.lit(4.0)
    recent_usage = (
        F.coalesce(F.col("_data_7d"), F.lit(0))
        + F.coalesce(F.col("_calls_7d"), F.lit(0))
    )
    base = base.withColumn(
        "usage_change_7d_pct",
        F.when(
            previous_weekly_average > 0,
            (recent_usage - previous_weekly_average) / previous_weekly_average * 100.0,
        ).otherwise(F.lit(0.0)),
    ).drop(
        "_data_7d",
        "_calls_7d",
        "_data_previous_28d",
        "_calls_previous_28d",
    )

    recharge = fact_recharge.where(F.col("event_date") < cutoff)
    recharge_agg = recharge.groupBy("customer_id").agg(
        F.sum(
            F.when(F.col("event_date") >= day_30_start, 1).otherwise(0)
        ).alias("recharge_count_30d"),
        F.sum(
            F.when(
                F.col("event_date") >= day_30_start,
                F.coalesce(F.col("amount_pkr"), F.lit(0)),
            ).otherwise(F.lit(0))
        ).alias("recharge_amount_30d"),
        F.max("event_date").alias("_last_recharge_date"),
    )
    base = _join_aggregate(base, recharge_agg).withColumn(
        "days_since_last_recharge",
        F.when(
            F.col("_last_recharge_date").isNull(),
            F.lit(999),
        ).otherwise(F.datediff(cutoff, F.col("_last_recharge_date"))),
    ).drop("_last_recharge_date")

    package_events = fact_package_events.where(F.col("event_date") < cutoff)
    eligible_subscriptions = subscriptions.select("subscription_id").distinct()
    package_events = package_events.join(
        eligible_subscriptions, "subscription_id", "inner"
    )
    package_agg = package_events.groupBy("customer_id").agg(
        F.sum(F.when(F.col("action") == "PURCHASE", 1).otherwise(0)).alias(
            "purchases_count"
        ),
        F.sum(F.when(F.col("action") == "AUTO_RENEW", 1).otherwise(0)).alias(
            "renewals"
        ),
    )
    base = _join_aggregate(base, package_agg)

    order = Window.partitionBy("subscription_id").orderBy(
        F.col("event_time").desc(), F.col("event_id").desc()
    )
    latest_package_state = (
        package_events.withColumn("_rn", F.row_number().over(order))
        .where(F.col("_rn") == 1)
        .withColumn(
            "_active",
            F.col("action").isin(*EVENT_TIME_ACTIONS)
            & F.col("validity_days").isNotNull()
            & (
                F.date_add(F.col("event_date"), F.col("validity_days"))
                >= cutoff
            ),
        )
        .groupBy("customer_id")
        .agg(F.max(F.col("_active").cast("int")).alias("has_active_package"))
    )
    base = _join_aggregate(base, latest_package_state)

    offer_summary = offers.where(F.col("sent_date") < cutoff)
    offers_sent = offer_summary.groupBy("customer_id").agg(
        F.countDistinct("offer_id").alias("offers_sent"),
        F.max("sent_date").alias("_last_offer_date"),
    )
    accepted_offers = (
        fact_offer_events.where(
            (F.col("event_date") < cutoff) & (F.col("action") == "ACCEPTED")
        )
        .select("customer_id", "offer_id")
        .distinct()
        .join(
            offer_summary.select("customer_id", "offer_id").distinct(),
            ["customer_id", "offer_id"],
            "inner",
        )
        .groupBy("customer_id")
        .agg(F.countDistinct("offer_id").alias("offers_accepted"))
    )
    base = _join_aggregate(base, offers_sent)
    base = _join_aggregate(base, accepted_offers).withColumn(
        "days_since_last_offer",
        F.when(
            F.col("_last_offer_date").isNull(),
            F.lit(999),
        ).otherwise(F.datediff(cutoff, F.col("_last_offer_date"))),
    ).drop("_last_offer_date")

    window_start_ts = F.date_sub(cutoff, 30).cast("timestamp")
    cutoff_ts = cutoff.cast("timestamp")
    overlapping_outages = outages.where(
        (F.col("start_time") < cutoff_ts)
        & (
            F.coalesce(F.col("end_time"), cutoff_ts)
            > window_start_ts
        )
    ).withColumn(
        "_clipped_start", F.greatest(F.col("start_time"), window_start_ts)
    ).withColumn(
        "_clipped_end",
        F.least(F.coalesce(F.col("end_time"), cutoff_ts), cutoff_ts),
    )
    outage_agg = (
        overlapping_outages.join(
            profile.select(
                F.col("customer_id").alias("_customer_id"),
                F.col("home_tower_id").alias("_home_tower_id"),
            ),
            overlapping_outages["tower_id"] == F.col("_home_tower_id"),
            "inner",
        )
        .groupBy(F.col("_customer_id").alias("customer_id"))
        .agg(
            F.sum(
                (
                    F.unix_timestamp("_clipped_end")
                    - F.unix_timestamp("_clipped_start")
                )
                / 3600.0
            ).alias("outage_hours_30d"),
            F.countDistinct("outage_id").alias("outage_count_30d"),
        )
    )
    base = _join_aggregate(base, outage_agg)

    degraded = fact_tower_metrics.where(
        (F.col("event_date") >= day_30_start)
        & (F.col("event_date") < cutoff)
    )
    tower_agg = (
        degraded.join(
            profile.select(
                F.col("customer_id").alias("_customer_id"),
                F.col("home_tower_id").alias("_home_tower_id"),
            ),
            degraded["tower_id"] == F.col("_home_tower_id"),
            "inner",
        )
        .groupBy(F.col("_customer_id").alias("customer_id"))
        .agg(
            F.sum(
                F.when(
                    F.col("health").isin("DEGRADED", "CRITICAL"), 1
                ).otherwise(0)
            ).alias("_degraded_count"),
            F.count(F.lit(1)).alias("_reading_count"),
        )
        .withColumn(
            "degraded_share_30d",
            F.col("_degraded_count") / F.col("_reading_count"),
        )
        .drop("_degraded_count", "_reading_count")
    )
    base = _join_aggregate(base, tower_agg)

    numeric_features = [
        *(f"{measure}_{window}" for measure in USAGE_MEASURES for window in ("7d", "30d")),
        "active_days_30d",
        "recharge_count_30d",
        "recharge_amount_30d",
        "purchases_count",
        "renewals",
        "offers_sent",
        "offers_accepted",
        "outage_hours_30d",
        "outage_count_30d",
        "degraded_share_30d",
        "tenure_days",
    ]
    base = base.withColumn(
        "recharge_count_30d",
        F.coalesce(F.col("recharge_count_30d"), F.lit(0)).cast("long"),
    )
    for column in numeric_features:
        base = base.withColumn(column, F.coalesce(F.col(column), F.lit(0)))
    base = (
        base.withColumn(
            "has_active_package",
            F.coalesce(F.col("has_active_package"), F.lit(0)).cast("int"),
        )
        .withColumn(
            "days_since_last_recharge",
            F.coalesce(F.col("days_since_last_recharge"), F.lit(999)).cast("int"),
        )
        .withColumn(
            "days_since_last_offer",
            F.coalesce(F.col("days_since_last_offer"), F.lit(999)).cast("int"),
        )
    )
    for column in CATEGORICAL_FEATURES:
        base = base.withColumn(
            column,
            F.coalesce(F.col(column), F.lit("unknown")),
        )

    output_columns = [
        "customer_id",
        *(f"{measure}_{window}" for measure in USAGE_MEASURES for window in ("7d", "30d")),
        "usage_change_7d_pct",
        "active_days_30d",
        "recharge_count_30d",
        "recharge_amount_30d",
        "days_since_last_recharge",
        "purchases_count",
        "has_active_package",
        "renewals",
        "offers_sent",
        "offers_accepted",
        "days_since_last_offer",
        "outage_hours_30d",
        "outage_count_30d",
        "degraded_share_30d",
        "tenure_days",
        *CATEGORICAL_FEATURES,
    ]
    return base.select(*output_columns)
