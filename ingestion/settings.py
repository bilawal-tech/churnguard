"""Configuration for Kafka and S3 ingestion."""
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class IngestionSettings:
    bootstrap_servers: str = "localhost:9092"
    partitions: int = 6
    replication: int = 1
    retention_ms: int = 2_592_000_000
    s3_bucket: str = "churnguard-data-bilawal"
    s3_region: str = "ap-south-1"
    s3_root: str = "raw"
    batch_records: int = 5000
    batch_seconds: int = 60
    consumer_group: str = "bronze-writer"
    raw_data_dir: str = "data/raw"
    checkpoint_path: str = "state/ingest_producer_checkpoint.json"
    producer_dlq_dir: str = "data/dlq"


def load_settings(
    config_path: str | Path = "config/config.yaml",
    s3_root_override: str | None = None,
) -> IngestionSettings:
    """Load ingestion settings using existing Kafka and S3 config sections."""
    with Path(config_path).open(encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file) or {}
    if not isinstance(config, dict):
        raise ValueError("Config file must contain a YAML mapping")

    kafka = config.get("kafka") or {}
    s3 = config.get("s3") or {}
    ingestion = config.get("ingestion") or {}

    retention_ms = kafka.get("retention_ms")
    if retention_ms is None:
        retention_ms = ingestion.get("retention_ms", 2_592_000_000)

    return IngestionSettings(
        bootstrap_servers=kafka.get("bootstrap", "localhost:9092"),
        partitions=kafka.get("partitions", 6),
        replication=kafka.get("replication", 1),
        retention_ms=retention_ms,
        s3_bucket=s3.get("bucket", "churnguard-data-bilawal"),
        s3_region=s3.get("region", "ap-south-1"),
        s3_root=(
            s3_root_override
            if s3_root_override is not None
            else s3.get("prefix", "raw")
        ),
        batch_records=s3.get("batch_records", 5000),
        batch_seconds=s3.get("batch_seconds", 60),
        consumer_group=ingestion.get("consumer_group", "bronze-writer"),
        raw_data_dir=ingestion.get("raw_data_dir", "data/raw"),
        checkpoint_path=ingestion.get(
            "checkpoint_path", "state/ingest_producer_checkpoint.json"
        ),
        producer_dlq_dir=ingestion.get("producer_dlq_dir", "data/dlq"),
    )
