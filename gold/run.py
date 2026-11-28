from __future__ import annotations

from gold.features import build_churn_features
from gold.labels import (
    CUTOFF_DATE,
    LABEL_WINDOW_DAYS,
    active_customers_at_cutoff,
    build_churn_labels,
)
from gold.settings import load_gold_settings
from silver.spark_session import build_spark


def main() -> None:
    settings = load_gold_settings()
    spark = build_spark("ChurnGuard-Gold", settings.silver_settings)
    try:
        silver = settings.silver_dir
        read = lambda table: spark.read.parquet(str(silver / table))
        history = read("customer_status_history")
        active = active_customers_at_cutoff(history, CUTOFF_DATE)
        features = build_churn_features(
            active_customers=active,
            dim_customer=read("dim_customer"),
            fact_usage=read("fact_usage"),
            fact_recharge=read("fact_recharge"),
            fact_package_events=read("fact_package_events"),
            subscriptions=read("subscriptions"),
            offers=read("offers"),
            fact_offer_events=read("fact_offer_events"),
            outages=read("outages"),
            fact_tower_metrics=read("fact_tower_metrics"),
            cutoff_date=CUTOFF_DATE,
        )
        labels = build_churn_labels(
            active,
            history,
            cutoff_date=CUTOFF_DATE,
            label_window_days=LABEL_WINDOW_DAYS,
        )
        gold = features.join(labels, "customer_id", "inner")
        output = settings.gold_dir / "churn_features"
        output.parent.mkdir(parents=True, exist_ok=True)
        gold.write.mode("overwrite").parquet(str(output))
        print(f"Wrote {gold.count()} customers to {output}")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
