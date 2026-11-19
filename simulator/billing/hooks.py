"""Engine hooks for package lifecycle and prepaid recharges."""
from simulator.billing.engine import (
    AUTO_RENEW_ON_CHANCE,
    PACKAGE_BUY_CHANCE,
    RECHARGE_THRESHOLD_PKR,
    choose_package,
    choose_recharge,
    has_no_package_habit,
    init_active_package_row,
)
from simulator.billing.events import (
    build_package_event,
    build_recharge_event,
    subscription_id,
)
from simulator.common import make_rng
from simulator.usage.generator import customer_no


def _tower_city_map(towers):
    return {t["tower_id"]: t["city"] for t in towers}


def make_package_hook(cfg, towers, packages):
    """Return package hook(ctx): handles expiry/auto-renew and new purchases."""
    tower_city = _tower_city_map(towers)
    pkg_lookup = {p["package_id"]: p for p in packages}

    def hook(ctx):
        events = []
        customers = ctx.store.conn.execute(
            "SELECT * FROM customer_state WHERE status='ACTIVE' ORDER BY customer_id"
        ).fetchall()
        cust_map = {r["customer_id"]: dict(r) for r in customers}

        # 1. Process expiries and auto-renewals for all active packages
        all_pkgs = ctx.store.all_active_packages()
        has_active_pkg = set()

        for prow in all_pkgs:
            cid = prow["customer_id"]
            cust = cust_map.get(cid)
            if not cust:
                continue
            if int(prow["expires_at"]) > ctx.clock.index:
                has_active_pkg.add(cid)
                continue

            pdef = pkg_lookup.get(prow["package_id"])
            if not pdef:
                ctx.store.delete_active_package(cid, prow["package_id"])
                continue

            is_prepaid = cust["plan_type"] == "prepaid"
            price = float(pdef["price_pkr"])
            balance = float(cust["balance"])

            if int(prow["auto_renew"]) == 1:
                can_afford = (not is_prepaid) or (balance >= price)
                if can_afford:
                    if is_prepaid:
                        balance = round(balance - price, 2)
                        cust["balance"] = balance
                        ctx.store.upsert_customers([cust])
                    refilled = init_active_package_row(
                        cid, prow["subscription_id"], pdef, ctx.clock.index, True
                    )
                    ctx.store.upsert_active_package(refilled)
                    has_active_pkg.add(cid)
                    events.append((
                        "package_events",
                        build_package_event(
                            cfg, cid, ctx.clock, prow["subscription_id"],
                            "AUTO_RENEW", pdef, balance, seq=1,
                        ),
                    ))
                else:
                    ctx.store.delete_active_package(cid, prow["package_id"])
                    events.append((
                        "package_events",
                        build_package_event(
                            cfg, cid, ctx.clock, prow["subscription_id"],
                            "AUTO_RENEW_OFF", pdef, balance, seq=1,
                        ),
                    ))
                    events.append((
                        "package_events",
                        build_package_event(
                            cfg, cid, ctx.clock, prow["subscription_id"],
                            "EXPIRE", pdef, balance, seq=2,
                        ),
                    ))
            else:
                ctx.store.delete_active_package(cid, prow["package_id"])
                events.append((
                    "package_events",
                    build_package_event(
                        cfg, cid, ctx.clock, prow["subscription_id"],
                        "EXPIRE", pdef, balance, seq=1,
                    ),
                ))

        # 2. New package purchase for active customers with no active package
        for cid, cust in cust_map.items():
            if cid in has_active_pkg:
                continue
            n = customer_no(cfg, cid)
            if has_no_package_habit(cfg, n):
                continue

            city = tower_city.get(cust["home_tower_id"], "Other_cities")
            is_prepaid = cust["plan_type"] == "prepaid"
            balance = float(cust["balance"])
            pkg = choose_package(
                cfg, n, cust["plan_type"], city, packages,
                max_price=balance if is_prepaid else None,
            )
            if not pkg:
                continue

            price = float(pkg["price_pkr"])
            if is_prepaid and balance < price:
                continue

            rng = make_rng(cfg["seed"], "pkg_buy", n, ctx.clock.index)
            if rng.random() >= PACKAGE_BUY_CHANCE:
                continue

            auto_renew = (
                bool(pkg.get("auto_renew_allowed", True))
                and (rng.random() < AUTO_RENEW_ON_CHANCE)
            )
            if is_prepaid:
                balance = round(balance - price, 2)
                cust["balance"] = balance
                ctx.store.upsert_customers([cust])

            sub_id = subscription_id(cid, ctx.clock.index, pkg["package_id"])
            new_row = init_active_package_row(
                cid, sub_id, pkg, ctx.clock.index, auto_renew
            )
            ctx.store.upsert_active_package(new_row)
            events.append((
                "package_events",
                build_package_event(
                    cfg, cid, ctx.clock, sub_id, "PURCHASE", pkg, balance, seq=0,
                ),
            ))

        return events

    return hook


def make_recharge_hook(cfg):
    """Return recharge hook(ctx): recharges prepaid customers with balance < 50 PKR."""
    def hook(ctx):
        events = []
        rows = ctx.store.conn.execute(
            "SELECT * FROM customer_state "
            "WHERE status='ACTIVE' AND plan_type='prepaid' AND balance < ? "
            "ORDER BY customer_id",
            (RECHARGE_THRESHOLD_PKR,),
        ).fetchall()
        updated_customers = []
        for r in rows:
            cust = dict(r)
            cid = cust["customer_id"]
            n = customer_no(cfg, cid)
            bal_before = float(cust["balance"])
            amount, channel = choose_recharge(cfg, n, "prepaid", ctx.clock.index)
            bal_after = round(bal_before + amount, 2)
            cust["balance"] = bal_after
            updated_customers.append(cust)
            events.append((
                "recharge_events",
                build_recharge_event(
                    cfg, cid, ctx.clock, amount, channel, bal_before, bal_after,
                ),
            ))
        if updated_customers:
            ctx.store.upsert_customers(updated_customers)
        return events

    return hook