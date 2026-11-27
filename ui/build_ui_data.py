"""Build small UI files (data/ui/) from Silver.
Run (Windows PowerShell, venv on, project root): python -m ui.build_ui_data [--silver data/silver]
fact_usage is aggregated with pyarrow, never loaded fully into pandas."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import pyarrow.dataset as ds

from ui.common import UI_DIR, nearest_team, to_pkt


def rd(silver, table, cols=None):
    return pd.read_parquet(silver / table, columns=cols)


def save(df, name):
    df.to_parquet(UI_DIR / f"{name}.parquet", index=False)
    print(f"{name:16s} rows={len(df):,}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--silver")
    a = ap.parse_args()
    silver = Path(a.silver) if a.silver else next(
        (Path(p) for p in ("data/silver", "data/silver_old") if (Path(p) / "dim_tower").exists()), None)
    if silver is None:
        raise SystemExit("Silver folder not found, pass --silver")
    UI_DIR.mkdir(parents=True, exist_ok=True)
    print("silver:", silver)

    tw = rd(silver, "dim_tower", ["tower_id", "city", "zone", "lat", "lon", "tower_type",
                                  "capacity_users", "neighbor_tower_ids"])
    tm = rd(silver, "dim_field_team", ["team_id", "city", "zone", "base_lat", "base_lon"])
    cu = rd(silver, "customers_current", ["customer_id", "city", "segment", "arpu_band", "device_type",
                                          "age_band", "home_tower_id", "signup_date", "status",
                                          "churn_date", "churn_reason"])
    cu["signup_date"] = pd.to_datetime(cu["signup_date"])
    cu["churn_date"] = pd.to_datetime(cu["churn_date"])
    cu["city"] = cu["city"].fillna("Unknown")
    sh = rd(silver, "customer_status_history", ["customer_id", "status", "valid_from", "valid_to"])
    for c in ("valid_from", "valid_to"):
        sh[c] = pd.to_datetime(sh[c])

    of = rd(silver, "offers", ["offer_id", "customer_id", "offer_type", "group", "final_action"])
    save(of.groupby(["group", "offer_type", "final_action"]).size().reset_index(name="n"), "offers_summary")
    cu["offer_group"] = cu["customer_id"].map(of.drop_duplicates("customer_id").set_index("customer_id")["group"])
    g = cu.groupby("offer_group").agg(customers=("customer_id", "size"),
                                      churned=("status", lambda s: int((s == "CHURNED").sum())))
    save(g.reset_index(), "group_churn")

    ou = rd(silver, "outages")
    ou["start_time"], ou["end_time"] = to_pkt(ou["start_time"]), to_pkt(ou["end_time"])
    ou = ou.merge(tw[["tower_id", "city", "zone", "lat", "lon"]], on="tower_id", how="left")
    ou["customers_home"] = ou["tower_id"].map(cu.groupby("home_tower_id").size()).fillna(0).astype(int)
    teams = tm.to_dict("records")
    near = [nearest_team(r.city, r.lat, r.lon, teams) for r in ou.itertuples()]
    ou["nearest_team_id"], ou["team_km"] = [n[0] for n in near], [n[1] for n in near]

    mt = rd(silver, "fact_tower_metrics", ["tower_id", "event_time", "health", "signal_dbm", "load",
                                            "active_users", "dropped_calls"])
    mt["ts"] = to_pkt(mt["event_time"]).dt.floor("h")
    mt = mt.drop(columns="event_time").sort_values("ts").reset_index(drop=True)
    per_tower = dict(tuple(mt.groupby("tower_id")))
    parts = []
    for r in ou.itertuples():
        d = per_tower.get(r.tower_id)
        if d is None:
            continue
        w = d[(d.ts >= r.start_time - pd.Timedelta(hours=6)) & (d.ts < r.start_time)].copy()
        w["outage_id"] = r.outage_id
        parts.append(w)
    ctx = pd.concat(parts) if parts else mt.head(0).assign(outage_id="")

    t = ds.dataset(str(silver / "fact_usage"), format="parquet", partitioning="hive").to_table(
        columns=["event_date", "total_data_mb", "total_call_min", "total_spend"])
    ag = t.group_by("event_date").aggregate([("total_spend", "count"), ("total_data_mb", "sum"),
                                             ("total_call_min", "sum"), ("total_spend", "sum")]).to_pandas()
    daily = pd.DataFrame({"event_date": pd.to_datetime(ag["event_date"].astype(str)),
                          "events": ag["total_spend_count"], "data_gb": ag["total_data_mb_sum"] / 1024,
                          "call_min": ag["total_call_min_sum"], "spend": ag["total_spend_sum"]}
                         ).sort_values("event_date")

    rows = []
    for f in sorted((silver / "_dq").glob("*.json")):
        j = json.loads(f.read_text(encoding="utf-8"))
        rows.append({"table": f.stem, "rows_out": j.get("rows_out"), "status": j.get("status"),
                     "dedup_pct": j.get("dedup_pct"), "rejects": j.get("rejects")})

    for name, df in [("towers", tw), ("teams", tm), ("customers", cu), ("status_history", sh),
                     ("outages", ou), ("tower_metrics", mt), ("alert_context", ctx),
                     ("usage_daily", daily), ("pipeline", pd.DataFrame(rows))]:
        save(df, name)
    d0, d1 = daily.event_date.min(), daily.event_date.max()
    (UI_DIR / "meta.json").write_text(json.dumps(
        {"sim_start": str(d0.date()), "days": int((d1 - d0).days + 1), "silver": str(silver)}), encoding="utf-8")
    print("DONE ->", UI_DIR)


if __name__ == "__main__":
    main()