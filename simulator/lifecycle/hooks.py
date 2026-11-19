"""Lifecycle hook: usage ka roz ka hisaab aur roz ek baar churn ka faisla.

Har band: us band ke usage events customer_daily mein jama hote hain.
Evening band ke aakhir mein: last_active, zero balance, at-risk, SUSPENDED,
CHURNED aur reactivation ka faisla. Naya status agle din ke Night band se lagu hota hai.
Hooks ki tartib mein ye sab se aakhir mein chalta hai (tower_hook ke baad).
"""
from simulator.billing.engine import arpu_band_for, choose_recharge
from simulator.billing.events import build_recharge_event
from simulator.common import make_rng
from simulator.core.clock import BANDS_PER_DAY
from simulator.lifecycle import engine as e
from simulator.lifecycle import model as m
from simulator.lifecycle.events import build_lifecycle_event
from simulator.usage.generator import MINUTES_PER_CALL, customer_no

EVENING = BANDS_PER_DAY - 1

UPSERT_DAILY = (
    "INSERT INTO customer_daily(customer_id, day, usage, calls, dropped_calls) "
    "VALUES(?, ?, ?, ?, ?) "
    "ON CONFLICT(customer_id, day) DO UPDATE SET "
    "usage = usage + excluded.usage, calls = calls + excluded.calls, "
    "dropped_calls = dropped_calls + excluded.dropped_calls"
)

AGG_SQL = (
    "SELECT customer_id, "
    "SUM(usage) AS usage_28d, COUNT(*) AS history_days, "
    "SUM(CASE WHEN day > :w7 THEN usage ELSE 0 END) AS usage_7d, "
    "SUM(CASE WHEN day > :w7 THEN calls ELSE 0 END) AS calls_7d, "
    "SUM(CASE WHEN day > :w7 THEN dropped_calls ELSE 0 END) AS dropped_7d, "
    "SUM(CASE WHEN day = :today THEN usage ELSE 0 END) AS usage_today "
    "FROM customer_daily WHERE day > :w28 GROUP BY customer_id"
)

STATE_SQL = (
    "SELECT * FROM customer_state WHERE status IN ('ACTIVE', 'SUSPENDED') "
    "ORDER BY customer_id"
)

UPDATE_SQL = (
    "UPDATE customer_state SET status=?, status_since=?, balance=?, last_active=?, "
    "at_risk=?, at_risk_since=?, zero_balance_since=? WHERE customer_id=?"
)

_EMPTY = {"usage_28d": 0.0, "history_days": 0, "usage_7d": 0.0,
          "calls_7d": 0, "dropped_7d": 0, "usage_today": 0.0}


def _record_usage(ctx):
    """Is band ke usage events ko customer_daily mein jodna."""
    day = ctx.clock.day
    rows = []
    for ev in ctx.band_events_for("usage_events"):
        usage = (ev["spend_from_package"] or 0.0) + (ev["spend_from_balance"] or 0.0)
        minutes = ev["calls_onnet_min"] + ev["calls_offnet_min"] + ev["calls_intl_min"]
        calls = int(round(minutes / MINUTES_PER_CALL))
        rows.append((ev["customer_id"], day, usage, calls, ev["dropped_calls"]))
    if rows:
        ctx.store.conn.executemany(UPSERT_DAILY, rows)


def _life(cfg, cid, clock, from_status, to_status, reason=None, days=None):
    return ("lifecycle_events",
            build_lifecycle_event(cfg, cid, clock, from_status, to_status, reason, days))


