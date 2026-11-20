"""End-to-end check: run the simulator on config_test.yaml and verify the output.

Run from the project root:  python -m simulator.verify_core_pipeline
Only data/test_run*, and state/test_sim*.db are created and deleted here.
Hooks: customers, package, recharge, usage, tower, offer, lifecycle (in this order).
"""
import json
import re
import shutil
import sys
from collections import Counter
from datetime import datetime

from simulator.common import ROOT, load_config
from simulator.core.clock import BANDS_PER_DAY, SimClock
from simulator.core.engine import Simulator
from simulator.core.state_store import StateStore
from simulator.customers.hook import make_customer_hook, new_customers_in_band
from simulator.masters.towers import add_neighbors, build_towers
from simulator.towers import model
from simulator.towers.hook import make_tower_hook
from simulator.usage.hook import make_usage_hook
from simulator.billing.hooks import make_package_hook, make_recharge_hook
from simulator.masters.packages import build_packages
from simulator.lifecycle import model as lifecycle_model
from simulator.lifecycle.hooks import make_lifecycle_hook
from simulator.dirty.model import NULLABLE_FIELDS_BY_TOPIC
from simulator.dirty.processor import make_dirty_processor
from simulator.offers import model as offers_model
from simulator.offers.hooks import make_offer_hook


TOPICS = ("customer_events", "profile_events", "usage_events")
TOWER_TOPICS = ("tower_metrics_events", "network_events")
BILLING_TOPICS = ("recharge_events", "package_events")
LIFECYCLE_TOPICS = ("lifecycle_events",)
OFFER_TOPICS = ("offer_events",)
ALL_TOPICS = TOPICS + TOWER_TOPICS + BILLING_TOPICS + LIFECYCLE_TOPICS + OFFER_TOPICS
PHONE = re.compile(r"03\d{2}-xxxx\d{2}")
CNIC = re.compile(r"xxxxx-xxxxx\d{2}-\d")
LEAK = re.compile(r"\d{4}-\d{7}|\d{5}-\d{7}-\d")
RESUME_AFTER = 7  # bands before the simulated stop
VALID_TRANSITIONS = {
    ("ACTIVE", "SUSPENDED"), ("ACTIVE", "CHURNED"),
    ("SUSPENDED", "CHURNED"), ("SUSPENDED", "REACTIVATED"),
}


class Run:
    """One simulator run with its own output folder and state database."""

    def __init__(self, out_dir, db_path):
        self.out = out_dir
        self.db = db_path

    def clean(self):
        if self.out.exists():
            shutil.rmtree(self.out)
        for suffix in ("", "-wal", "-shm"):
            path = self.db.with_name(self.db.name + suffix)
            if path.exists():
                path.unlink()

    def run(self, cfg, towers, stop_after=None, post_hooks=None):
        store = StateStore(self.db)
        packages = build_packages()
        hooks = [make_customer_hook(cfg, towers),
                 make_package_hook(cfg, towers, packages),
                 make_recharge_hook(cfg),
                 make_usage_hook(cfg, towers, packages=packages),
                 make_tower_hook(cfg, towers),
                 make_offer_hook(cfg, packages),
                 make_lifecycle_hook(cfg)]
        Simulator(
            cfg, store, self.out, hooks=hooks, post_hooks=post_hooks
        ).run(stop_after=stop_after)
        store.close()

    def text(self, topic):
        path = self.out / f"{topic}.jsonl"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def events(self, topic):
        return [json.loads(line) for line in self.text(topic).splitlines()]


def expected_counts(cfg):
    """Customers and usage events the config should produce over the history."""
    customers = usage = 0
    for index in range(cfg["history_days"] * BANDS_PER_DAY):
        customers += new_customers_in_band(cfg, index)
        usage += customers
    return customers, usage


def band_of(cfg, event):
    """Event ka band index (event_time se)."""
    start = SimClock.from_config(cfg, index=0).band_start
    hours = (datetime.fromisoformat(event["event_time"]) - start).total_seconds() / 3600
    return round(hours / 6)


