import pytest

pytest.importorskip("pyspark")

from datetime import datetime

from silver.common import dedup_by_event_id, split_rejects
from silver.spark_session import build_spark
from silver.tables.customers import build_dim_customer, impute_city


@pytest.fixture(scope="module")
def spark():
    s = build_spark("test-silver-customers", master_override="local[2]", shuffle_partitions_override=2)
    yield s
    s.stop()


def _ev(spark, rows, cols):
    return spark.createDataFrame(rows, cols)


def test_dedup_keeps_earliest_ingest(spark):
    df = _ev(
        spark,
        [("e1", datetime(2026, 11, 2), "b2", 2), ("e1", datetime(2026, 11, 1), "b1", 1), ("e2", datetime(2026, 11, 1), "b1", 3)],
        "event_id string, ingest_time timestamp, bronze_file string, v int",
    )
    out = {r["event_id"]: r["v"] for r in dedup_by_event_id(df).collect()}
    assert out == {"e1": 1, "e2": 3}


def test_split_rejects_reasons(spark):
    t = datetime(2026, 5, 1)
    df = _ev(
        spark,
        [
            (None, t, "1.0"),
            ("a", t, "2.0"),
            ("b", None, "1.0"),
            ("c", datetime(2027, 1, 1), "1.0"),
            ("d", t, "1.0"),
        ],
        "event_id string, event_time timestamp, schema_version string",
    )
    valid, rejects = split_rejects(df)
    assert [r["event_id"] for r in valid.collect()] == ["d"]
    reasons = {r["reject_reason"] for r in rejects.collect()}
    assert reasons == {"event_id_null", "bad_schema_version", "event_time_null", "event_time_out_of_range"}


def test_impute_city_from_tower(spark):
    cust = _ev(spark, [("C1", None, "T1"), ("C2", "Lahore", "T9"), ("C3", None, None)],
               "customer_id string, city string, home_tower_id string")
    towers = _ev(spark, [("T1", "Karachi")], "tower_id string, city string")
    rows = {r["customer_id"]: r for r in impute_city(cust, towers).collect()}
    assert rows["C1"]["city"] == "Karachi" and rows["C1"]["city_imputed"] is True
    assert rows["C2"]["city"] == "Lahore" and rows["C2"]["tower_known"] is False
    assert rows["C3"]["city"] is None and rows["C3"]["tower_known"] is None


def test_dim_customer_keeps_profile_only_and_latest_profile(spark):
    t = datetime(2026, 4, 1)
    cust = _ev(
        spark,
        [("C1", "e1", t, None, "Lahore", False, "prepaid", "retailer", "smartphone_android", 80.0, "T1", True)],
        "customer_id string, event_id string, event_time timestamp, signup_date date, city string, "
        "city_imputed boolean, segment string, acquisition_channel string, device_type string, "
        "initial_balance double, home_tower_id string, tower_known boolean",
    ).withColumn("region", cust_region := __import__("pyspark.sql.functions", fromlist=["lit"]).lit("Lahore"))
    prof = _ev(
        spark,
        [("C1", "p1", t, 1, "18-24", "male", "x", "y", "Urdu", "low"),
         ("C1", "p2", t, 2, "25-34", "male", "x", "y", "Urdu", "mid"),
         ("C2", "p3", t, 1, "35-44", "female", "x", "y", "Urdu", "high")],
        "customer_id string, event_id string, event_time timestamp, profile_version int, age_band string, "
        "gender string, phone_masked string, cnic_masked string, language_pref string, arpu_band string",
    )
    rows = {r["customer_id"]: r for r in build_dim_customer(cust, prof).collect()}
    assert set(rows) == {"C1", "C2"}
    assert rows["C1"]["age_band"] == "25-34"
    assert rows["C2"]["has_customer_event"] is False and rows["C2"]["has_profile"] is True