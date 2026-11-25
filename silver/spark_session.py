from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from silver.settings import SilverSettings, load_silver_settings

if TYPE_CHECKING:
    from pyspark.sql import SparkSession


def build_spark(
    app_name: str = "ChurnGuard-Silver",
    settings: SilverSettings | None = None,
    master_override: str | None = None,
    shuffle_partitions_override: int | None = None,
) -> "SparkSession":
    from pyspark.sql import SparkSession

    cfg = settings or load_silver_settings()
    master = master_override or cfg.spark_master
    partitions = (
        shuffle_partitions_override
        if shuffle_partitions_override is not None
        else cfg.shuffle_partitions
    )

    local_dir = Path(cfg.spark_local_dir)
    local_dir.mkdir(parents=True, exist_ok=True)

    builder = (
        SparkSession.builder.appName(app_name)
        .master(master)
        .config("spark.driver.memory", cfg.driver_memory)
        .config("spark.sql.shuffle.partitions", str(partitions))
        .config("spark.sql.session.timeZone", cfg.timezone)
        .config("spark.sql.sources.partitionOverwriteMode", "dynamic")
        .config("spark.sql.parquet.compression.codec", "snappy")
        .config("spark.local.dir", str(local_dir))
        .config("spark.ui.showConsoleProgress", "false")
    )

    spark = builder.getOrCreate()
    spark.sparkContext.setLogLevel("WARN")
    return spark