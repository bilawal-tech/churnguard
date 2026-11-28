from __future__ import annotations

from gold.labels import CUTOFF_DATE, active_customers_at_cutoff
from gold.settings import load_gold_settings
from silver.spark_session import build_spark

FORBIDDEN_COLUMNS = {
    "churn_reason",
    "at_risk",
    "inactivity_days",
    "transition_date",
    "status",
    "valid_from",
    "valid_to",
}


def main() -> None:
    settings = load_gold_settings()
    spark = build_spark("ChurnGuard-Gold-Verify", settings.silver_settings)
    passed = True
    try:
        gold = spark.read.parquet(str(settings.gold_dir / "churn_features"))
        history = spark.read.parquet(
            str(settings.silver_dir / "customer_status_history")
        )
        expected = active_customers_at_cutoff(history, CUTOFF_DATE).count()
        rows = gold.count()
        unique = rows == gold.select("customer_id").distinct().count()
        label_nulls = gold.where(gold["churned_60d"].isNull()).count()
        forbidden = sorted(FORBIDDEN_COLUMNS.intersection(gold.columns))
        class_counts = {
            row["churned_60d"]: row["count"]
            for row in gold.groupBy("churned_60d").count().collect()
        }
        churned = class_counts.get(1, 0)
        label_rate = churned / rows if rows else 0.0

        checks = [
            ("customer_id unique", unique),
            ("row count matches cutoff-active customers", rows == expected),
            ("labels are non-null", label_nulls == 0),
            ("no forbidden columns", not forbidden),
        ]
        for name, result in checks:
            print(f"{'PASS' if result else 'FAIL'}: {name}")
            passed = passed and result
        print(f"rows={rows}, expected_active={expected}")
        print(f"label_rate={label_rate:.6f}, class_counts={class_counts}")
        if forbidden:
            print(f"forbidden_columns={forbidden}")
    except Exception as exc:
        passed = False
        print(f"FAIL: verification error: {exc}")
    finally:
        spark.stop()
    print(f"RESULT {'PASS' if passed else 'FAIL'}")


if __name__ == "__main__":
    main()
