import pytest

pytest.importorskip("pyspark")

from datetime import date

from silver.common import latest_snapshot
from silver.spark_session import build_spark
from silver.tables.dims import build_tower_neighbors


@pytest.fixture(scope="module")
def spark():
    s = build_spark(
        "test-silver-dims",
        master_override="local[2]",
        shuffle_partitions_override=2,
    )
    yield s
    s.stop()


def test_latest_snapshot_keeps_newest(spark):
    df = spark.createDataFrame(
        [
            ("T1", date(2026, 9, 1), "snapshot_date=2026-09-01/m.jsonl.gz", 1),
            ("T1", date(2026, 9, 27), "snapshot_date=2026-09-27/m.jsonl.gz", 2),
            ("T2", date(2026, 9, 1), "snapshot_date=2026-09-01/m.jsonl.gz", 3),
        ],
        "tower_id string, snapshot_date date, bronze_file string, val int",
    )
    out = {r["tower_id"]: r["val"] for r in latest_snapshot(df, "tower_id").collect()}
    assert out == {"T1": 2, "T2": 3}


def test_tower_neighbors_explodes_with_rank(spark):
    df = spark.createDataFrame(
        [("T1", ["A", "B", "C"]), ("T2", []), ("T3", None)],
        "tower_id string, neighbor_tower_ids array<string>",
    )
    rows = build_tower_neighbors(df).orderBy("tower_id", "neighbor_rank").collect()
    got = [(r["tower_id"], r["neighbor_rank"], r["neighbor_tower_id"]) for r in rows]
    assert got == [("T1", 1, "A"), ("T1", 2, "B"), ("T1", 3, "C")]