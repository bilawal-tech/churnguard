# Step 14: Silver (PySpark)

Bronze (S3 `raw/`) is synced to `data/bronze/` (`python -m silver.bronze_sync`, Windows venv) and cleaned by PySpark (WSL, Java 17) into Parquet under `data/silver/`.

## Run (WSL, venv on, project root)
    python -m silver.run --table all        # dims, customers, usage, facts, lifecycle, network, dq
    python -m silver.verify_silver          # PASS/FAIL checks
    python -m pytest tests -q               # silver tests run in WSL, skip on Windows

## Cleaning rules
- Dedup by `event_id` (earliest `ingest_time`, then `bronze_file`).
- Rejects go to `data/silver/_rejects/<topic>/` with `reject_reason`; expected 0.
- Nulls are kept. Only deterministic imputation, each with a `<col>_imputed` flag: `offer_events.trigger_rule`, `discount_pct`; `package_events.validity_days`; `customer_events.city`; `network_events.cause`.
- `event_date` is the PKT date of `event_time` (the Bronze `dt=` folder is not trusted).
- Orphan keys are flagged (`customer_known`, `tower_known`, `package_known`), not rejected.

## Tables
| Group | Tables |
|---|---|
| Dims | dim_tower, dim_package, dim_field_team, tower_neighbors, dim_customer, customers_current |
| Facts | fact_usage (partitioned by event_date), fact_recharge, fact_package_events, fact_offer_events, fact_lifecycle_events, fact_network_events, fact_tower_metrics |
| Derived | customer_status_history (SCD2), subscriptions, offers, outages, tower_hourly_grid |

Side outputs: `_dq/<table>.json`, `_manifest/<table>.json`, `_rejects/`, `_logs/`.

## Leakage rule
Silver holds no features or labels. `churn_reason`, `at_risk` and `inactivity_days` are never Gold features.