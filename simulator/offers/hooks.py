"""Offer hook: daily usage/recharge tracking, offer acceptance/expiry, and new offers.

Har band: usage_events se offer_daily jama hota hai aur recharge_events se OPEN
RECHARGE_BONUS offers ka recharge_total barhta hai.
Evening band ke aakhir mein: pehle OPEN offers accept/expire hote hain, phir ACTIVE
customers ke liye naye offers evaluate hote hain. Hooks ki tartib mein tower_hook ke
baad aur lifecycle_hook se pehle chalta hai.
"""
from datetime import date, timedelta

from simulator.billing.engine import arpu_band_for, init_active_package_row
from simulator.billing.events import build_package_event, subscription_id
from simulator.core.clock import BANDS_PER_DAY
from simulator.customers.events import device_type_for
from simulator.offers import engine as e
from simulator.offers import model as m
from simulator.offers.events import build_offer_event, make_offer_id
from simulator.usage.generator import customer_no

EVENING = BANDS_PER_DAY - 1
OFFER_PKG_SEQ_BASE = 100


def _today_date(clock):
    return date.fromisoformat(clock.event_date)


def _record_band_activity(ctx):
    """Is band ke usage aur recharge events ko offer state mein jama karna."""
    day_str = ctx.clock.event_date
    for ev in ctx.band_events_for("usage_events"):
        data_mb = (
            float(ev.get("data_mb_whatsapp") or 0.0)
            + float(ev.get("data_mb_social") or 0.0)
            + float(ev.get("data_mb_video") or 0.0)
            + float(ev.get("data_mb_browsing") or 0.0)
            + float(ev.get("data_mb_other") or 0.0)
        )
        call_min = float(ev.get("calls_offnet_min") or 0.0) + float(ev.get("calls_intl_min") or 0.0)
        ctx.store.add_offer_daily(ev["customer_id"], day_str, data_mb, call_min)

    recharge_by_cust = {}
    for ev in ctx.band_events_for("recharge_events"):
        cid = ev["customer_id"]
        recharge_by_cust[cid] = recharge_by_cust.get(cid, 0.0) + float(ev["amount_pkr"])

    if recharge_by_cust:
        for row in ctx.store.open_offers():
            if row["offer_type"] == "RECHARGE_BONUS" and row["customer_id"] in recharge_by_cust:
                new_total = round(float(row["recharge_total"]) + recharge_by_cust[row["customer_id"]], 2)
                ctx.store.update_offer(row["offer_id"], recharge_total=new_total)


def _grant_package(cfg, ctx, cust, pdef, seq):
    """Customer ko package row dena aur package_events emit karna."""
    cid = cust["customer_id"]
    pkg_id = pdef["package_id"]
    sub_id = subscription_id(cid, ctx.clock.index, pkg_id)
    prow = init_active_package_row(
        cid, sub_id, pdef, ctx.clock.index, m.OFFER_PACKAGE_AUTO_RENEW
    )
    ctx.store.upsert_active_package(prow)
    return ("package_events", build_package_event(
        cfg, cid, ctx.clock, sub_id, "PURCHASE", pdef, float(cust["balance"]), seq=seq,
    ))


