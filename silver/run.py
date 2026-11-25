from __future__ import annotations

import argparse
import json

from silver.settings import load_silver_settings
from silver.spark_session import build_spark
from silver.tables.customers import build_customers
from silver.tables.dims import build_dims
from silver.tables.facts import build_facts
from silver.tables.usage import build_usage
from silver.tables.lifecycle import build_lifecycle
from silver.tables.network import build_network


def _run_dims(spark, cfg):
    return {k: {"rows_out": v, "status": "-"} for k, v in build_dims(spark, cfg).items()}

def _run_dq(spark, cfg):
    out = {}
    for f in sorted(cfg.dq_dir.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        out[f.stem] = {"rows_out": d.get("rows_out", 0), "status": d.get("status", "-"), "problems": d.get("problems", "")}
    return out

TABLES = {
    "dims": _run_dims,
    "customers": build_customers,
    "usage": build_usage,
    "facts": build_facts,
    "lifecycle": build_lifecycle,
    "network": build_network,
    "network": build_network,
    "dq": _run_dq,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", default="all", help="all | " + " | ".join(TABLES))
    ap.add_argument("--config", default="config/config.yaml")
    args = ap.parse_args()
    cfg = load_silver_settings(config_path=args.config)
    names = list(TABLES) if args.table == "all" else [args.table]
    spark = build_spark("ChurnGuard-Silver", cfg)
    try:
        for name in names:
            for tbl, dq in TABLES[name](spark, cfg).items():
                print(f"{tbl:18s} rows_out={dq['rows_out']:>8,d} status={dq['status']} {dq.get('problems', '')}")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()