"""Step 9 (offers): pure functions. Yahan koi DB ya hook nahi."""
import hashlib
from datetime import timedelta

from simulator.offers import model as m


def unit_random(seed, *parts):
    """Seed aur parts se deterministic number, 0 se 1 ke beech."""
    key = "|".join(str(p) for p in (seed,) + parts).encode("utf-8")
    h = hashlib.sha256(key).digest()
    return int.from_bytes(h[:8], "big") / 2 ** 64


def is_control(seed, customer_id):
    return unit_random(seed, "offer_control", customer_id) < m.CONTROL_GROUP_PCT


def weekly_rise(values_by_day, day):
    """Pichle 7 din ka total / 28 din ka hafta-wari average.
    History kam ho (OFFER_MIN_HISTORY_DAYS) ya average 0 ho to None."""
    window = [values_by_day[d] for d in range(day - 27, day + 1) if d in values_by_day]
    if len(window) < m.OFFER_MIN_HISTORY_DAYS:
        return None
    avg_week = sum(window) / len(window) * 7.0
    if avg_week <= 0:
        return None
    last7 = sum(values_by_day.get(d, 0.0) for d in range(day - 6, day + 1))
    return last7 / avg_week


def weekend_due(d):
    return d.weekday() == m.WEEKEND_OFFER_DAY


def events_due(d):
    """Is date par kaun se event offers jane chahiye: [(offer_type, campaign, event_date)]."""
    out = []
    for ev_date, offer_type, campaign in m.EVENT_CALENDAR:
        if d == ev_date - timedelta(days=m.LEAD_DAYS_BY_OFFER[offer_type]):
            out.append((offer_type, campaign, ev_date))
    return out


def recharge_offer_due(plan_type, balance):
    return plan_type == "prepaid" and balance < m.LOW_BALANCE_OFFER_PKR


def recharge_target_reached(total, band):
    return total >= m.RECHARGE_TARGET_BY_BAND[band]


def window_end(offer_type, sent, event_date=None):
    """Accept ki aakhri date (shamil)."""
    if offer_type == "WEEKEND_SPECIAL":
        return sent + timedelta(days=6 - sent.weekday())  # Sunday tak
    if offer_type in m.AFTER_DAYS_BY_OFFER:
        return event_date + timedelta(days=m.AFTER_DAYS_BY_OFFER[offer_type])
    return sent + timedelta(days=m.WINDOW_DAYS_BY_OFFER[offer_type])


def planned_accept_date(seed, offer_id, offer_type, sent, end):
    """Package offers ke liye accept ki date (seed se), ya None agar accept nahi karega.
    RECHARGE_BONUS ke liye hamesha None (wahan accept recharge total se hota hai)."""
    chance = m.ACCEPT_CHANCE_BY_OFFER.get(offer_type)
    if chance is None:
        return None
    if unit_random(seed, "offer_accept", offer_id) >= chance:
        return None
    n_days = (end - sent).days
    if n_days < 1:
        return None
    pick = int(unit_random(seed, "offer_accept_day", offer_id) * n_days)
    return sent + timedelta(days=1 + pick)


def price_in_band(price, band):
    lo, hi = m.PRICE_RANGE_BY_BAND[band]
    return price >= lo and (hi is None or price < hi)


def _all_region(p):
    return list(p.get("region", [])) == ["all"] and not p.get("night_only", False)


def _fits(offer_type, p):
    if offer_type in ("DATA_BOOST", "CRICKET_PACK"):
        return p["quota_data_mb"] >= m.DATA_BOOST_MIN_DATA_MB
    if offer_type == "CALL_BUNDLE":
        return p["quota_offnet_min"] + p["quota_anynet_min"] >= m.CALL_BUNDLE_MIN_MINUTES
    return p.get("package_type") == "combo"  # WEEKEND_SPECIAL, EVENT_OFFER


def choose_offer_package(seed, customer_id, offer_type, packages, band, active_ids):
    """Quota aur price band se chunao; customer ke paas pehle se active package nahi."""
    cands = sorted(
        (p for p in packages
         if _all_region(p) and p["package_id"] not in active_ids
         and price_in_band(p["price_pkr"], band) and _fits(offer_type, p)),
        key=lambda p: p["package_id"],
    )
    if not cands:
        return None
    i = int(unit_random(seed, "offer_pkg", customer_id, offer_type) * len(cands))
    return cands[i]


def discounted_package(pdef, pct):
    """Package ki copy, discounted price ke sath (asli pdef nahi badalta)."""
    d = dict(pdef)
    d["price_pkr"] = round(float(pdef["price_pkr"]) * (1.0 - pct), 2)
    return d


def reward_package(packages, band, device_type, active_ids):
    """RECHARGE_BONUS ka inaam: free package (price 0). Feature phone ko minutes,
    baqi ko data wala sab se bara package, jo band ke price cap ke andar ho."""
    cap = m.REWARD_MAX_PRICE_BY_BAND[band]

    def value(p):
        if device_type == "feature_phone":
            return p["quota_onnet_min"] + p["quota_offnet_min"] + p["quota_anynet_min"]
        return p["quota_data_mb"]

    cands = [
        p for p in packages
        if _all_region(p) and p["package_id"] not in active_ids
        and p["price_pkr"] <= cap and value(p) > 0
    ]
    if not cands:
        return None
    best = max(cands, key=lambda p: (value(p), p["package_id"]))
    free = dict(best)
    free["price_pkr"] = 0.0
    return free


def can_send(sent_dates, today):
    """Frequency cap: 7 din mein 1 offer, 30 din mein zyada se zyada 3 (HELD bhi ginte hain)."""
    if any(0 <= (today - d).days < m.OFFER_GAP_DAYS for d in sent_dates):
        return False
    last30 = [d for d in sent_dates if 0 <= (today - d).days < 30]
    return len(last30) < m.MAX_OFFERS_30D


def pick_offer(due_types):
    for t in m.PRIORITY:
        if t in due_types:
            return t
    return None