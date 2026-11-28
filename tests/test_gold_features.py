import sys

import pytest

pytest.importorskip("pyspark")
pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Gold Spark tests run in WSL",
)

from datetime import date, datetime

from gold.features import build_churn_features
from silver.spark_session import build_spark


@pytest.fixture(scope="module")
def spark():
    session = build_spark(
        "test-gold-features",
        master_override="local[2]",
        shuffle_partitions_override=2,
    )
    yield session
    session.stop()


def test_features_use_only_pre_cutoff_data_and_default_missing_values(spark):
    active = spark.createDataFrame([("C1",), ("C2",)], "customer_id string")
    dim = spark.createDataFrame(
        [
            ("C1", "T1", date(2026, 4, 1), "prepaid", "low", "phone", "adult", "A"),
            ("C2", None, None, None, None, None, None, None),
        ],
        "customer_id string, home_tower_id string, signup_date date, segment string, "
        "arpu_band string, device_type string, age_band string, city string",
    )
    usage = spark.createDataFrame(
        [
            ("C1", date(2026, 7, 27), 10.0, 5, 2, 20.0, 1),
            ("C1", date(2026, 7, 20), 8.0, 4, 1, 10.0, 0),
            ("C1", date(2026, 7, 28), 100.0, 50, 20, 200.0, 10),
        ],
        "customer_id string, event_date date, total_data_mb double, total_call_min int, "
        "sms_count int, total_spend double, dropped_calls int",
    )
    recharge = spark.createDataFrame(
        [("C1", date(2026, 7, 27), "R1", 100)],
        "customer_id string, event_date date, event_id string, amount_pkr int",
    )
    package_events = spark.createDataFrame(
        [
            ("E1", "C1", "S1", date(2026, 7, 20), datetime(2026, 7, 20, 12, 0), "PURCHASE", 10),
            ("E2", "C1", "S1", date(2026, 7, 28), datetime(2026, 7, 28, 12, 0), "EXPIRE", 10),
        ],
        "event_id string, customer_id string, subscription_id string, event_date date, "
        "event_time timestamp, action string, validity_days int",
    )
    subscriptions = spark.createDataFrame([("S1",)], "subscription_id string")
    offers = spark.createDataFrame([], "customer_id string, offer_id string, sent_date date")
    offer_events = spark.createDataFrame(
        [], "customer_id string, offer_id string, event_date date, action string"
    )
    outages = spark.createDataFrame(
        [], "tower_id string, outage_id string, start_time timestamp, end_time timestamp"
    )
    metrics = spark.createDataFrame(
        [], "tower_id string, event_date date, health string"
    )

    rows = {
        row["customer_id"]: row
        for row in build_churn_features(
            active,
            dim,
            usage,
            recharge,
            package_events,
            subscriptions,
            offers,
            offer_events,
            outages,
            metrics,
        ).collect()
    }
    assert rows["C1"]["total_data_mb_7d"] == 10.0
    assert rows["C1"]["total_data_mb_30d"] == 18.0
    assert rows["C1"]["recharge_count_30d"] == 1
    assert rows["C1"]["has_active_package"] == 1
    assert rows["C1"]["days_since_last_recharge"] == 1
    assert rows["C2"]["total_data_mb_30d"] == 0.0
    assert rows["C2"]["days_since_last_recharge"] == 999
    assert rows["C2"]["segment"] == "unknown"
