"""Bronze verify (sirf padhta hai): local JSONL vs Kafka vs S3 Bronze.
Chalane ka tareeqa: python -m ingestion.verify_ingestion [--skip-kafka]"""
import argparse
import gzip
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import boto3

TOPICS = [
    "customer_events", "profile_events", "usage_events", "recharge_events",
    "package_events", "offer_events", "lifecycle_events", "network_events",
    "tower_metrics_events",
]
MASTERS = ("tower_master", "packages_master", "field_teams_master")
ID_PAT = re.compile(rb'"event_id": "([0-9a-f]+)"')
ET_PAT = re.compile(rb'"event_time": "([^"]+)"')
DT_PAT = re.compile(r"/dt=(\d{4}-\d{2}-\d{2})/")
NULLABLE = {  # simulator/dirty/model.py se
    "customer_events": ("home_tower_id", "city", "acquisition_channel"),
    "profile_events": ("age_band", "gender", "language_pref", "arpu_band", "device_type"),
    "usage_events": ("tower_id", "data_mb_whatsapp", "data_mb_video", "calls_onnet_min", "dropped_calls"),
    "tower_metrics_events": ("signal_dbm", "load", "active_users", "dropped_calls"),
}


def scan_local(path, topic):
    total = bad = nulls = late = 0
    ids = set()
    max_t = b""
    fields = NULLABLE.get(topic)
    with open(path, "rb") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total += 1
            m = ID_PAT.search(line[:200])
            if not m:
                bad += 1
                continue
            ids.add(m.group(1))
            if topic == "usage_events":  # is topic ka event_time har band mein ek hi hota hai
                t = ET_PAT.search(line[:200])
                if t:
                    tv = t.group(1)
                    if tv < max_t:
                        late += 1
                    elif tv > max_t:
                        max_t = tv
            if fields:
                rec = json.loads(line)
                if any(rec.get(k) is None for k in fields):
                    nulls += 1
    return {"lines": total, "ids": ids, "bad": bad, "nulls": nulls, "late": late}


def scan_s3(s3, bucket, prefix, sample):
    total = bad = files = 0
    copies = Counter()
    samples = []
    pager = s3.get_paginator("list_objects_v2")
    for page in pager.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.endswith(".jsonl.gz"):
                continue
            files += 1
            lines = gzip.decompress(s3.get_object(Bucket=bucket, Key=key)["Body"].read()).splitlines()
            dt = DT_PAT.search(key)
            for line in lines:
                if not line.strip():
                    continue
                total += 1
                m = ID_PAT.search(line[:200])
                if m:
                    copies[m.group(1)] += 1
                else:
                    bad += 1
            for line in lines[:sample]:
                samples.append((dt.group(1) if dt else None, line))
    return {"lines": total, "copies": copies, "files": files, "bad": bad, "samples": samples}


def check_samples(samples):
    n = ingest = ev_date = pkt = utc = 0
    for dt, line in samples:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        n += 1
        ingest += "ingest_time" in rec
        ev_date += rec.get("event_date") == dt
        et = rec.get("event_time")
        if et:
            pkt += et[:10] == dt
            try:
                utc += datetime.fromisoformat(et).astimezone(timezone.utc).date().isoformat() == dt
            except ValueError:
                pass
    return {"n": n, "ingest_time": ingest, "dt_eq_event_date": ev_date, "dt_eq_pkt_date": pkt, "dt_eq_utc_date": utc}


def kafka_count(bootstrap, topic):
    from kafka import KafkaConsumer, TopicPartition
    c = KafkaConsumer(bootstrap_servers=bootstrap)
    try:
        parts = [TopicPartition(topic, p) for p in sorted(c.partitions_for_topic(topic) or [])]
        end, beg = c.end_offsets(parts), c.beginning_offsets(parts)
        return sum(end[p] - beg[p] for p in parts)
    finally:
        c.close()


