from __future__ import annotations
import json
import time
from pathlib import Path
import shutil

from pyspark.sql import Column
from silver.settings import SIM_START_DATE, SIM_END_DATE

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql.types import StructType

from silver.settings import SilverSettings



def read_bronze_master(
    spark: SparkSession,
    settings: SilverSettings,
    master: str,
    schema: StructType,
) -> DataFrame:
    """Read all snapshots of one master with an explicit schema.

    Adds snapshot_date (from the folder name) and bronze_file (lineage).
    """
    path = settings.bronze_dir / "masters" / master / "snapshot_date=*" / f"{master}.jsonl.gz"
    df = spark.read.schema(schema).json(str(path))
    fp = F.col("_metadata.file_path")
    return df.withColumn(
        "snapshot_date",
        F.to_date(F.regexp_extract(fp, r"snapshot_date=(\d{4}-\d{2}-\d{2})", 1)),
    ).withColumn(
        "bronze_file",
        F.regexp_extract(fp, r"(snapshot_date=[^/]+/[^/]+)$", 1),
    )


def latest_snapshot(df: DataFrame, key: str) -> DataFrame:
    """Keep one row per key: the one from the newest snapshot_date."""
    w = Window.partitionBy(key).orderBy(F.col("snapshot_date").desc(), F.col("bronze_file").desc())
    return df.withColumn("_rn", F.row_number().over(w)).where(F.col("_rn") == 1).drop("_rn")


# Bronze verification se tay hui distinct event_id ginti
EXPECTED_DISTINCT = {
    "customer_events": 29_512,
    "profile_events": 29_515,
    "usage_events": 14_990_217,
    "recharge_events": 281_314,
    "package_events": 828_631,
    "offer_events": 680_139,
    "lifecycle_events": 8_295,
    "network_events": 292,
    "tower_metrics_events": 474_035,
}


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def null_counts(df: DataFrame) -> dict[str, int]:
    row = df.select(
        [F.sum(F.col(c).isNull().cast("int")).alias(c) for c in df.columns]
    ).collect()[0].asDict()
    return {c: int(row[c] or 0) for c in df.columns}


def read_bronze_events(spark, settings, topic: str, schema: StructType) -> DataFrame:
    path = settings.bronze_dir / "events" / topic / "dt=*" / "*.jsonl.gz"
    df = spark.read.schema(schema).json(str(path))
    return (
        df.withColumn("bronze_file", F.regexp_extract(F.col("_metadata.file_path"), r"([^/]+)$", 1))
        .withColumn("event_time", F.to_timestamp("event_time"))
        .withColumn("ingest_time", F.to_timestamp("ingest_time"))
    )


def common_reject_reason() -> Column:
    d = F.to_date("event_time")  # session timezone Asia/Karachi (PKT)
    return (
        F.when(F.col("event_id").isNull(), "event_id_null")
        .when(F.coalesce(F.col("schema_version") != "1.0", F.lit(True)), "bad_schema_version")
        .when(F.col("event_time").isNull(), "event_time_null")
        .when(
            (d < F.lit(SIM_START_DATE).cast("date")) | (d > F.lit(SIM_END_DATE).cast("date")),
            "event_time_out_of_range",
        )
    )


def split_rejects(df: DataFrame, extra_reason: Column | None = None):
    reason = common_reject_reason()
    if extra_reason is not None:
        reason = F.coalesce(reason, extra_reason)
    flagged = df.withColumn("reject_reason", reason).cache()
    valid = flagged.where(F.col("reject_reason").isNull()).drop("reject_reason")
    rejects = flagged.where(F.col("reject_reason").isNotNull())
    return valid, rejects


def dedup_by_event_id(df: DataFrame) -> DataFrame:
    w = Window.partitionBy("event_id").orderBy(
        F.col("ingest_time").asc_nulls_last(), F.col("bronze_file").asc()
    )
    return df.withColumn("_rn", F.row_number().over(w)).where(F.col("_rn") == 1).drop("_rn")


def clean_events(spark, settings, topic, schema, extra_reason=None):
    """Bronze padho, reject alag, dedup karo. Return (clean_df, stats)."""
    t0 = time.time()
    raw = read_bronze_events(spark, settings, topic, schema)
    valid, rejects = split_rejects(raw, extra_reason)
    valid = valid.cache()
    valid_n = valid.count()
    rej_n = rejects.count()
    by_reason = {r["reject_reason"]: r["n"] for r in rejects.groupBy("reject_reason").agg(F.count("*").alias("n")).collect()}
    if rej_n > 0:
        rejects.write.mode("overwrite").parquet(str(settings.rejects_dir / topic))
    else:
        shutil.rmtree(settings.rejects_dir / topic, ignore_errors=True)
    clean = dedup_by_event_id(valid)
    stats = {
        "started": t0,
        "bronze_files": len(list((settings.bronze_dir / "events" / topic).rglob("*.jsonl.gz"))),
        "bronze_rows": valid_n + rej_n,
        "valid_rows": valid_n,
        "rejects": rej_n,
        "rejects_by_reason": by_reason,
    }
    return clean, stats


def write_table(df, settings, table, stats, expected_distinct=None, files=1, partition_by=None):
    """Silver table likho, DQ + manifest json likho. Return dq dict."""
    df = df.cache()
    if partition_by:
        w = df.repartition(F.col(partition_by)).write.mode("overwrite").partitionBy(partition_by)
    else:
        w = df.coalesce(files).write.mode("overwrite")
    w.parquet(str(settings.silver_dir / table))
    rows_out = df.count()

    dq = dict(stats)
    dq.pop("started", None)
    if "valid_rows" in stats:
        removed = stats["valid_rows"] - rows_out
        dq["dedup_removed"] = removed
        dq["dedup_pct"] = round(100 * removed / max(stats["valid_rows"], 1), 3)
    dq["rows_out"] = rows_out
    dq["null_counts"] = null_counts(df)
    if "event_date" in df.columns:
        mm = df.agg(F.min("event_date").alias("a"), F.max("event_date").alias("b")).collect()[0]
        dq["min_event_date"], dq["max_event_date"] = mm["a"], mm["b"]

    problems = []
    if "dedup_pct" in dq and not (0.2 <= dq["dedup_pct"] <= 3.0):
        problems.append(f"dedup_pct {dq['dedup_pct']} 0.2-3.0 ke bahar")
    if stats.get("bronze_rows") and 100 * stats["rejects"] / stats["bronze_rows"] > 0.5:
        problems.append("rejects 0.5% se zyada")
    if expected_distinct is not None and stats.get("rejects") == 0 and rows_out != expected_distinct:
        problems.append(f"rows_out {rows_out} != expected {expected_distinct}")
    dq["problems"] = problems
    dq["status"] = "FAIL" if problems else "PASS"

    write_json(settings.dq_dir / f"{table}.json", dq)
    write_json(
        settings.manifest_dir / f"{table}.json",
        {
            "table": table,
            "bronze_files": stats.get("bronze_files"),
            "rows_in": stats.get("bronze_rows"),
            "rows_out": rows_out,
            "seconds": round(time.time() - stats.get("started", time.time()), 1),
        },
    )
    return dq
def flag_known(df: DataFrame, dim: DataFrame, key: str, flag: str) -> DataFrame:
    k = dim.select(F.col(key).alias("_k")).distinct()
    j = df.join(F.broadcast(k), df[key] == k["_k"], "left")
    return j.withColumn(
        flag,
        F.when(F.col(key).isNull(), F.lit(None).cast("boolean")).otherwise(F.col("_k").isNotNull()),
    ).drop("_k")