"""Usage hook: one usage_events record per ACTIVE customer in every band."""
from simulator.billing.engine import apply_usage_billing
from simulator.billing.events import build_package_event
from simulator.usage.generator import build_usage_event, neighbor_map
from simulator.lifecycle.engine import scale_usage_event
from simulator.common import make_rng
from simulator.lifecycle.model import AT_RISK_USAGE_FACTOR, DORMANT_SHARE
from simulator.usage.generator import customer_no

_DORMANT_CACHE: dict = {}


def _is_dormant(cfg, cid):
    key = (cfg["seed"], cid)
    v = _DORMANT_CACHE.get(key)
    if v is None:
        rng = make_rng(cfg["seed"], "dormant", customer_no(cfg, cid))
        v = float(rng.random()) < DORMANT_SHARE
        _DORMANT_CACHE[key] = v
    return v

def make_usage_hook(cfg, towers, packages=None):
    """Return a hook(ctx) for the engine.

    `towers` must come from add_neighbors(build_towers(cfg)), so that every
    tower has neighbor_tower_ids. Tower health comes from tower_state (the
    previous band's end state), so the tower hook must run AFTER this hook.
    """
    if any("neighbor_tower_ids" not in t for t in towers):
        raise ValueError(
            "towers mein neighbor_tower_ids nahi hain; add_neighbors(...) wali list do"
        )
    neighbors = neighbor_map(towers)
    pkg_lookup = {p["package_id"]: p for p in (packages or [])}

    def hook(ctx):
        health = {r["tower_id"]: r["health"] for r in ctx.store.all_towers()}
        rows = ctx.store.conn.execute(
            "SELECT * FROM customer_state WHERE status='ACTIVE' ORDER BY customer_id"
        ).fetchall()

        pkgs_by_cust = {}
        for prow in ctx.store.all_active_packages():
            pkgs_by_cust.setdefault(prow["customer_id"], []).append(prow)

        events = []
        updated_customers = []

        for r in rows:
            cust = dict(r)
            cid = cust["customer_id"]
            ev = build_usage_event(
                cfg, cid, cust["home_tower_id"], neighbors,
                ctx.clock, tower_health=health,
            )
            if cust["at_risk"]:
                if cust["plan_type"] == "prepaid" and _is_dormant(cfg, cid):
                    scale_usage_event(ev, 0.0)
                    ev["dropped_calls"] = 0
                else:
                    scale_usage_event(ev, AT_RISK_USAGE_FACTOR)
                

            active_pkgs = pkgs_by_cust.get(cid, [])
            old_pkg_ids = {p["package_id"] for p in active_pkgs}

            new_bal, rem_pkgs, exhausted_subs, addon_subs = apply_usage_billing(
                cfg, cust, active_pkgs, pkg_lookup, ev,
                ctx.clock.band, ctx.clock.index,
            )

            events.append(("usage_events", ev))

            # Emit QUOTA_EXHAUSTED and ADDON_PURCHASE events if triggered
            for seq_idx, (ex_row, pdef) in enumerate(exhausted_subs, start=1):
                events.append((
                    "package_events",
                    build_package_event(
                        cfg, cid, ctx.clock, ex_row["subscription_id"],
                        "QUOTA_EXHAUSTED", pdef, new_bal, seq=10 + seq_idx,
                    ),
                ))
            for seq_idx, (ad_row, pdef) in enumerate(addon_subs, start=1):
                events.append((
                    "package_events",
                    build_package_event(
                        cfg, cid, ctx.clock, ad_row["subscription_id"],
                        "ADDON_PURCHASE", pdef, new_bal, seq=20 + seq_idx,
                    ),
                ))

            # Sync active_packages table if changed
            new_pkg_ids = {p["package_id"] for p in rem_pkgs}
            for removed_id in old_pkg_ids - new_pkg_ids:
                ctx.store.delete_active_package(cid, removed_id)
            for prow in rem_pkgs:
                ctx.store.upsert_active_package(prow)

            if round(float(cust["balance"]), 2) != round(new_bal, 2):
                cust["balance"] = new_bal
                updated_customers.append(cust)

        if updated_customers:
            ctx.store.upsert_customers(updated_customers)

        return events

    return hook