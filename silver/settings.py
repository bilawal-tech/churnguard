from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# Simulation date bounds (PKT, inclusive)
SIM_START_DATE = "2026-04-01"
SIM_END_DATE = "2026-09-28"

# Spark defaults (WSL2 local mode)
DEFAULT_SPARK_MASTER = "local[*]"
DEFAULT_DRIVER_MEMORY = "8g"
DEFAULT_SHUFFLE_PARTITIONS = 48
DEFAULT_TIMEZONE = "Asia/Karachi"
DEFAULT_SPARK_LOCAL_DIR = str(Path.home() / "spark-tmp")

# Canonical Bronze topic & master names
EVENT_TOPICS: tuple[str, ...] = (
    "customer_events",
    "profile_events",
    "usage_events",
    "recharge_events",
    "package_events",
    "offer_events",
    "lifecycle_events",
    "network_events",
    "tower_metrics_events",
)

MASTER_TABLES: tuple[str, ...] = (
    "tower_master",
    "packages_master",
    "field_teams_master",
)


@dataclass(frozen=True)
class SilverSettings:
    project_root: Path
    bronze_dir: Path
    silver_dir: Path
    rejects_dir: Path
    dq_dir: Path
    manifest_dir: Path
    logs_dir: Path
    s3_bucket: str
    s3_region: str
    s3_raw_prefix: str
    spark_master: str = DEFAULT_SPARK_MASTER
    driver_memory: str = DEFAULT_DRIVER_MEMORY
    shuffle_partitions: int = DEFAULT_SHUFFLE_PARTITIONS
    timezone: str = DEFAULT_TIMEZONE
    spark_local_dir: str = DEFAULT_SPARK_LOCAL_DIR


def load_silver_settings(
    config_path: str | Path = "config/config.yaml",
    bronze_dir: str | Path | None = None,
    silver_dir: str | Path | None = None,
) -> SilverSettings:
    cfg_file = Path(config_path)
    raw_cfg: dict[str, Any] = {}
    if cfg_file.exists():
        with cfg_file.open("r", encoding="utf-8") as f:
            raw_cfg = yaml.safe_load(f) or {}

    s3 = raw_cfg.get("s3") or {}
    root = Path.cwd()
    b_dir = Path(bronze_dir) if bronze_dir is not None else root / "data" / "bronze"
    s_dir = Path(silver_dir) if silver_dir is not None else root / "data" / "silver"

    return SilverSettings(
        project_root=root,
        bronze_dir=b_dir,
        silver_dir=s_dir,
        rejects_dir=s_dir / "_rejects",
        dq_dir=s_dir / "_dq",
        manifest_dir=s_dir / "_manifest",
        logs_dir=s_dir / "_logs",
        s3_bucket=str(s3.get("bucket", "churnguard-data-bilawal")),
        s3_region=str(s3.get("region", "ap-south-1")),
        s3_raw_prefix=str(s3.get("prefix", "raw")).strip("/"),
        spark_master=os.getenv("CHURNGUARD_SPARK_MASTER", DEFAULT_SPARK_MASTER),
        driver_memory=os.getenv("CHURNGUARD_SPARK_DRIVER_MEMORY", DEFAULT_DRIVER_MEMORY),
        shuffle_partitions=int(
            os.getenv("CHURNGUARD_SPARK_SHUFFLE_PARTITIONS", DEFAULT_SHUFFLE_PARTITIONS)
        ),
        timezone=DEFAULT_TIMEZONE,
        spark_local_dir=os.getenv("CHURNGUARD_SPARK_LOCAL_DIR", DEFAULT_SPARK_LOCAL_DIR),
    )