def _process_open_offers(cfg, ctx, packages, pkg_lookup, cust_map, arpu_cache, device_cache):
    """Evening ke aakhir mein OPEN offers ko accept ya expire karna."""
    today_str = ctx.clock.event_date
    events = []
    seq = OFFER_PKG_SEQ_BASE

    for row in ctx.store.open_offers():
        oid = row["offer_id"]
        cid = row["customer_id"]
        otype = row["offer_type"]
        cust = cust_map.get(cid)
        active_ids = {p["package_id"] for p in ctx.store.get_active_packages(cid)} if cust else set()

        if cust and cust["status"] == "ACTIVE":
            n = customer_no(cfg, cid)
            band = arpu_cache.get(cid)
            if band is None:
                band = arpu_cache[cid] = arpu_band_for(cfg, n, cust["plan_type"])

            if otype == "RECHARGE_BONUS":
                if e.recharge_target_reached(float(row["recharge_total"]), band):
                    dev = device_cache.get(cid)
                    if dev is None:
                        dev = device_cache[cid] = device_type_for(cfg, n)
                    rew = e.reward_package(packages, band, dev, active_ids)
                    rew_id = None
                    if rew is not None:
                        free_pkg = e.discounted_package(rew, 1.0)
                        rew_id = free_pkg["package_id"]
                        events.append(_grant_package(cfg, ctx, cust, free_pkg, seq))
                        seq += 1
                    ctx.store.update_offer(oid, status="ACCEPTED", closed_date=today_str)
                    events.append(("offer_events", build_offer_event(
                        cfg, cid, ctx.clock, oid, otype, "ACCEPTED", "treatment",
                        m.TRIGGER_RULE[otype], campaign_name=row["campaign_name"],
                        package_id=rew_id, discount_pct=row["discount_pct"],
                    )))
                    continue
            else:
                plan_date = row["planned_accept_date"]
                pdef = pkg_lookup.get(row["package_id"])
                if plan_date and today_str >= plan_date and pdef and pdef["package_id"] not in active_ids:
                    disc_pkg = e.discounted_package(pdef, float(row["discount_pct"] or 0.0))
                    price = float(disc_pkg["price_pkr"])
                    is_prepaid = cust["plan_type"] == "prepaid"
                    bal = float(cust["balance"])
                    if (not is_prepaid) or (bal >= price):
                        if is_prepaid:
                            bal = round(bal - price, 2)
                            cust["balance"] = bal
                            ctx.store.conn.execute(
                                "UPDATE customer_state SET balance=? WHERE customer_id=?",
                                (bal, cid),
                            )
                        events.append(_grant_package(cfg, ctx, cust, disc_pkg, seq))
                        seq += 1
                        ctx.store.update_offer(oid, status="ACCEPTED", closed_date=today_str)
                        events.append(("offer_events", build_offer_event(
                            cfg, cid, ctx.clock, oid, otype, "ACCEPTED", "treatment",
                            m.TRIGGER_RULE[otype], campaign_name=row["campaign_name"],
                            package_id=disc_pkg["package_id"], discount_pct=row["discount_pct"],
                        )))
                        continue

        if today_str > row["window_end_date"]:
            ctx.store.update_offer(oid, status="EXPIRED", closed_date=today_str)
            events.append(("offer_events", build_offer_event(
                cfg, cid, ctx.clock, oid, otype, "EXPIRED", "treatment",
                m.TRIGGER_RULE[otype], campaign_name=row["campaign_name"],
                package_id=row["package_id"], discount_pct=row["discount_pct"],
            )))

    return events


