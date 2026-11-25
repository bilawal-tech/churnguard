import pytest

pytest.importorskip("pyspark")

from datetime import date

from silver.spark_session import build_spark
from silver.tables.lifecycle import build_customers_current, build_status_history


@pytest.fixture(scope="module")
def spark():
    s = build_spark("test-silver-lifecycle", master_override="local[2]", shuffle_partitions_override=2)
    yield s
    s.stop()


def _data(spark):
    dim = spark.createDataFrame(
        [("C1", date(2026, 4, 1)), ("C2", date(2026, 4, 1)), ("C3", date(2026, 4, 1))],
        "customer_id string, signup_date date",
    )
    lc = spark.createDataFrame(
        [
            ("C1", date(2026, 5, 10), "CHURNED", "HIGH_PRICE"),
            ("C3", date(2026, 5, 1), "SUSPENDED", None),
            ("C3", date(2026, 5, 20), "REACTIVATED", None),
        ],
        "customer_id string, event_date date, to_status string, churn_reason string",
    )
    return dim, lc


def test_status_history_scd2(spark):
    dim, lc = _data(spark)
    rows = build_status_history(dim, lc).orderBy("customer_id", "valid_from").collect()
    c1 = [(r["status"], r["valid_from"], r["valid_to"], r["churn_reason"]) for r in rows if r["customer_id"] == "C1"]
    assert c1 == [
        ("ACTIVE", date(2026, 4, 1), date(2026, 5, 11), None),
        ("CHURNED", date(2026, 5, 11), None, "HIGH_PRICE"),
    ]
    c3 = [r["status"] for r in rows if r["customer_id"] == "C3"]
    assert c3 == ["ACTIVE", "SUSPENDED", "ACTIVE"]


def test_one_current_row_per_customer(spark):
    dim, lc = _data(spark)
    hist = build_status_history(dim, lc)
    cur = hist.where("is_current").groupBy("customer_id").count().collect()
    assert {r["customer_id"]: r["count"] for r in cur} == {"C1": 1, "C2": 1, "C3": 1}


def test_customers_current(spark):
    dim, lc = _data(spark)
    cc = {r["customer_id"]: r for r in build_customers_current(dim, build_status_history(dim, lc)).collect()}
    assert cc["C1"]["status"] == "CHURNED" and cc["C1"]["churn_date"] == date(2026, 5, 10)
    assert cc["C2"]["status"] == "ACTIVE" and cc["C2"]["churn_date"] is None