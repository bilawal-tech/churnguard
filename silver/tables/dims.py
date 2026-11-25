from __future__ import annotations

from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from silver.common import latest_snapshot, read_bronze_master
from silver.schemas import MASTER_SCHEMAS
from silver.settings import SilverSettings, load_silver_settings
from silver.spark_session import build_spark

# master name -> (dim table name, key column)
DIMS = {
    "tower_master": ("dim_tower", "tower_id"),
    "packages_master": ("dim_package", "package_id"),
    "field_teams_master": ("dim_field_team", "team_id"),
}


def build_tower_neighbors(dim_tower: DataFrame) -> DataFrame:
    return dim_tower.select(
        "tower_id",
        F.posexplode_outer("neighbor_tower_ids").alias("pos", "neighbor_tower_id"),
    ).select(
        "tower_id",
        (F.col("pos") + 1).alias("neighbor_rank"),
        "neighbor_tower_id",
    ).where(F.col("neighbor_tower_id").isNotNull())


def _write(df: DataFrame, settings: SilverSettings, name: str) -> None:
    df.coalesce(1).write.mode("overwrite").parquet(str(settings.silver_dir / name))


def build_dims(spark: SparkSession, settings: SilverSettings) -> dict[str, int]:
    counts: dict[str, int] = {}
    tower_df = None
    for master, (dim_name, key) in DIMS.items():
        raw = read_bronze_master(spark, settings, master, MASTER_SCHEMAS[master])
        dim = latest_snapshot(raw, key).cache()
        _write(dim, settings, dim_name)
        counts[dim_name] = dim.count()
        if master == "tower_master":
            tower_df = dim
    counts["tower_neighbors"] = _write_neighbors(tower_df, settings)
    return counts


def _write_neighbors(dim_tower: DataFrame, settings: SilverSettings) -> int:
    nb = build_tower_neighbors(dim_tower).cache()
    _write(nb, settings, "tower_neighbors")
    return nb.count()


def main() -> None:
    settings = load_silver_settings()
    spark = build_spark("ChurnGuard-Silver-dims", settings)
    try:
        for name, n in build_dims(spark, settings).items():
            print(f"{name:18s} rows={n}")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()