from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from silver.common import EXPECTED_DISTINCT, clean_events, flag_known, write_table
from silver.schemas import OFFER_EVENTS_BRONZE, PACKAGE_EVENTS_BRONZE, RECHARGE_EVENTS_BRONZE
from silver.settings import SilverSettings

PACKAGE_ACTIONS = ["PURCHASE", "AUTO_RENEW", "EXPIRE", "QUOTA_EXHAUSTED", "ADDON_PURCHASE", "AUTO_RENEW_OFF"]
OFFER_TYPES = ["RECHARGE_BONUS", "DATA_BOOST", "CALL_BUNDLE", "WEEKEND_SPECIAL", "EVENT_OFFER", "CRICKET_PACK"]
OFFER_ACTIONS = ["SENT", "ACCEPTED", "EXPIRED", "HELD"]
OFFER_GROUPS = ["treatment", "control"]


def _bad(col: str, valid: list[str], reason: str):
    return F.when(~F.coalesce(F.col(col).isin(*valid), F.lit(False)), reason)


def recharge_reject_reason():
    return F.when(F.col("amount_pkr") <= 0, "bad_amount")


def package_reject_reason():
    return _bad("action", PACKAGE_ACTIONS, "bad_action")


def offer_reject_reason():
    return (
        _bad("action", OFFER_ACTIONS, "bad_action")
        .when(~F.coalesce(F.col("offer_type").isin(*OFFER_TYPES), F.lit(False)), "bad_offer_type")
        .when(~F.coalesce(F.col("group").isin(*OFFER_GROUPS), F.lit(False)), "bad_group")
        .when((F.col("discount_pct") < 0) | (F.col("discount_pct") > 1), "bad_discount")
    )


def impute_package(df: DataFrame, dim_package: DataFrame) -> DataFrame:
    p = dim_package.select(F.col("package_id").alias("_pid"), F.col("validity_days").alias("_pval"))
    j = df.join(F.broadcast(p), df["package_id"] == p["_pid"], "left")
    return (
        j.withColumn(
            "package_known",
            F.when(F.col("package_id").isNull(), F.lit(None).cast("boolean")).otherwise(F.col("_pid").isNotNull()),
        )
        .withColumn("validity_days_imputed", F.col("validity_days").isNull() & F.col("_pval").isNotNull())
        .withColumn("validity_days", F.coalesce(F.col("validity_days"), F.col("_pval")))
        .drop("_pid", "_pval")
    )


def impute_offers(df: DataFrame) -> DataFrame:
    t = F.col("offer_type")
    rule = (
        F.when(t == "RECHARGE_BONUS", "balance")
        .when(t.isin("DATA_BOOST", "CALL_BUNDLE"), "usage_mix")
        .when(t == "WEEKEND_SPECIAL", "weekend")
        .when(t.isin("EVENT_OFFER", "CRICKET_PACK"), "event")
    )
    other = F.max("discount_pct").over(Window.partitionBy("offer_id"))
    return (
        df.withColumn("trigger_rule_imputed", F.col("trigger_rule").isNull() & rule.isNotNull())
        .withColumn("trigger_rule", F.coalesce(F.col("trigger_rule"), rule))
        .withColumn("discount_pct_imputed", F.col("discount_pct").isNull() & other.isNotNull())
        .withColumn("discount_pct", F.coalesce(F.col("discount_pct"), other))
    )


def build_subscriptions(pk: DataFrame) -> DataFrame:
    def cnt(action):
        return F.sum(F.when(F.col("action") == action, 1).otherwise(0))

    return pk.groupBy("subscription_id").agg(
        F.first("customer_id", ignorenulls=True).alias("customer_id"),
        F.first("package_id", ignorenulls=True).alias("package_id"),
        F.min("event_time").alias("first_time"),
        F.max("event_time").alias("last_time"),
        cnt("AUTO_RENEW").alias("n_renewals"),
        cnt("QUOTA_EXHAUSTED").alias("n_quota_exhausted"),
        cnt("ADDON_PURCHASE").alias("n_addons"),
        (cnt("EXPIRE") > 0).alias("expired"),
        (cnt("AUTO_RENEW_OFF") > 0).alias("auto_renew_off"),
    )


def build_offers(of: DataFrame) -> DataFrame:
    def flag(*actions):
        return F.max(F.col("action").isin(*actions))

    g = of.groupBy("offer_id").agg(
        F.first("customer_id", ignorenulls=True).alias("customer_id"),
        F.first("offer_type", ignorenulls=True).alias("offer_type"),
        F.first("group", ignorenulls=True).alias("group"),
        F.first("trigger_rule", ignorenulls=True).alias("trigger_rule"),
        F.first("campaign_name", ignorenulls=True).alias("campaign_name"),
        F.first("package_id", ignorenulls=True).alias("package_id"),
        F.first("discount_pct", ignorenulls=True).alias("discount_pct"),
        F.min(F.when(F.col("action").isin("SENT", "HELD"), F.col("event_date"))).alias("sent_date"),
        F.min(F.when(F.col("action").isin("ACCEPTED", "EXPIRED"), F.col("event_date"))).alias("closed_date"),
        flag("HELD").alias("_held"),
        flag("ACCEPTED").alias("_acc"),
        flag("EXPIRED").alias("_exp"),
    )
    final = (
        F.when(F.col("_held"), "HELD")
        .when(F.col("_acc"), "ACCEPTED")
        .when(F.col("_exp"), "EXPIRED")
        .otherwise("OPEN")
    )
    return g.withColumn("final_action", final).drop("_held", "_acc", "_exp")


def build_facts(spark: SparkSession, settings: SilverSettings) -> dict[str, dict]:
    sd = settings.silver_dir
    dim_c = spark.read.parquet(str(sd / "dim_customer"))
    dim_p = spark.read.parquet(str(sd / "dim_package"))
    out: dict[str, dict] = {}

    df, st = clean_events(spark, settings, "recharge_events", RECHARGE_EVENTS_BRONZE, recharge_reject_reason())
    df = flag_known(df.withColumn("event_date", F.to_date("event_time")), dim_c, "customer_id", "customer_known")
    out["fact_recharge"] = write_table(df, settings, "fact_recharge", st, EXPECTED_DISTINCT["recharge_events"])

    df, st = clean_events(spark, settings, "package_events", PACKAGE_EVENTS_BRONZE, package_reject_reason())
    df = df.withColumn("event_date", F.to_date("event_time"))
    df = flag_known(impute_package(df, dim_p), dim_c, "customer_id", "customer_known")
    out["fact_package_events"] = write_table(df, settings, "fact_package_events", st, EXPECTED_DISTINCT["package_events"])
    pk = spark.read.parquet(str(sd / "fact_package_events"))
    out["subscriptions"] = write_table(build_subscriptions(pk), settings, "subscriptions", {"started": st["started"]})

    df, st = clean_events(spark, settings, "offer_events", OFFER_EVENTS_BRONZE, offer_reject_reason())
    df = df.withColumn("event_date", F.to_date("event_time"))
    df = flag_known(impute_offers(df), dim_c, "customer_id", "customer_known")
    out["fact_offer_events"] = write_table(df, settings, "fact_offer_events", st, EXPECTED_DISTINCT["offer_events"])
    of = spark.read.parquet(str(sd / "fact_offer_events"))
    out["offers"] = write_table(build_offers(of), settings, "offers", {"started": st["started"]})
    return out