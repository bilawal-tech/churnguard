import pytest

pytest.importorskip("pyspark")

from pyspark.sql import functions as F

from silver.spark_session import build_spark
from silver.tables.network import build_outages, build_tower_grid, impute_cause


@pytest.fixture(scope="module")
def spark():
    s = build_spark("test-silver-network", master_override="local[2]", shuffle_partitions_override=2)
    yield s
    s.stop()


def _net(spark):
    return spark.createDataFrame(
        [
            ("O1", "T1", "Lahore", "START", "2026-04-01 01:00:00", 2, 4.0, None),
            ("O1", "T1", "Lahore", "END", "2026-04-01 05:00:00", None, 4.0, "power_cut"),
            ("O2", "T2", "Karachi", "START", "2026-04-02 00:00:00", 1, 1.0, "fibre_cut"),
        ],
        "outage_id string, tower_id string, region string, status string, t string, "
        "severity int, affected_pct double, cause string",
    ).withColumn("event_time", F.to_timestamp("t"))


def test_impute_cause_from_other_row(spark):
    rows = {(r["outage_id"], r["status"]): r for r in impute_cause(_net(spark)).collect()}
    assert rows[("O1", "START")]["cause"] == "power_cut"
    assert rows[("O1", "START")]["cause_imputed"] is True


def test_outages_pairing(spark):
    out = {r["outage_id"]: r for r in build_outages(impute_cause(_net(spark))).collect()}
    assert out["O1"]["duration_hours"] == 4.0 and out["O1"]["is_open"] is False
    assert out["O1"]["severity"] == 2 and out["O1"]["cause"] == "power_cut"
    assert out["O2"]["is_open"] is True and out["O2"]["duration_hours"] is None


def test_tower_grid(spark):
    towers = spark.createDataFrame([("T1",)], "tower_id string")
    metrics = spark.createDataFrame(
        [("T1", "2026-04-01 00:00:00"), ("T1", "2026-04-01 03:00:00")], "tower_id string, t string"
    ).withColumn("event_time", F.to_timestamp("t"))
    outages = spark.createDataFrame(
        [("T1", "2026-04-01 01:00:00", "2026-04-01 03:00:00")], "tower_id string, s string, e string"
    ).withColumn("start_time", F.to_timestamp("s")).withColumn("end_time", F.to_timestamp("e"))
    grid = build_tower_grid(spark, towers, metrics, outages, start_date="2026-04-01", n_hours=4)
    rows = grid.orderBy("hour_ts").collect()
    assert [r["has_reading"] for r in rows] == [True, False, False, True]
    assert [r["in_outage"] for r in rows] == [False, True, True, False]