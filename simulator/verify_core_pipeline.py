"""End-to-end check: run the simulator on config_test.yaml and verify the output.

Run from the project root:  python -m simulator.verify_core_pipeline
Only data/test_run*, and state/test_sim*.db are created and deleted here.
Hooks: customers, usage, tower (in this order).
"""
import json
import re
import shutil
import sys
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

TOPICS = ("customer_events", "profile_events", "usage_events")
TOWER_TOPICS = ("tower_metrics_events", "network_events")
BILLING_TOPICS = ("recharge_events", "package_events")
ALL_TOPICS = TOPICS + TOWER_TOPICS + BILLING_TOPICS
PHONE = re.compile(r"03\d{2}-xxxx\d{2}")
CNIC = re.compile(r"xxxxx-xxxxx\d{2}-\d")
LEAK = re.compile(r"\d{4}-\d{7}|\d{5}-\d{7}-\d")
RESUME_AFTER = 7  # bands before the simulated stop


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

    def run(self, cfg, towers, stop_after=None):
        store = StateStore(self.db)
        packages = build_packages()
        hooks = [make_customer_hook(cfg, towers),
                 make_package_hook(cfg, towers, packages),
                 make_recharge_hook(cfg),
                 make_usage_hook(cfg, towers, packages=packages),
                 make_tower_hook(cfg, towers)]
        Simulator(cfg, store, self.out, hooks=hooks).run(stop_after=stop_after)
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


def main():
    cfg = load_config("config_test.yaml")
    towers = add_neighbors(build_towers(cfg))
    runs = {
        "main": Run(ROOT / "data" / "test_run", ROOT / "state" / "test_sim.db"),
        "repeat": Run(ROOT / "data" / "test_run_repeat",
                      ROOT / "state" / "test_sim_repeat.db"),
        "resume": Run(ROOT / "data" / "test_run_resume",
                      ROOT / "state" / "test_sim_resume.db"),
    }
    for r in runs.values():
        r.clean()

    # Sirf is script ke liye: kharabiyan zyada, taake 5 din ki chhoti run mein bhi
    # outages dikhein. Asli constants (towers/model.py) nahi badalte.
    model.SUDDEN_RATE = 0.01
    model.DIP_RATE = 0.01

    main_run, repeat, resume = runs["main"], runs["repeat"], runs["resume"]
    main_run.run(cfg, towers)
    repeat.run(cfg, towers)
    resume.run(cfg, towers, stop_after=RESUME_AFTER)
    resume.run(cfg, towers)  # new store and simulator = a restart

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

    # 3. Counts.
    exp_customers, exp_usage = expected_counts(cfg)
    store = StateStore(main_run.db)
    in_db = store.count_customers()
    next_no = int(store.get_meta("next_customer_no"))
    store.close()
    got = {t: len(main_run.events(t)) for t in TOPICS}
    ok = (in_db == exp_customers and next_no == exp_customers + 1
          and got["customer_events"] == exp_customers
          and got["profile_events"] == exp_customers
          and got["usage_events"] == exp_usage)
    check("3 ginti theek", ok,
          f"customers {in_db} (chahiye {exp_customers}), "
          f"customer/profile events {got['customer_events']}/{got['profile_events']}, "
          f"usage {got['usage_events']} (chahiye {exp_usage})")

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

        # 10. Billing events bane aur rakam/actions sahi.
    recharges = main_run.events("recharge_events")
    pkg_events = main_run.events("package_events")
    actions = {e["action"] for e in pkg_events}
    allowed = {"PURCHASE", "AUTO_RENEW", "AUTO_RENEW_OFF", "EXPIRE",
               "QUOTA_EXHAUSTED", "ADDON_PURCHASE"}
    recharge_ok = all(
        e["amount_pkr"] >= 100
        and e["channel"] in ("retailer", "easypaisa", "jazzcash", "app", "card")
        and abs((e["balance_after"] - e["balance_before"]) - e["amount_pkr"]) < 0.01
        and e["balance_before"] < 50.0
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
    
    print(f"\n{sum(results)}/{len(results)} checks pass")
    print(f"Files: {main_run.out}")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())