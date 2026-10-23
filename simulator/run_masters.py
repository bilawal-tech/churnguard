import argparse
import json
from datetime import date, timedelta

from simulator.common import ROOT, load_config
from simulator.masters.packages import build_packages
from simulator.masters.towers import add_neighbors, build_towers
from simulator.masters.field_teams import build_field_teams


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()

    cfg = load_config(args.config)
    start = date.fromisoformat(cfg["start_date"])

    towers = []
    for t in add_neighbors(build_towers(cfg)):
        rec = dict(t)
        days = rec.pop("install_days_ago")
        rec["install_date"] = (start - timedelta(days=days)).isoformat()
        rec["schema_version"] = "1.0"
        rec["source"] = "simulator"
        towers.append(rec)
    out = ROOT / "data" / "raw" / "tower_master" / "tower_master.jsonl"
    write_jsonl(out, towers)
    print(f"{len(towers)} towers likhe gaye -> {out}")

    packages = []
    for p in build_packages():
        rec = dict(p)
        rec["schema_version"] = "1.0"
        rec["source"] = "simulator"
        packages.append(rec)
    out = ROOT / "data" / "raw" / "packages_master" / "packages_master.jsonl"
    write_jsonl(out, packages)
    print(f"{len(packages)} packages likhe gaye -> {out}")

    teams = []
    for t in build_field_teams(cfg):
        rec = dict(t)
        rec["schema_version"] = "1.0"
        rec["source"] = "simulator"
        teams.append(rec)
    out = ROOT / "data" / "raw" / "field_teams_master" / "field_teams_master.jsonl"
    write_jsonl(out, teams)
    print(f"{len(teams)} field teams likhe gaye -> {out}")


if __name__ == "__main__":
    main()