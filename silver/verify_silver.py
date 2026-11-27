from __future__ import annotations

import json
import sys

from pyspark.sql import functions as F

from silver.settings import load_silver_settings
from silver.spark_session import build_spark

EXPECTED_ROWS = {
    "dim_tower": 110, "dim_package": 29, "dim_field_team": 25, "tower_neighbors": 330,
    "customer_events": 29_512, "profile_events": 29_515,
    "dim_customer": 29_515, "customers_current": 29_515,
    "fact_usage": 14_990_217, "fact_recharge": 281_314,
    "fact_package_events": 828_631, "fact_offer_events": 680_139,
    "fact_lifecycle_events": 8_295, "customer_status_history": 29_515 + 8_295,
    "fact_network_events": 292, "outages": 146,
    "fact_tower_metrics": 474_035, "tower_hourly_grid": 475_200,
}


def main() -> int:
    cfg = load_silver_settings()
    spark = build_spark("verify-silver", cfg)
    sd = cfg.silver_dir
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))
        print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")

    def rd(t):
        return spark.read.parquet(str(sd / t))

    try:
        # 1. row counts
        for t, exp in EXPECTED_ROWS.items():
            n = rd(t).count()
            check(f"rows {t}", n == exp, f"got={n:,} expected={exp:,}")

        # 2. DQ reports
        bad = []
        for f in sorted(cfg.dq_dir.glob("*.json")):
            if json.loads(f.read_text(encoding="utf-8")).get("status") != "PASS":
                bad.append(f.stem)
        check("dq reports all PASS", not bad, f"failing={bad}")

        # 3. rejects
        rej = list(cfg.rejects_dir.rglob("*.parquet")) if cfg.rejects_dir.exists() else []
        check("no rejects", not rej, f"reject_files={len(rej)}")

        # 4. usage partitions
        parts = len(list((sd / "fact_usage").glob("event_date=*")))
        check("fact_usage 180 partitions", parts == 180, f"got={parts}")

        # 5. usage event_id unique
        u = rd("fact_usage")
        check("fact_usage event_id unique", u.count() == u.select("event_id").distinct().count())

        # 6. status history
        dim = rd("dim_customer")
        hist = rd("customer_status_history")
        check("dim_customer customer_id unique", dim.count() == dim.select("customer_id").distinct().count())
        cur = hist.where("is_current").groupBy("customer_id").count()
        check("one is_current per customer",
              cur.where("count != 1").count() == 0 and cur.count() == dim.count())

        # 7. churned count matches lifecycle
        cc = rd("customers_current")
        n_cur = cc.where("status = 'CHURNED'").count()
        n_lc = rd("fact_lifecycle_events").where("to_status = 'CHURNED'").select("customer_id").distinct().count()
        check("churned customers match lifecycle", n_cur == n_lc, f"current={n_cur} lifecycle={n_lc}")

        # 8. subscriptions / offers one row per id
        pk = rd("fact_package_events").select("subscription_id").distinct().count()
        check("subscriptions one per id", rd("subscriptions").count() == pk, f"distinct={pk}")
        of = rd("fact_offer_events").select("offer_id").distinct().count()
        check("offers one per id", rd("offers").count() == of, f"distinct={of}")

        # 9. leakage: hidden truth fact tables mein nahi
        leak = {"churn_reason", "at_risk", "inactivity_days"} & set(u.columns)
        check("no leakage cols in fact_usage", not leak, f"found={sorted(leak)}")

        # 10. info only (PASS/FAIL nahi)
        g = rd("tower_hourly_grid")
        print("INFO grid: no_reading=%d in_outage=%d no_reading_not_outage=%d reading_in_outage=%d" % (
            g.where("not has_reading").count(), g.where("in_outage").count(),
            g.where("not has_reading and not in_outage").count(), g.where("has_reading and in_outage").count()))
        print("INFO orphans fact_usage: customer_unknown=%d tower_unknown=%d" % (
            u.where("customer_known = false").count(), u.where("tower_known = false").count()))
    finally:
        spark.stop()

    failed = [n for n, ok, _ in results if not ok]
    print("RESULT", "PASS" if not failed else f"FAIL ({len(failed)} checks)")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())