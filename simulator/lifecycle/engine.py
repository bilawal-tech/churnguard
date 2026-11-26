"""Churn ka hisaab: sirf pure functions, koi SQLite ya random generator nahi.

Random draws (noise_z, u) aur is_prepaid bahar se aate hain.
Din ke numbers (today, at_risk_since) ek hi unit (din ka index) mein hote hain.
"""
from simulator.lifecycle import model as m

# adder ka naam -> churn_reason
_ADDER_REASON = {
    "price": m.HIGH_PRICE,
    "network": m.POOR_NETWORK,
    "usage": m.USAGE_DECLINE,
    "zero_balance": m.INACTIVITY,
}


def price_adder(arpu_band):
    return m.PRICE_WEIGHT * m.PRICE_SENSITIVITY[arpu_band]


def usage_adder(usage_7d, usage_28d, history_days):
    """7 din ka usage hafta-wari average ke USAGE_DROP_START se kam ho to adder."""
    if history_days < m.MIN_HISTORY_DAYS:
        return 0.0
    weekly_avg = usage_28d / (min(history_days, m.HISTORY_DAYS) / m.USAGE_WINDOW_DAYS)
    if weekly_avg <= 0:
        return 0.0
    ratio = usage_7d / weekly_avg
    if ratio >= m.USAGE_DROP_START:
        return 0.0
    return m.USAGE_MAX_ADDER * (m.USAGE_DROP_START - ratio) / m.USAGE_DROP_START


def network_adder(calls_7d, dropped_7d):
    if calls_7d < m.NETWORK_MIN_CALLS:
        return 0.0
    ratio = dropped_7d / calls_7d
    if ratio <= m.NETWORK_NORMAL_RATIO:
        return 0.0
    span = m.NETWORK_FULL_RATIO - m.NETWORK_NORMAL_RATIO
    frac = min(1.0, (ratio - m.NETWORK_NORMAL_RATIO) / span)
    return m.NETWORK_MAX_ADDER * frac



def zero_balance_adder(days_at_zero):
    if days_at_zero <= 0:
        return 0.0
    return m.ZERO_BALANCE_MAX_ADDER * min(1.0, days_at_zero / m.ZERO_BALANCE_FULL_DAYS)


def risk_score(arpu_band, usage_7d, usage_28d, history_days,
               calls_7d, dropped_7d, days_at_zero, is_prepaid):
    """Chaaron adders aur unka jama (total) dict mein. Postpaid par zero_balance 0."""
    adders = {
        "price": price_adder(arpu_band),
        "network": network_adder(calls_7d, dropped_7d),
        "usage": usage_adder(usage_7d, usage_28d, history_days),
        "zero_balance": zero_balance_adder(days_at_zero) if is_prepaid else 0.0,
    }
    adders["total"] = sum(adders.values())
    return adders


def churn_chance(risk_total, is_prepaid, at_risk, noise_z):
    """Roz ka churn chance (0 se 1). noise_z ek standard normal draw hai."""
    p = m.BASE_DAILY_CHURN * (1.0 + risk_total)
    if not is_prepaid:
        p *= m.POSTPAID_CHURN_FACTOR
    if at_risk:
        p *= m.AT_RISK_CHURN_MULTIPLIER
    p *= max(0.0, 1.0 + m.NOISE_SD * noise_z)
    return min(1.0, p)


def pick_churn_reason(adders, u):
    """Reason adders ke hisse se. COMPETITOR_OFFER ka fixed weight. u 0..1 ka draw."""
    weights = {k: max(0.0, adders[k]) for k in _ADDER_REASON}
    total = sum(weights.values()) + m.COMPETITOR_OFFER_WEIGHT
    x = u * total
    for k in _ADDER_REASON:
        x -= weights[k]
        if x < 0:
            return _ADDER_REASON[k]
    return m.COMPETITOR_OFFER


def inactivity_transition(is_prepaid, status, inactivity_days):
    """Prepaid: ACTIVE 14 din par SUSPENDED, SUSPENDED 30 din par CHURNED. Warna None."""
    if not is_prepaid:
        return None
    if status == m.ACTIVE and inactivity_days >= m.INACTIVE_SUSPEND_DAYS:
        return m.SUSPENDED
    if status == m.SUSPENDED and inactivity_days >= m.INACTIVE_CHURN_DAYS:
        return m.CHURNED
    return None


def reactivates(status, u):
    """Sirf SUSPENDED wapas aa sakta hai, REACTIVATE_CHANCE_PER_DAY se."""
    return status == m.SUSPENDED and u < m.REACTIVATE_CHANCE_PER_DAY


def at_risk_next(at_risk, at_risk_since, risk_total, today):
    """(at_risk, at_risk_since). at_risk_since = aakhri din jab score threshold par tha."""
    if risk_total >= m.AT_RISK_THRESHOLD:
        return 1, today
    if at_risk and at_risk_since is not None:
        if today - at_risk_since >= m.AT_RISK_RECOVER_DAYS:
            return 0, None
        return 1, at_risk_since
    return 0, None
_INT_FIELDS = ("calls_onnet_min", "calls_offnet_min", "calls_intl_min",
               "sms_count", "dropped_calls")
_MB_FIELDS = ("data_mb_whatsapp", "data_mb_social", "data_mb_video",
              "data_mb_browsing", "data_mb_other")


def scale_usage_event(ev, factor):
    """Usage event ko jagah par factor se scale karta hai (at-risk ka disengage)."""
    for k in _INT_FIELDS:
        ev[k] = int(round(ev[k] * factor))
    for k in _MB_FIELDS:
        ev[k] = round(ev[k] * factor, 2)
    return ev