def _evaluate_new_offers(cfg, ctx, packages, cust_map, arpu_cache, device_cache):
    """Evening ke aakhir mein ACTIVE customers ko naye offers bhejna."""
    today = _today_date(ctx.clock)
    today_str = ctx.clock.event_date
    since_30 = (today - timedelta(days=30)).isoformat()
    since_28 = (today - timedelta(days=28)).isoformat()
    seed = cfg["seed"]

    open_custs = {r["customer_id"] for r in ctx.store.open_offers()}
    ev_due = e.events_due(today)
    ev_map = {ot: (camp, edate) for ot, camp, edate in ev_due}
    is_wknd = e.weekend_due(today)

    events = []
    for cid, cust in cust_map.items():
        if cust["status"] != "ACTIVE" or cid in open_custs:
            continue

        sent_dates = [date.fromisoformat(d) for d in ctx.store.recent_offer_dates(cid, since_30)]
        if not e.can_send(sent_dates, today):
            continue

        n = customer_no(cfg, cid)
        dev = device_cache.get(cid)
        if dev is None:
            dev = device_cache[cid] = device_type_for(cfg, n)
        is_smart = dev in ("smartphone_android", "smartphone_ios")

        due = []
        if "EVENT_OFFER" in ev_map:
            due.append("EVENT_OFFER")
        if "CRICKET_PACK" in ev_map and is_smart:
            due.append("CRICKET_PACK")
        if e.recharge_offer_due(cust["plan_type"], float(cust["balance"])):
            due.append("RECHARGE_BONUS")

        daily_rows = ctx.store.get_offer_daily(cid, since_28)
        if daily_rows:
            day_idx = ctx.clock.day
            data_by_day = {
                day_idx - (today - date.fromisoformat(r["day"])).days: float(r["data_mb"])
                for r in daily_rows
            }
            call_by_day = {
                day_idx - (today - date.fromisoformat(r["day"])).days: float(r["call_min"])
                for r in daily_rows
            }
            data_rise = e.weekly_rise(data_by_day, day_idx)
            if is_smart and data_rise is not None and data_rise >= m.DATA_BOOST_RISE_RATIO:
                due.append("DATA_BOOST")
            call_rise = e.weekly_rise(call_by_day, day_idx)
            if call_rise is not None and call_rise >= m.CALL_BUNDLE_RISE_RATIO:
                due.append("CALL_BUNDLE")

        if is_wknd:
            due.append("WEEKEND_SPECIAL")

        chosen = e.pick_offer(due)
        if chosen is None:
            continue

        band = arpu_cache.get(cid)
        if band is None:
            band = arpu_cache[cid] = arpu_band_for(cfg, n, cust["plan_type"])

        camp_name = ev_map[chosen][0] if chosen in ev_map else None
        ev_date = ev_map[chosen][1] if chosen in ev_map else None
        end_d = e.window_end(chosen, today, event_date=ev_date)
        oid = make_offer_id(cid, ctx.clock.index, chosen)

        if e.is_control(seed, cid):
            ctx.store.insert_offer({
                "offer_id": oid,
                "customer_id": cid,
                "offer_type": chosen,
                "grp": "control",
                "campaign_name": camp_name,
                "sent_date": today_str,
                "window_end_date": end_d.isoformat(),
                "status": "HELD",
                "closed_date": today_str,
            })
            events.append(("offer_events", build_offer_event(
                cfg, cid, ctx.clock, oid, chosen, "HELD", "control",
                m.TRIGGER_RULE[chosen], campaign_name=camp_name,
            )))
            continue

        pkg_id = None
        disc_pct = None
        plan_acc_str = None
        rech_target = None

        if chosen == "RECHARGE_BONUS":
            rech_target = float(m.RECHARGE_TARGET_BY_BAND[band])
        else:
            active_ids = {p["package_id"] for p in ctx.store.get_active_packages(cid)}
            pdef = e.choose_offer_package(seed, cid, chosen, packages, band, active_ids)
            if pdef is None:
                continue
            pkg_id = pdef["package_id"]
            disc_pct = float(m.DISCOUNT_PCT_BY_OFFER[chosen])
            plan_acc = e.planned_accept_date(seed, oid, chosen, today, end_d)
            plan_acc_str = plan_acc.isoformat() if plan_acc is not None else None

        ctx.store.insert_offer({
            "offer_id": oid,
            "customer_id": cid,
            "offer_type": chosen,
            "grp": "treatment",
            "package_id": pkg_id,
            "campaign_name": camp_name,
            "discount_pct": disc_pct,
            "sent_date": today_str,
            "window_end_date": end_d.isoformat(),
            "status": "OPEN",
            "planned_accept_date": plan_acc_str,
            "recharge_target": rech_target,
            "recharge_total": 0.0,
        })
        events.append(("offer_events", build_offer_event(
            cfg, cid, ctx.clock, oid, chosen, "SENT", "treatment",
            m.TRIGGER_RULE[chosen], campaign_name=camp_name,
            package_id=pkg_id, discount_pct=disc_pct,
        )))

    ctx.store.prune_offer_daily((today - timedelta(days=30)).isoformat())
    return events


def make_offer_hook(cfg, packages):
    """Return offer hook(ctx). tower_hook ke baad aur lifecycle_hook se pehle rakhna."""
    pkg_lookup = {p["package_id"]: p for p in packages}
    arpu_cache = {}
    device_cache = {}

    def hook(ctx):
        _record_band_activity(ctx)
        if ctx.clock.band != EVENING:
            return []

        rows = ctx.store.conn.execute(
            "SELECT * FROM customer_state ORDER BY customer_id"
        ).fetchall()
        cust_map = {r["customer_id"]: dict(r) for r in rows}

        events = []
        events.extend(
            _process_open_offers(cfg, ctx, packages, pkg_lookup, cust_map, arpu_cache, device_cache)
        )
        events.extend(
            _evaluate_new_offers(cfg, ctx, packages, cust_map, arpu_cache, device_cache)
        )
        return events

    return hook