def jsonl(path):
    with open(path, "rb") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def local_stats(raw):
    customers = {r["customer_id"] for r in jsonl(raw / "profile_events.jsonl")}
    churned = {r["customer_id"] for r in jsonl(raw / "lifecycle_events.jsonl") if r.get("to_status") == "CHURNED"}
    offer_all, offer_ctl = set(), set()
    for r in jsonl(raw / "offer_events.jsonl"):
        offer_all.add(r["customer_id"])
        if r.get("group") == "control":
            offer_ctl.add(r["customer_id"])
    outages = {r.get("outage_id") for r in jsonl(raw / "network_events.jsonl")}
    return {
        "customers": len(customers),
        "churn_rate": round(len(churned) / max(1, len(customers)), 4),
        "control_share": round(len(offer_ctl) / max(1, len(offer_all)), 4),
        "outages": len(outages),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", default="churnguard-data-bilawal")
    ap.add_argument("--region", default="ap-south-1")
    ap.add_argument("--bootstrap", default="localhost:9092")
    ap.add_argument("--raw-dir", default="data/raw")
    ap.add_argument("--prefix", default="raw/events")
    ap.add_argument("--sample", type=int, default=100)
    ap.add_argument("--skip-kafka", action="store_true")
    ap.add_argument("--out", default="state/ingestion_verify.json")
    a = ap.parse_args()

    raw = Path(a.raw_dir)
    s3 = boto3.client("s3", region_name=a.region)
    problems, report = [], {}
    print("topic                  local     kafka        s3  s3/local  copies>1  missing extra bad")
    for t in TOPICS:
        loc = scan_local(raw / f"{t}.jsonl", t)
        s = scan_s3(s3, a.bucket, f"{a.prefix}/{t}/", a.sample)
        s_ids = set(s["copies"])
        missing, extra = len(loc["ids"] - s_ids), len(s_ids - loc["ids"])
        kafka = None
        if not a.skip_kafka:
            try:
                kafka = kafka_count(a.bootstrap, t)
            except Exception as e:  # Kafka band ho to baqi check chalte rahen
                print("   kafka error:", e)
        multi = sum(1 for c in s["copies"].values() if c > 1)
        smp = check_samples(s["samples"])
        report[t] = {
            "local_lines": loc["lines"], "local_ids": len(loc["ids"]), "kafka": kafka,
            "s3_lines": s["lines"], "s3_ids": len(s_ids), "s3_files": s["files"],
            "copies_hist": dict(Counter(s["copies"].values())),
            "missing": missing, "extra": extra, "bad": loc["bad"] + s["bad"],
            "local_dup_pct": round(100 * (loc["lines"] - len(loc["ids"])) / max(1, loc["lines"]), 3),
            "local_null_pct": round(100 * loc["nulls"] / max(1, loc["lines"]), 3) if t in NULLABLE else None,
            "local_late_pct": round(100 * loc["late"] / max(1, loc["lines"]), 3) if t == "usage_events" else None,
            "samples": smp,
        }
        print(f"{t:22} {loc['lines']:9} {str(kafka):>9} {s['lines']:9} {s['lines'] / max(1, loc['lines']):8.2f} "
              f"{multi:9} {missing:7} {extra:5} {loc['bad'] + s['bad']:3}", flush=True)
        if missing or extra or loc["bad"] or s["bad"]:
            problems.append(f"{t}: missing={missing} extra={extra} bad={loc['bad'] + s['bad']}")
        if smp["n"] and smp["ingest_time"] < smp["n"]:
            problems.append(f"{t}: ingest_time kam hai ({smp['ingest_time']}/{smp['n']})")

    masters = {m: 0 for m in MASTERS}
    dlq = 0
    pager = s3.get_paginator("list_objects_v2")
    for page in pager.paginate(Bucket=a.bucket, Prefix="raw/masters/"):
        for o in page.get("Contents", []):
            for m in MASTERS:
                if f"/{m}/" in o["Key"] and o["Key"].endswith(".jsonl.gz"):
                    masters[m] += 1
    for page in pager.paginate(Bucket=a.bucket, Prefix="raw/dlq/"):
        dlq += len(page.get("Contents", []))
    if not all(masters.values()):
        problems.append(f"masters missing: {masters}")
    if dlq:
        problems.append(f"DLQ files: {dlq}")

    report["masters"], report["dlq_files"] = masters, dlq
    report["stats"] = local_stats(raw)
    print("\nmasters:", masters, " DLQ files:", dlq)
    print("stats:", report["stats"], "(target: churn ~0.265, control ~0.10)")
    for t in TOPICS:
        r = report[t]
        print(f"{t:22} dup%={r['local_dup_pct']} null%={r['local_null_pct']} late%={r['local_late_pct']} "
              f"copies={r['copies_hist']} samples={r['samples']}")

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("\nRESULT:", "PASS" if not problems else "FAIL")
    for p in problems:
        print(" -", p)


if __name__ == "__main__":
    main()