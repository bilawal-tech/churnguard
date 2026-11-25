from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

from silver.common import EXPECTED_DISTINCT, clean_events, flag_known, write_table
from silver.schemas import NETWORK_EVENTS_BRONZE, TOWER_METRICS_EVENTS_BRONZE
from silver.settings import SIM_START_DATE, SilverSettings

N_HOURS = 180 * 24  # 4,320


def network_reject_reason():
    return F.when(
        ~F.coalesce(F.col("status").isin("START", "END"), F.lit(False)), "bad_status"
    ).when((F.col("affected_pct") < 0) | (F.col("affected_pct") > 100), "bad_affected_pct")


def tower_metrics_reject_reason():
    return F.when(
        (F.col("signal_dbm") < -130) | (F.col("signal_dbm") > -40), "bad_signal"
    ).when(F.col("active_users") < 0, "negative_users")


def impute_cause(df: DataFrame) -> DataFrame:
    other = F.max("cause").over(Window.partitionBy("outage_id"))
    return df.withColumn(
        "cause_imputed", F.col("cause").isNull() & other.isNotNull()
    ).withColumn("cause", F.coalesce(F.col("cause"), other))


def build_outages(net: DataFrame) -> DataFrame:
    start = F.col("status") == "START"
    g = net.groupBy("outage_id").agg(
        F.first("tower_id", ignorenulls=True).alias("tower_id"),
        F.first("region", ignorenulls=True).alias("region"),
        F.min(F.when(start, F.col("event_time"))).alias("start_time"),
        F.min(F.when(F.col("status") == "END", F.col("event_time"))).alias("end_time"),
        F.max("cause").alias("cause"),
        F.coalesce(F.max(F.when(start, F.col("severity"))), F.max("severity")).alias("severity"),
        F.max(F.when(start, F.col("affected_pct"))).alias("affected_pct"),
    )
    return g.withColumn(
        "duration_hours",
        (F.unix_timestamp("end_time") - F.unix_timestamp("start_time")) / 3600.0,
    ).withColumn("is_open", F.col("end_time").isNull())


def build_tower_grid(
    spark: SparkSession,
    towers: DataFrame,
    metrics: DataFrame,
    outages: DataFrame,
    start_date: str = SIM_START_DATE,
    n_hours: int = N_HOURS,
) -> DataFrame:
    hours = spark.range(n_hours).select(
        F.timestamp_seconds(F.unix_timestamp(F.lit(f"{start_date} 00:00:00")) + F.col("id") * 3600).alias("hour_ts")
    )
    grid = towers.select("tower_id").distinct().crossJoin(hours)
    readings = (
        metrics.select("tower_id", F.date_trunc("hour", "event_time").alias("hour_ts"))
        .distinct()
        .withColumn("has_reading", F.lit(True))
    )
    grid = grid.join(readings, ["tower_id", "hour_ts"], "left").withColumn(
        "has_reading", F.coalesce(F.col("has_reading"), F.lit(False))
    )
    o = outages.where(F.col("start_time").isNotNull()).select(
        F.col("tower_id").alias("_o_tower"),
        F.col("start_time").alias("_o_start"),
        F.coalesce(F.col("end_time"), F.to_timestamp(F.lit("2100-01-01"))).alias("_o_end"),
    )
    j = grid.join(
        F.broadcast(o),
        (grid["tower_id"] == o["_o_tower"]) & (grid["hour_ts"] >= o["_o_start"]) & (grid["hour_ts"] < o["_o_end"]),
        "left",
    )
    return j.groupBy("tower_id", "hour_ts", "has_reading").agg(
        (F.max(F.col("_o_start").isNotNull().cast("int")) == 1).alias("in_outage")
    )


def build_network(spark: SparkSession, settings: SilverSettings) -> dict[str, dict]:
    sd = settings.silver_dir
    dim_t = spark.read.parquet(str(sd / "dim_tower"))
    out: dict[str, dict] = {}

    df, st = clean_events(spark, settings, "network_events", NETWORK_EVENTS_BRONZE, network_reject_reason())
    df = impute_cause(df.withColumn("event_date", F.to_date("event_time")))
    df = flag_known(df, dim_t, "tower_id", "tower_known")
    out["fact_network_events"] = write_table(df, settings, "fact_network_events", st, EXPECTED_DISTINCT["network_events"])
    net = spark.read.parquet(str(sd / "fact_network_events"))
    out["outages"] = write_table(build_outages(net), settings, "outages", {"started": st["started"]})

    df, st = clean_events(spark, settings, "tower_metrics_events", TOWER_METRICS_EVENTS_BRONZE, tower_metrics_reject_reason())
    df = flag_known(df.withColumn("event_date", F.to_date("event_time")), dim_t, "tower_id", "tower_known")
    out["fact_tower_metrics"] = write_table(df, settings, "fact_tower_metrics", st, EXPECTED_DISTINCT["tower_metrics_events"])

    metrics = spark.read.parquet(str(sd / "fact_tower_metrics"))
    outages = spark.read.parquet(str(sd / "outages"))
    grid = build_tower_grid(spark, dim_t, metrics, outages)
    out["tower_hourly_grid"] = write_table(grid, settings, "tower_hourly_grid", {"started": st["started"]})
    return out