# Bronze Layer — Raw Ingestion & Storage Architecture

## 1. Overview

- **Medallion Role:** **Bronze (Raw)** — Immutable, append-only landing zone storing raw simulated telecom events and master reference snapshots exactly as emitted by the producer pipeline.
- **Primary Cloud Storage:** Amazon S3 (`s3://churnguard-data-bilawal/raw/`)
- **Local Mirror (for Spark ETL):** `data/bronze/` (synced via `silver/bronze_sync.py`)
- **Serialization & Compression:** Gzipped JSON Lines (`.jsonl.gz`), UTF-8 encoded, schema version `"1.0"`.
- **Simulation Window:** `2026-04-01` through `2026-09-27` (`180` days, `Asia/Karachi` / PKT).

---

## 2. Directory & Partition Layout

```text
s3://churnguard-data-bilawal/raw/   (and local data/bronze/)
├── masters/
│   ├── tower_master/snapshot_date=2026-04-01/tower_master.jsonl.gz
│   ├── packages_master/snapshot_date=2026-04-01/packages_master.jsonl.gz
│   └── field_teams_master/snapshot_date=2026-04-01/field_teams_master.jsonl.gz
└── events/
    ├── customer_events/dt=YYYY-MM-DD/*.jsonl.gz
    ├── profile_events/dt=YYYY-MM-DD/*.jsonl.gz
    ├── usage_events/dt=YYYY-MM-DD/*.jsonl.gz
    ├── recharge_events/dt=YYYY-MM-DD/*.jsonl.gz
    ├── package_events/dt=YYYY-MM-DD/*.jsonl.gz
    ├── offer_events/dt=YYYY-MM-DD/*.jsonl.gz
    ├── lifecycle_events/dt=YYYY-MM-DD/*.jsonl.gz
    ├── network_events/dt=YYYY-MM-DD/*.jsonl.gz
    └── tower_metrics_events/dt=YYYY-MM-DD/*.jsonl.gz
```

## 3. Dataset Inventory & Volume

| Category | Dataset / Topic | Partitioning | Files | Volume / Scale | Description |
|---|---|---|---:|---|---|
| Master | tower_master | `snapshot_date=YYYY-MM-DD` | 1 | 110 towers | Cell tower locations, regions, cities, zones, coordinates, and capacity. |
| Master | packages_master | `snapshot_date=YYYY-MM-DD` | 1 | 29 packages | Telecom bundle catalog (price, validity, voice/SMS/data quotas). |
| Master | field_teams_master | `snapshot_date=YYYY-MM-DD` | 1 | 25 teams | Regional field engineering teams and base coordinates. |
| Event | customer_events | `dt=YYYY-MM-DD` | ~180 | ~29.5K rows | Customer signups, segments, acquisition channels, and home towers. |
| Event | profile_events | `dt=YYYY-MM-DD` | ~180 | ~29.8K rows | Versioned customer demographic & device profiles (masked PII). |
| Event | usage_events | `dt=YYYY-MM-DD` | ~180 | ~14.0M rows | Daily customer voice, SMS, app-level data usage, and spend. |
| Event | recharge_events | `dt=YYYY-MM-DD` | ~180 | ~450K+ rows | Top-up transactions, channels, and before/after balances. |
| Event | package_events | `dt=YYYY-MM-DD` | ~180 | ~400K+ rows | Subscription lifecycle events (SUBSCRIBE, RENEW, EXPIRE, CANCEL). |
| Event | offer_events | `dt=YYYY-MM-DD` | ~180 | ~350K+ rows | Retention & promotional offer funnel events (TRIGGERED to REDEEMED). |
| Event | lifecycle_events | `dt=YYYY-MM-DD` | ~180 | 6,956 rows | Customer status transitions (ACTIVE, SUSPENDED, CHURNED). |
| Event | network_events | `dt=YYYY-MM-DD` | ~180 | ~15K+ rows | Tower outage detection, team dispatch, and restoration logs. |
| Event | tower_metrics_events | `dt=YYYY-MM-DD` | ~180 | ~475K rows | Hourly per-tower KPIs (PRB utilization, latency, packet loss, throughput). |

**Total Local Sync Footprint:** 4,658 files (691.37 MB compressed .jsonl.gz).

## 4. Common Envelope & Guarantees

**Standard Envelope Fields (All Event Topics):**

- `event_id` (UUID string — natural deduplication key)
- `event_time` (ISO-8601 timestamp with +05:00 PKT offset)
- `schema_version` ("1.0")
- `source` ("simulator" or "kafka_consumer")
- `ingest_time` (ISO-8601 ingestion timestamp)

**PII Governance at Ingestion:**

Sensitive identifiers (phone_masked, cnic_masked) are masked before Bronze persistence; no raw MSISDN or CNIC is stored.

**Immutability:**

Bronze files are never modified in place. All deduplication, null imputation, type casting, and quarantine handling occur downstream in the Silver Layer (docs/medallion/silver_layer.md).

## 5. Local Sync Command (S3 -> Local Bronze)

```bash
python -m silver.bronze_sync --workers 16
```
