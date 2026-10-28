"""Build one customer's starting state (no events, no engine)."""
from simulator.common import customer_id, make_rng

PREPAID_BALANCE_MIN = 50
PREPAID_BALANCE_MAX = 500


def towers_by_city(towers, cfg):
    """Group tower ids by city. Raises if a configured city has no towers."""
    grouped = {}
    for t in towers:
        grouped.setdefault(t["city"], []).append(t["tower_id"])
    for city in grouped:
        grouped[city].sort()
    missing = [c for c in cfg["geography"] if not grouped.get(c)]
    if missing:
        raise ValueError(f"In shehron ke towers nahi mile: {missing}")
    return grouped


def _pick_city(cfg, rng):
    cities = list(cfg["geography"].items())
    x = rng.random()
    total = 0.0
    for name, g in cities:
        total += g["share"]
        if x < total:
            return name
    return cities[-1][0]


def build_customer(cfg, towers_by_city, n, signup_index):
    rng = make_rng(cfg["seed"], "customer", n)
    city = _pick_city(cfg, rng)
    tower_ids = towers_by_city[city]
    home_tower_id = tower_ids[int(rng.random() * len(tower_ids))]
    prepaid = rng.random() < cfg["customers"]["prepaid_share"]
    if prepaid:
        span = PREPAID_BALANCE_MAX - PREPAID_BALANCE_MIN
        balance = round(PREPAID_BALANCE_MIN + span * rng.random() ** 2, 2)
    else:
        balance = 0.0
    return {
        "customer_id": customer_id(cfg, n),
        "city": city,
        "plan_type": "prepaid" if prepaid else "postpaid",
        "status": "ACTIVE",
        "status_since": signup_index,
        "balance": balance,
        "home_tower_id": home_tower_id,
        "last_active": signup_index,
        "at_risk": 0,
    }