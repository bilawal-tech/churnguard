import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from simulator.common import ROOT, load_config
from simulator.core.clock import BANDS_PER_DAY
from simulator.core.engine import Simulator
from simulator.core.state_store import StateStore
from simulator.customers.hook import make_customer_hook
from simulator.billing.hooks import make_package_hook, make_recharge_hook
from simulator.dirty.processor import make_dirty_processor
from simulator.lifecycle.hooks import make_lifecycle_hook
from simulator.lifecycle import model as lifecycle_model
from simulator.masters.field_teams import build_field_teams
from simulator.masters.packages import build_packages
from simulator.masters.towers import add_neighbors, build_towers
from simulator.offers.hooks import make_offer_hook
from simulator.towers import model as tower_model
from simulator.towers.hook import make_tower_hook
from simulator.usage.hook import make_usage_hook


TOPICS = (
    "customer_events",
    "profile_events",
    "usage_events",
    "tower_metrics_events",
    "network_events",
    "recharge_events",
    "package_events",
    "lifecycle_events",
    "offer_events",
)


def _write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as output:
        for record in records:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")


def _ensure_masters(cfg, out_dir):
    tower_path = out_dir / "tower_master" / "tower_master.jsonl"
    package_path = out_dir / "packages_master" / "packages_master.jsonl"
    teams_path = out_dir / "field_teams_master" / "field_teams_master.jsonl"
    if tower_path.exists() and package_path.exists() and teams_path.exists():
        return add_neighbors(build_towers(cfg)), build_packages()

    start = date.fromisoformat(cfg["start_date"])
    towers = add_neighbors(build_towers(cfg))
    packages = build_packages()
    teams = build_field_teams(cfg)

    if not tower_path.exists():
        records = []
        for tower in towers:
            record = dict(tower)
            days = record.pop("install_days_ago")
            record["install_date"] = (start - timedelta(days=days)).isoformat()
            record["schema_version"] = "1.0"
            record["source"] = "simulator"
            records.append(record)
        _write_jsonl(tower_path, records)

    if not package_path.exists():
        records = []
        for package in packages:
            record = dict(package)
            record["schema_version"] = "1.0"
            record["source"] = "simulator"
            records.append(record)
        _write_jsonl(package_path, records)

    if not teams_path.exists():
        records = []
        for team in teams:
            record = dict(team)
            record["schema_version"] = "1.0"
            record["source"] = "simulator"
            records.append(record)
        _write_jsonl(teams_path, records)

    return towers, packages


def _reset_outputs(db_path, out_dir):
    for suffix in ("", "-wal", "-shm"):
        path = db_path.with_name(db_path.name + suffix)
        if path.exists():
            path.unlink()
    if out_dir.exists():
        for path in out_dir.glob("*_events.jsonl"):
            path.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--out-dir", default="data/raw")
    parser.add_argument("--db-path", default="state/sim_state.db")
    parser.add_argument("--days", type=int)
    parser.add_argument("--no-dirty", action="store_true")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    if args.days is not None:
        cfg["history_days"] = args.days

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    db_path = Path(args.db_path)
    if not db_path.is_absolute():
        db_path = ROOT / db_path

    if args.reset:
        _reset_outputs(db_path, out_dir)

    towers, packages = _ensure_masters(cfg, out_dir)
    hooks = [
        make_customer_hook(cfg, towers),
        make_package_hook(cfg, towers, packages),
        make_recharge_hook(cfg),
        make_usage_hook(cfg, towers, packages=packages),
        make_tower_hook(cfg, towers),
        make_offer_hook(cfg, packages),
        make_lifecycle_hook(cfg),
    ]
    post_hooks = [] if args.no_dirty else [make_dirty_processor(cfg)]

    store = StateStore(db_path)
    original_model_settings = (
        tower_model.SUDDEN_RATE,
        tower_model.DIP_RATE,
        lifecycle_model.BASE_DAILY_CHURN,
        lifecycle_model.INACTIVE_SUSPEND_DAYS,
        lifecycle_model.INACTIVE_CHURN_DAYS,
        lifecycle_model.REACTIVATE_CHANCE_PER_DAY,
    )
    try:
        tower_model.SUDDEN_RATE = 0.01
        tower_model.DIP_RATE = 0.01
        Simulator(
            cfg, store, out_dir, hooks=hooks, post_hooks=post_hooks
        ).run(live=False)
    finally:
        (
            tower_model.SUDDEN_RATE,
            tower_model.DIP_RATE,
            lifecycle_model.BASE_DAILY_CHURN,
            lifecycle_model.INACTIVE_SUSPEND_DAYS,
            lifecycle_model.INACTIVE_CHURN_DAYS,
            lifecycle_model.REACTIVATE_CHANCE_PER_DAY,
        ) = original_model_settings
        store.close()

    total_bands = cfg["history_days"] * BANDS_PER_DAY
    print(f"Days simulated: {cfg['history_days']}")
    print(f"Total bands: {total_bands}")
    print(f"Output directory: {out_dir}")
    print("Event line counts:")
    for topic in TOPICS:
        path = out_dir / f"{topic}.jsonl"
        count = sum(1 for _ in path.open("rb")) if path.exists() else 0
        print(f"  {topic}: {count}")
    return 0


if __name__ == "__main__":
    main()