def _daily_decisions(cfg, ctx, arpu_cache):
    conn = ctx.store.conn
    clock = ctx.clock
    today = clock.day
    params = {"w7": today - m.USAGE_WINDOW_DAYS, "w28": today - m.HISTORY_DAYS,
              "today": today}
    agg = {r["customer_id"]: r for r in conn.execute(AGG_SQL, params)}

    events = []
    updates = []
    for r in conn.execute(STATE_SQL).fetchall():
        c = dict(r)
        cid = c["customer_id"]
        n = customer_no(cfg, cid)
        is_prepaid = c["plan_type"] == "prepaid"
        a = agg.get(cid, _EMPTY)

        status = c["status"]
        status_since = c["status_since"]
        balance = float(c["balance"])
        last_active = c["last_active"]
        at_risk = c["at_risk"]
        at_risk_since = c["at_risk_since"]
        zb_since = c["zero_balance_since"]
        old = (status, status_since, balance, last_active, at_risk, at_risk_since, zb_since)

        if a["usage_today"] > 0:
            last_active = clock.index
        inactivity_days = (clock.index - last_active) // BANDS_PER_DAY

        rng = make_rng(cfg["seed"], "lifecycle", n, today)
        noise_z = float(rng.standard_normal())
        u_churn = float(rng.random())
        u_reason = float(rng.random())
        u_react = float(rng.random())

        if status == m.ACTIVE:
            if is_prepaid:
                if balance <= 0.0:
                    if zb_since is None:
                        zb_since = today
                else:
                    zb_since = None
            days_at_zero = (today - zb_since) if zb_since is not None else 0

            band = arpu_cache.get(cid)
            if band is None:
                band = arpu_cache[cid] = arpu_band_for(cfg, n, c["plan_type"])
            adders = e.risk_score(
                band, a["usage_7d"], a["usage_28d"], a["history_days"],
                a["calls_7d"], a["dropped_7d"], days_at_zero, is_prepaid,
            )
            at_risk, at_risk_since = e.at_risk_next(
                at_risk, at_risk_since, adders["total"], today)

            if e.inactivity_transition(is_prepaid, status, inactivity_days) == m.SUSPENDED:
                events.append(_life(cfg, cid, clock, m.ACTIVE, m.SUSPENDED,
                                    None, inactivity_days))
                status, status_since = m.SUSPENDED, clock.index
            else:
                p = e.churn_chance(adders["total"], is_prepaid, at_risk, noise_z)
                if u_churn < p:
                    reason = e.pick_churn_reason(adders, u_reason)
                    events.append(_life(cfg, cid, clock, m.ACTIVE, m.CHURNED, reason, None))
                    status, status_since = m.CHURNED, clock.index
        else:  # SUSPENDED
            if e.inactivity_transition(is_prepaid, status, inactivity_days) == m.CHURNED:
                events.append(_life(cfg, cid, clock, m.SUSPENDED, m.CHURNED,
                                    m.INACTIVITY, inactivity_days))
                status, status_since = m.CHURNED, clock.index
            elif e.reactivates(status, u_react):
                amount, channel = choose_recharge(cfg, n, "prepaid", clock.index)
                bal_after = round(balance + amount, 2)
                events.append(("recharge_events", build_recharge_event(
                    cfg, cid, clock, amount, channel, balance, bal_after)))
                events.append(_life(cfg, cid, clock, m.SUSPENDED, m.REACTIVATED))
                balance = bal_after
                status, status_since = m.ACTIVE, clock.index
                last_active = clock.index
                at_risk, at_risk_since, zb_since = 0, None, None

        new = (status, status_since, balance, last_active, at_risk, at_risk_since, zb_since)
        if new != old:
            updates.append((status, status_since, balance, last_active,
                            at_risk, at_risk_since, zb_since, cid))

    if updates:
        conn.executemany(UPDATE_SQL, updates)
    conn.execute("DELETE FROM customer_daily WHERE day <= ?", (today - m.HISTORY_DAYS,))
    return events


def make_lifecycle_hook(cfg):
    """Return lifecycle hook(ctx). Hooks ki list mein sab se aakhir mein rakhna."""
    arpu_cache = {}

    def hook(ctx):
        _record_usage(ctx)
        if ctx.clock.band != EVENING:
            return []
        return _daily_decisions(cfg, ctx, arpu_cache)

    return hook