def quiet_bands(cfg, lifecycle):
    """{customer_id: set(band)} jin bands mein customer SUSPENDED ya CHURNED tha.

    Faisla Evening band ke aakhir mein hota hai, is liye us band ka usage ho chuka
    hota hai; usage agle band se band hoti hai aur agli tabdili ke band tak (shamil).
    """
    total = cfg["history_days"] * BANDS_PER_DAY
    by_customer = {}
    for e in lifecycle:
        by_customer.setdefault(e["customer_id"], []).append(
            (band_of(cfg, e), e["to_status"]))
    quiet = {}
    for cid, items in by_customer.items():
        items.sort()
        bands = set()
        for i, (band, status) in enumerate(items):
            if status in ("SUSPENDED", "CHURNED"):
                end = items[i + 1][0] if i + 1 < len(items) else total - 1
                bands.update(range(band + 1, end + 1))
        quiet[cid] = bands
    return quiet


def main():
    cfg = load_config("config_test.yaml")
    towers = add_neighbors(build_towers(cfg))
    runs = {
        "main": Run(ROOT / "data" / "test_run", ROOT / "state" / "test_sim.db"),
        "repeat": Run(ROOT / "data" / "test_run_repeat",
                      ROOT / "state" / "test_sim_repeat.db"),
        "resume": Run(ROOT / "data" / "test_run_resume",
                      ROOT / "state" / "test_sim_resume.db"),
        "dirty": Run(ROOT / "data" / "test_run_dirty",
                     ROOT / "state" / "test_sim_dirty.db"),
        "dirty_resume": Run(ROOT / "data" / "test_run_dirty_resume",
                            ROOT / "state" / "test_sim_dirty_resume.db"),
    }
    for r in runs.values():
        r.clean()

    # Sirf is script ke liye: kharabiyan zyada, taake 5 din ki chhoti run mein bhi
    # outages dikhein. Asli constants (towers/model.py) nahi badalte.
    model.SUDDEN_RATE = 0.01
    model.DIP_RATE = 0.01

    # Sirf is script ke liye: churn aur inactivity ki hadein chhoti, taake 5 din mein
    # bhi lifecycle events dikhein. Asli constants (lifecycle/model.py) nahi badalte.
    lifecycle_model.BASE_DAILY_CHURN = 0.05
    lifecycle_model.INACTIVE_SUSPEND_DAYS = 2
    lifecycle_model.INACTIVE_CHURN_DAYS = 4
    lifecycle_model.REACTIVATE_CHANCE_PER_DAY = 0.3

    main_run, repeat, resume = runs["main"], runs["repeat"], runs["resume"]
    dirty, dirty_resume = runs["dirty"], runs["dirty_resume"]
    main_run.run(cfg, towers)
    repeat.run(cfg, towers)
    resume.run(cfg, towers, stop_after=RESUME_AFTER)
    resume.run(cfg, towers)  # new store and simulator = a restart
    dirty.run(cfg, towers, post_hooks=[make_dirty_processor(cfg)])
    dirty_resume.run(
        cfg, towers, stop_after=RESUME_AFTER,
        post_hooks=[make_dirty_processor(cfg)],
    )
    dirty_resume.run(cfg, towers, post_hooks=[make_dirty_processor(cfg)])

    results = []

    def check(name, ok, detail=""):
        results.append(ok)
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))

    # 1. Same seed, same events.
    same = [t for t in ALL_TOPICS if main_run.text(t) == repeat.text(t)]
    check("1 same seed do baar, events same", len(same) == len(ALL_TOPICS),
          f"{len(same)}/{len(ALL_TOPICS)} topics bilkul same")

    # 2. Stop in the middle and resume.
    same = [t for t in ALL_TOPICS if main_run.text(t) == resume.text(t)]
    check(f"2 {RESUME_AFTER} band ke baad roka aur resume kiya, poori run jaisa",
          len(same) == len(ALL_TOPICS),
          f"{len(same)}/{len(ALL_TOPICS)} topics bilkul same")

    # 3. Counts (usage: SUSPENDED/CHURNED customers ke bands nikal kar).
    lifecycle = main_run.events("lifecycle_events")
    quiet = quiet_bands(cfg, lifecycle)
    skipped = sum(len(b) for b in quiet.values())
    exp_customers, exp_usage = expected_counts(cfg)
    store = StateStore(main_run.db)
    in_db = store.count_customers()
    next_no = int(store.get_meta("next_customer_no"))
    store.close()
    got = {t: len(main_run.events(t)) for t in TOPICS}
    ok = (in_db == exp_customers and next_no == exp_customers + 1
          and got["customer_events"] == exp_customers
          and got["profile_events"] == exp_customers
          and got["usage_events"] + skipped == exp_usage)
    check("3 ginti theek", ok,
          f"customers {in_db} (chahiye {exp_customers}), "
          f"customer/profile events {got['customer_events']}/{got['profile_events']}, "
          f"usage {got['usage_events']} + band-band {skipped} "
          f"(chahiye {exp_usage})")

    # 4. Common envelope on every event; event ids unique inside a topic.
    problems = 0
    for topic in ALL_TOPICS:
        events = main_run.events(topic)
        problems += len(events) - len({e["event_id"] for e in events})
        for e in events:
            if (not e.get("event_id") or not str(e.get("event_time", "")).endswith("+05:00")
                    or e.get("schema_version") != "1.0" or e.get("source") != "simulator"):
                problems += 1
    check("4 har event mein event_id, event_time (+05:00), schema_version, source",
          problems == 0, f"{problems} masle")

    # 5. Phone and CNIC are masked and nothing unmasked leaks.
    profiles = main_run.events("profile_events")
    bad = sum(
        not (PHONE.fullmatch(p["phone_masked"]) and CNIC.fullmatch(p["cnic_masked"]))
        for p in profiles
    )
    leaks = sum(bool(LEAK.search(main_run.text(t))) for t in TOPICS)
    check("5 phone aur CNIC masked", bad == 0 and leaks == 0,
          f"{bad} galat format, {leaks} topics mein asli number jaisa pattern")

    # 6. customer_events has no zone, usage points to known customers and towers.
    customers = main_run.events("customer_events")
    known_customers = {e["customer_id"] for e in customers}
    known_towers = {t["tower_id"] for t in towers}
    usage_ok = all(
        e["customer_id"] in known_customers and e["tower_id"] in known_towers
        for e in main_run.events("usage_events")
    )
    check("6 customer_events mein zone nahi, usage ke customer aur tower sahi",
          usage_ok and all("zone" not in e for e in customers))

    # 7. Tower ka har ghanta: ya metrics event, ya DOWN.
    start = SimClock.from_config(cfg, index=0).band_start
    total_hours = cfg["history_days"] * 24

    def hour_of(e):
        return round((datetime.fromisoformat(e["event_time"]) - start)
                     .total_seconds() / 3600)

    metrics = main_run.events("tower_metrics_events")
    network = main_run.events("network_events")
    starts = {e["outage_id"]: e for e in network if e["status"] == "START"}
    ends = {e["outage_id"]: e for e in network if e["status"] == "END"}
    down_hours = sum(
        (hour_of(ends[o]) if o in ends else total_hours) - hour_of(s)
        for o, s in starts.items()
    )
    expected = len(towers) * total_hours
    check("7 har tower ka har ghanta: metrics event ya DOWN",
          len(starts) > 0 and len(metrics) + down_hours == expected,
          f"{len(metrics)} metrics + {down_hours} DOWN ghante "
          f"(chahiye {expected}), {len(starts)} outages")

    # 8. Health ki qismein, START/END ka jor, chhupi state events mein nahi.
    pair_ok = (
        len(network) == len(starts) + len(ends)
        and all(o in starts for o in ends)
        and all(
            hour_of(ends[o]) > hour_of(starts[o])
            and ends[o]["tower_id"] == starts[o]["tower_id"]
            and ends[o]["severity"] == starts[o]["severity"]
            and ends[o]["cause"] == starts[o]["cause"]
            for o in ends
        )
    )
    health_ok = all(e["health"] in ("HEALTHY", "DEGRADED", "CRITICAL") for e in metrics)
    hidden = sum(("precursor_active" in e or "failure_at" in e)
                 for e in metrics + network)
    check("8 health sirf 3 qism, START/END jore sahi, chhupi state events mein nahi",
          pair_ok and health_ok and hidden == 0,
          f"jore {pair_ok}, health {health_ok}, chhupi fields {hidden}")

    # 9. Tower ka dropped_calls jama usage se nikle jama se kam ya barabar.
    usage_dropped = sum(e["dropped_calls"] for e in main_run.events("usage_events"))
    metrics_dropped = sum(e["dropped_calls"] for e in metrics)
    check("9 tower_metrics ka dropped_calls jama usage se kam ya barabar",
          metrics_dropped <= usage_dropped,
          f"metrics {metrics_dropped}, usage {usage_dropped}")

    # 10. Billing events bane aur rakam/actions sahi (reactivation recharge shamil).
    recharges = main_run.events("recharge_events")
    pkg_events = main_run.events("package_events")
    actions = {e["action"] for e in pkg_events}
    allowed = {"PURCHASE", "AUTO_RENEW", "AUTO_RENEW_OFF", "EXPIRE",
               "QUOTA_EXHAUSTED", "ADDON_PURCHASE"}
    reactivated = {(e["customer_id"], e["event_time"])
                   for e in lifecycle if e["to_status"] == "REACTIVATED"}
    recharge_ok = all(
        e["amount_pkr"] >= 100
        and e["channel"] in ("retailer", "easypaisa", "jazzcash", "app", "card")
        and abs((e["balance_after"] - e["balance_before"]) - e["amount_pkr"]) < 0.01
        and (e["balance_before"] < 50.0
             or (e["customer_id"], e["event_time"]) in reactivated)
        for e in recharges
    )
    package_ok = all(
        e["action"] in allowed and e["price_pkr"] >= 0 and e["balance_after"] >= 0
        for e in pkg_events
    )
    check("10 recharge aur package events bane, rakam aur actions sahi",
          len(recharges) > 0 and "PURCHASE" in actions and recharge_ok and package_ok,
          f"{len(recharges)} recharge, {len(pkg_events)} package events, "
          f"actions {sorted(actions)}")

    # 11. Usage mein package aur kharcha ki fields bhari hain.
    usage = main_run.events("usage_events")
    fields_ok = all(
        isinstance(e["active_package_ids"], list)
        and e["spend_from_package"] is not None and e["spend_from_package"] >= 0
        and e["spend_from_balance"] is not None and e["spend_from_balance"] >= 0
        for e in usage
    )
    with_pkg = sum(1 for e in usage if e["active_package_ids"])
    check("11 usage mein active_package_ids aur spend fields bhari",
          fields_ok and with_pkg > 0,
          f"{with_pkg}/{len(usage)} usage events mein active package")

    # 12. Balance kabhi 0 se neeche nahi, postpaid ka balance 0.
    store = StateStore(main_run.db)
    min_balance = store.conn.execute(
        "SELECT MIN(balance) FROM customer_state").fetchone()[0]
    post_bad = store.conn.execute(
        "SELECT COUNT(*) FROM customer_state "
        "WHERE plan_type='postpaid' AND balance != 0").fetchone()[0]
    store.close()
    check("12 balance 0 se neeche nahi, postpaid ka balance 0",
          min_balance >= 0 and post_bad == 0,
          f"sab se kam balance {min_balance}, postpaid jinka balance 0 nahi {post_bad}")

    # 13. lifecycle_events sahi: tabdiliyan, zanjeer, churn_reason sirf CHURNED par.
    reasons = set(lifecycle_model.CHURN_REASONS)
    counts = Counter(e["to_status"] for e in lifecycle)
    life_ok = all(
        (e["from_status"], e["to_status"]) in VALID_TRANSITIONS
        and e["customer_id"] in known_customers
        and (e["churn_reason"] in reasons if e["to_status"] == "CHURNED"
             else e["churn_reason"] is None)
        for e in lifecycle
    )
    by_customer = {}
    for e in lifecycle:
        by_customer.setdefault(e["customer_id"], []).append(e)
    chain_ok = True
    for items in by_customer.values():
        current = "ACTIVE"
        for e in sorted(items, key=lambda x: band_of(cfg, x)):
            if e["from_status"] != current:
                chain_ok = False
            current = "ACTIVE" if e["to_status"] == "REACTIVATED" else e["to_status"]
    check("13 lifecycle_events sahi (tabdiliyan, zanjeer, churn_reason sirf CHURNED par)",
          counts["CHURNED"] > 0 and life_ok and chain_ok,
          f"{dict(counts)}, tabdiliyan {life_ok}, zanjeer {chain_ok}")

    # 14. SUSPENDED ya CHURNED customer ki usage band rehti hai.
    bad_usage = sum(
        1 for e in usage if band_of(cfg, e) in quiet.get(e["customer_id"], ())
    )
    check("14 SUSPENDED/CHURNED customer ka usage event nahi", bad_usage == 0,
          f"{bad_usage} galat usage events, {skipped} band-band band")

    # 15. Offer events control/treatment, action, trigger, aur package links.
   # 15. Offer events control/treatment, action, trigger, aur package links.
    offers = main_run.events("offer_events")
    known_package_ids = {p["package_id"] for p in build_packages()}
    purchased_package_ids = {
        e["package_id"] for e in pkg_events
        if e["action"] == "PURCHASE" and e["package_id"] is not None
    }
    groups = {e["group"] for e in offers}
    offer_ok = (
        len(offers) > 0
        and {"treatment", "control"} <= groups
        and all(e["action"] in {"SENT", "ACCEPTED", "EXPIRED", "HELD"} for e in offers)
        and all(e["offer_type"] in set(offers_model.OFFER_TYPES) for e in offers)
        and all(e["trigger_rule"] == offers_model.TRIGGER_RULE[e["offer_type"]] for e in offers)
        and all(
            e["action"] == "HELD" and e["package_id"] is None
            for e in offers if e["group"] == "control"
        )
        and all(e["customer_id"] in known_customers for e in offers)
        and all(
            e["package_id"] is None or e["package_id"] in known_package_ids
            for e in offers
        )
        and all(
            e["package_id"] is None or e["package_id"] in purchased_package_ids
            for e in offers if e["action"] == "ACCEPTED"
        )
    )
    check("15 offer_events sahi (groups, actions, trigger_rule, package link)",
          offer_ok,
          f"{len(offers)} offers, groups {sorted(groups)}")

    # 16. Dirty data nulls, duplicates, late delivery aur resume mein deterministic.
    dirty_resume_same = sum(
        dirty.text(topic) == dirty_resume.text(topic) for topic in ALL_TOPICS
    )
    clean_by_topic = {
        topic: {e["event_id"]: e for e in main_run.events(topic)}
        for topic in ALL_TOPICS
    }
    null_count = 0
    envelope_null_count = 0
    dup_count = 0
    late_count = 0
    envelope_fields = ("event_id", "event_time", "schema_version", "source")
    for topic in ALL_TOPICS:
        seen_ids = set()
        max_seen_band = -1
        for event in dirty.events(topic):
            original = clean_by_topic[topic].get(event["event_id"], {})
            null_count += sum(
                field in event and event[field] is None
                and original.get(field) is not None
                for field in NULLABLE_FIELDS_BY_TOPIC.get(topic, ())
            )
            envelope_null_count += sum(
                field in event and event[field] is None
                for field in envelope_fields
            )
            event_id = event.get("event_id")
            if event_id in seen_ids:
                dup_count += 1
            else:
                seen_ids.add(event_id)
            event_band = band_of(cfg, event)
            if event_band < max_seen_band:
                late_count += 1
            max_seen_band = max(max_seen_band, event_band)

    dirty_ok = (
        dirty_resume_same == len(ALL_TOPICS)
        and null_count > 0
        and envelope_null_count == 0
        and dup_count > 0
        and late_count > 0
    )
    check("16 dirty data nulls, duplicates, late delivery aur resume sahi",
          dirty_ok,
          f"nulls {null_count}, dups {dup_count}, late {late_count}, "
          f"resume {dirty_resume_same}/{len(ALL_TOPICS)}")

    print(f"\n{sum(results)}/{len(results)} checks pass")
    print(f"Files: {main_run.out}")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())