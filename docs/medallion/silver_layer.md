# Silver Layer — Cleansed & Conformed Tables

## 1. Overview

- **Medallion Role:** **Silver (Cleansed)** — deduplicated, typed, validated facts and dimensions built from Bronze. No features, no labels.
- **Engine:** PySpark 4.2.1, local mode, WSL2 Ubuntu, Java 17.
- **Storage:** `data/silver/<table>/`, Parquet (snappy). Optional S3 upload later.
- **Input:** local Bronze mirror `data/bronze/` (see `bronze_layer.md`).
- **Run mode:** full rebuild per table (overwrite). Timezone `Asia/Karachi` (PKT).
- **Verification:** `python -m silver.verify_silver` ends with `RESULT PASS`.

---

## 2. Directory Layout

```text
data/silver/
├── dim_tower/  dim_package/  dim_field_team/  tower_neighbors/
├── dim_customer/  customers_current/  customer_status_history/
├── fact_usage/event_date=YYYY-MM-DD/      (180 partitions, 1 file each)
├── fact_recharge/  fact_package_events/  fact_offer_events/
├── fact_lifecycle_events/  fact_network_events/  fact_tower_metrics/
├── subscriptions/  offers/  outages/  tower_hourly_grid/
├── customer_events/  profile_events/
├── _dq/  _manifest/  _rejects/  _logs/
```

## 3. Table Inventory

| Group | Table | Rows | Grain / Description |
|---|---|---:|---|
| Dim | dim_tower | 110 | One row per tower (latest snapshot). |
| Dim | dim_package | 29 | One row per package. |
| Dim | dim_field_team | 25 | One row per field team. |
| Dim | tower_neighbors | 330 | Tower to its 3 nearest towers, with rank. |
| Dim | dim_customer | 29,515 | One row per customer: signup event plus latest profile (masked PII). |
| Dim | customers_current | 29,515 | dim_customer plus current status, churn_date, churn_reason (ground truth). |
| History | customer_status_history | 37,810 | SCD2 status per customer (`valid_from`, `valid_to`, `is_current`). |
| Fact | fact_usage | 14,990,217 | Customer x time band, with derived band, totals and flags. |
| Fact | fact_recharge | 281,314 | One row per recharge. |
| Fact | fact_package_events | 828,631 | One row per package event (6 actions). |
| Fact | fact_offer_events | 680,139 | One row per offer event (SENT, ACCEPTED, EXPIRED, HELD). |
| Fact | fact_lifecycle_events | 8,295 | Status transitions (currently ACTIVE to CHURNED only). |
| Fact | fact_network_events | 292 | Outage START and END events. |
| Fact | fact_tower_metrics | 474,035 | Hourly tower readings (DOWN hours have no reading). |
| Derived | subscriptions | 225,111 | One row per `subscription_id`. |
| Derived | offers | 363,259 | One row per `offer_id` with `final_action`. |
| Derived | outages | 146 | START and END paired by `outage_id`. |
| Derived | tower_hourly_grid | 475,200 | 110 towers x 4,320 hours with `has_reading` and `in_outage`. |
| Staging | customer_events / profile_events | 29,512 / 29,515 | Cleaned Bronze events feeding dim_customer. |

## 4. Cleaning Rules

1. **Dedup:** by `event_id`, keep the earliest `ingest_time` (then `bronze_file`). Removed share is about 0.5% per large topic and is checked in the DQ report.
2. **Quarantine:** invalid rows go to `_rejects/<topic>/` with `reject_reason` (null `event_id`, schema_version not "1.0", event_time null or outside 2026-04-01 to 2026-09-28, plus topic rules). Current run: 0 rejects.
3. **Nulls:** kept, never dropped. Only deterministic imputation, each with a `<col>_imputed` flag: `offer_events.trigger_rule`, `discount_pct`; `package_events.validity_days`; `customer_events.city`; `network_events.cause`.
4. **Dates:** `event_date` is the PKT date of `event_time`. The Bronze `dt=` folder is not trusted (late events).
5. **Orphans:** flagged, not rejected (`customer_known`, `tower_known`, `package_known`). Current orphans in fact_usage: 0.
6. **Derived usage columns:** `band`, `total_data_mb`, `total_call_min`, `total_spend`, `has_null_measure`.
7. **Status history:** ACTIVE from signup date; new status starts the day after the event (decision at end of Evening). REACTIVATED is stored as ACTIVE.

## 5. Quality Gates (per table, `_dq/<table>.json`)

- Dedup removed outside 0.2% to 1.0% fails the table.
- Rejects above 0.5% fails the table.
- `rows_out` must equal the expected distinct `event_id` count when rejects are 0.
- Tower grid check: 33,756 hours without reading, matching outage downtime; no reading inside an outage window.

## 6. Guarantees and Governance

- Silver holds only clean facts, dimensions, status history, outages and the tower grid. No features, rolling windows or labels (those belong to Gold).
- **Leakage list (never a Gold feature):** `churn_reason`, `at_risk`, `inactivity_days`, anything after the cutoff date.
- PII stays masked (`phone_masked`, `cnic_masked`).
- Every row carries `bronze_file` for lineage.

## 7. Run Commands

```bash
# WSL, venv on, project root
python -m silver.run --table all
python -m silver.verify_silver
```

```powershell
# Windows PowerShell, venv on (Bronze sync only)
python -m silver.bronze_sync --workers 16
```