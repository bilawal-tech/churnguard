from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from silver.common import EXPECTED_DISTINCT, clean_events, write_table
from silver.schemas import CUSTOMER_EVENTS_BRONZE, PROFILE_EVENTS_BRONZE
from silver.settings import SilverSettings


def customer_reject_reason():
    return (
        F.when(~F.coalesce(F.col("segment").isin("prepaid", "postpaid"), F.lit(False)), "bad_segment")
        .when(F.col("initial_balance") < 0, "negative_initial_balance")
    )


def impute_city(cust: DataFrame, dim_tower: DataFrame) -> DataFrame:
    """city null ho to home_tower_id se tower_master ki city; tower_known flag."""
    t = dim_tower.select(F.col("tower_id").alias("_tid"), F.col("city").alias("_tcity"))
    j = cust.join(F.broadcast(t), cust["home_tower_id"] == t["_tid"], "left")
    return (
        j.withColumn(
            "tower_known",
            F.when(F.col("home_tower_id").isNull(), F.lit(None).cast("boolean"))
            .otherwise(F.col("_tid").isNotNull()),
        )
        .withColumn("city_imputed", F.col("city").isNull() & F.col("_tcity").isNotNull())
        .withColumn("city", F.coalesce(F.col("city"), F.col("_tcity")))
        .drop("_tid", "_tcity")
    )


def build_dim_customer(cust: DataFrame, prof: DataFrame) -> DataFrame:
    """Ek row har customer_id ki. Full outer join: customer event ya profile mein se
    koi ek bhi ho to customer girta nahi."""
    wc = Window.partitionBy("customer_id").orderBy(F.col("event_time").asc(), F.col("event_id").asc())
    c = (
        cust.withColumn("_rn", F.row_number().over(wc))
        .where(F.col("_rn") == 1)
        .select(
            "customer_id",
            "signup_date",
            F.col("event_time").alias("signup_time"),
            "region", "city", "city_imputed", "segment", "acquisition_channel",
            "device_type", "initial_balance", "home_tower_id", "tower_known",
            F.lit(True).alias("has_customer_event"),
        )
    )
    wp = Window.partitionBy("customer_id").orderBy(
        F.col("profile_version").desc_nulls_last(), F.col("event_time").desc()
    )
    p = (
        prof.withColumn("_rn", F.row_number().over(wp))
        .where(F.col("_rn") == 1)
        .select(
            "customer_id", "profile_version", "age_band", "gender", "phone_masked",
            "cnic_masked", "language_pref", "arpu_band",
            F.lit(True).alias("has_profile"),
        )
    )
    out = c.join(p, "customer_id", "full_outer")
    return out.fillna(False, subset=["has_customer_event", "has_profile"])


def build_customers(spark: SparkSession, settings: SilverSettings) -> dict[str, dict]:
    dim_tower = spark.read.parquet(str(settings.silver_dir / "dim_tower"))
    results: dict[str, dict] = {}

    c, c_stats = clean_events(spark, settings, "customer_events", CUSTOMER_EVENTS_BRONZE, customer_reject_reason())
    c = c.withColumn("signup_date", F.to_date("signup_date")).withColumn("event_date", F.to_date("event_time"))
    c = impute_city(c, dim_tower)
    results["customer_events"] = write_table(c, settings, "customer_events", c_stats, EXPECTED_DISTINCT["customer_events"])

    p, p_stats = clean_events(spark, settings, "profile_events", PROFILE_EVENTS_BRONZE)
    p = p.withColumn("event_date", F.to_date("event_time"))
    results["profile_events"] = write_table(p, settings, "profile_events", p_stats, EXPECTED_DISTINCT["profile_events"])

    cs = spark.read.parquet(str(settings.silver_dir / "customer_events"))
    ps = spark.read.parquet(str(settings.silver_dir / "profile_events"))
    dim = build_dim_customer(cs, ps)
    results["dim_customer"] = write_table(dim, settings, "dim_customer", {"started": c_stats["started"]})
    return results