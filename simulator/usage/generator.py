"""Usage generator: one customer, one band -> one usage_events record."""
import math

from simulator.common import make_rng
from simulator.customers.events import (
    SCHEMA_VERSION, SOURCE, _event_id, _pick, device_type_for,
)

# Persona choice depends on the device (feature phones have no real data use).
PERSONA_FEATURE_PHONE = (("call_heavy", 0.65), ("sms_heavy", 0.35))
PERSONA_SMARTPHONE = (
    ("call_heavy", 0.15), ("whatsapp_only", 0.43), ("data_heavy", 0.42),
)

# Per-day average use before noise: onnet, offnet, intl minutes, SMS, data MB.
PERSONA_DAILY = {
    "call_heavy":    {"onnet": 40, "offnet": 30, "intl": 1.0, "sms": 5,  "data_mb": 300},
    "sms_heavy":     {"onnet": 8,  "offnet": 6,  "intl": 0.1, "sms": 40, "data_mb": 150},
    "whatsapp_only": {"onnet": 6,  "offnet": 4,  "intl": 0.2, "sms": 3,  "data_mb": 500},
    "data_heavy":    {"onnet": 10, "offnet": 8,  "intl": 0.3, "sms": 3,  "data_mb": 1500},
}

# Share of data MB per app type.
DATA_SPLIT = {
    "call_heavy":    {"whatsapp": 0.40, "social": 0.20, "video": 0.00, "browsing": 0.25, "other": 0.15},
    "sms_heavy":     {"whatsapp": 0.40, "social": 0.20, "video": 0.00, "browsing": 0.25, "other": 0.15},
    "whatsapp_only": {"whatsapp": 0.60, "social": 0.15, "video": 0.00, "browsing": 0.15, "other": 0.10},
    "data_heavy":    {"whatsapp": 0.10, "social": 0.20, "video": 0.40, "browsing": 0.20, "other": 0.10},
}
FEATURE_PHONE_DATA_MB = (5, 20)  # per day, all counted as "other"

# Share of a day's use in each band: Night, Morning, Afternoon, Evening.
BAND_SHARE = (0.10, 0.30, 0.25, 0.35)

# Noise: a fixed factor per customer, plus a small change in every band.
FACTOR_SIGMA = 0.35
FACTOR_MIN = 0.5
FACTOR_MAX = 1.8
BAND_NOISE = 0.25  # +/- 25%
BASE_DROP_RATE = 0.015   # per call, healthy tower (Step 5 will multiply it)
MINUTES_PER_CALL = 3
ROAM_SHARE = 0.15        # share of bands spent on a neighbor tower
DATA_APPS = ("whatsapp", "social", "video", "browsing", "other")


def persona_for(cfg, n):
    """Persona of customer n (same every time; depends on the device)."""
    device = device_type_for(cfg, n)
    table = PERSONA_FEATURE_PHONE if device == "feature_phone" else PERSONA_SMARTPHONE
    rng = make_rng(cfg["seed"], "persona", n)
    return _pick(rng, table)


def customer_factor(cfg, n):
    """Fixed heavy/light multiplier of customer n, between 0.5 and 1.8."""
    rng = make_rng(cfg["seed"], "usage_factor", n)
    factor = math.exp(float(rng.normal(0.0, FACTOR_SIGMA)))
    return min(max(factor, FACTOR_MIN), FACTOR_MAX)
def customer_no(cfg, customer_id):
    """'C0000012' -> 12."""
    return int(customer_id[len(cfg["ids"]["customer_prefix"]):])


def neighbor_map(towers):
    """tower_id -> list of neighbor tower ids (towers must have neighbor_tower_ids)."""
    return {t["tower_id"]: list(t.get("neighbor_tower_ids", [])) for t in towers}


def _pick_tower(rng, home_tower_id, neighbors):
    near = neighbors.get(home_tower_id) or []
    if near and rng.random() < ROAM_SHARE:
        return near[int(rng.random() * len(near))]
    return home_tower_id


def build_usage_event(cfg, customer_id, home_tower_id, neighbors, clock):
    """usage_events record for one customer in the band that `clock` points at."""
    n = customer_no(cfg, customer_id)
    persona = persona_for(cfg, n)
    device = device_type_for(cfg, n)
    factor = customer_factor(cfg, n)
    index = clock.index
    share = BAND_SHARE[clock.band]
    scale = factor * share
    base = PERSONA_DAILY[persona]
    rng = make_rng(cfg["seed"], "usage", n, index)

    def expected(value):
        return value * scale * rng.uniform(1 - BAND_NOISE, 1 + BAND_NOISE)

    onnet = int(rng.poisson(expected(base["onnet"])))
    offnet = int(rng.poisson(expected(base["offnet"])))
    intl = int(rng.poisson(expected(base["intl"])))
    sms = int(rng.poisson(expected(base["sms"])))

    if device == "feature_phone":
        low, high = FEATURE_PHONE_DATA_MB
        total_mb = rng.uniform(low, high) * share
        split = {"other": 1.0}
    else:
        total_mb = expected(base["data_mb"])
        split = DATA_SPLIT[persona]
    data = {app: round(total_mb * split.get(app, 0.0), 2) for app in DATA_APPS}

    calls = int(round((onnet + offnet + intl) / MINUTES_PER_CALL))
    dropped = int(rng.binomial(calls, BASE_DROP_RATE))
    tower_id = _pick_tower(rng, home_tower_id, neighbors)

    return {
        "event_id": _event_id(cfg["seed"], "usage_events", customer_id, index),
        "event_time": clock.band_start.isoformat(),
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE,
        "customer_id": customer_id,
        "event_date": clock.event_date,
        "time_band": clock.band_name,
        "tower_id": tower_id,
        "calls_onnet_min": onnet,
        "calls_offnet_min": offnet,
        "calls_intl_min": intl,
        "sms_count": sms,
        "data_mb_whatsapp": data["whatsapp"],
        "data_mb_social": data["social"],
        "data_mb_video": data["video"],
        "data_mb_browsing": data["browsing"],
        "data_mb_other": data["other"],
        "dropped_calls": dropped,
        "active_package_ids": [],
        "spend_from_package": None,
        "spend_from_balance": None,
    }