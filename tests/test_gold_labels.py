import sys

import pytest

pytest.importorskip("pyspark")
pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Gold Spark tests run in WSL",
)

from datetime import date

from gold.labels import active_customers_at_cutoff, build_churn_labels
from silver.spark_session import build_spark


@pytest.fixture(scope="module")
def spark():
    session = build_spark(
        "test-gold-labels",
        master_override="local[2]",
        shuffle_partitions_override=2,
    )
    yield session
    session.stop()


def test_cutoff_active_cohort_and_inclusive_label_window(spark):
    history = spark.createDataFrame(
        [
            ("C1", "ACTIVE", date(2026, 4, 1), date(2026, 8, 1)),
            ("C1", "CHURNED", date(2026, 8, 1), None),
            ("C2", "ACTIVE", date(2026, 4, 1), None),
            ("C2", "CHURNED", date(2026, 9, 26), None),
            ("C3", "ACTIVE", date(2026, 4, 1), date(2026, 7, 28)),
            ("C3", "CHURNED", date(2026, 7, 28), None),
            ("C4", "ACTIVE", date(2026, 7, 29), None),
        ],
        "customer_id string, status string, valid_from date, valid_to date",
    )
    active = active_customers_at_cutoff(history)
    labels = {
        row["customer_id"]: row["churned_60d"]
        for row in build_churn_labels(active, history).collect()
    }
    assert labels == {"C1": 1, "C2": 1}
