"""Build customer_events and profile_events records (pure functions)."""
import hashlib

from simulator.common import make_rng
from simulator.core.clock import SimClock

SCHEMA_VERSION = "1.0"
SOURCE = "simulator"
# (value, weight) tables. Weights are fractions that sum to 1.0.
AGE_BANDS = (
    ("18-24", 0.25), ("25-34", 0.35), ("35-44", 0.22),
    ("45-54", 0.12), ("55+", 0.06),
)
GENDERS = (("male", 0.60), ("female", 0.40))
LANGUAGES = (("Urdu", 0.65), ("English", 0.25), ("Regional", 0.10))
CHANNELS = (
    ("retailer", 0.55), ("online", 0.15), ("campaign", 0.15),
    ("referral", 0.10), ("other", 0.05),
)
DEVICES = (
    ("smartphone_android", 0.62), ("smartphone_ios", 0.08),
    ("feature_phone", 0.30),
)
# Prepaid leans low/mid; overall (88% prepaid) comes to ~40/40/20.
ARPU_PREPAID = (("low", 0.44), ("mid", 0.40), ("high", 0.16))
ARPU_POSTPAID = (("low", 0.10), ("mid", 0.40), ("high", 0.50))


def _pick(rng, table):
    """Weighted choice from a (value, weight) table."""
    total = sum(w for _, w in table)
    x = rng.random() * total
    running = 0.0
    for value, weight in table:
        running += weight
        if x < running:
            return value
    return table[-1][0]


def _arpu_band(rng, plan_type):
    table = ARPU_PREPAID if plan_type == "prepaid" else ARPU_POSTPAID
    return _pick(rng, table)


def _mask_phone(rng):
    """Masked mobile number, e.g. 0334-xxxx09."""
    prefix = f"03{int(rng.integers(0, 50)):02d}"
    last2 = f"{int(rng.integers(0, 100)):02d}"
    return f"{prefix}-xxxx{last2}"


def _mask_cnic(rng, gender):
    """Masked CNIC, e.g. xxxxx-xxxxx45-7 (last digit: odd male, even female)."""
    middle2 = f"{int(rng.integers(0, 100)):02d}"
    k = int(rng.integers(0, 5))
    last = 2 * k + 1 if gender == "male" else 2 * k
    return f"xxxxx-xxxxx{middle2}-{last}"


def _event_id(seed, topic, *parts):
    """Deterministic event id (same inputs always give the same id)."""
    text = "|".join([str(seed), topic] + [str(p) for p in parts])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]

def device_type_for(cfg, n):
    """Device type of customer n (same value every time; events and usage both use it)."""
    rng = make_rng(cfg["seed"], "device", n)
    return _pick(rng, DEVICES)

def _envelope(cfg, topic, customer_id, signup_index, *id_parts):
    """Common fields for one event, plus the signup date of that band."""
    clock = SimClock.from_config(cfg, index=signup_index)
    envelope = {
        "event_id": _event_id(cfg["seed"], topic, customer_id, *id_parts),
        "event_time": clock.band_start.isoformat(),
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE,
    }
    return envelope, clock.event_date


def build_customer_event(cfg, customer, n, signup_index):
    """customer_events record for one new customer (zone is not included)."""
    rng = make_rng(cfg["seed"], "customer_event", n)
    event, signup_date = _envelope(
        cfg, "customer_events", customer["customer_id"], signup_index
    )
    event.update({
        "customer_id": customer["customer_id"],
        "signup_date": signup_date,
        "region": customer["city"],
        "city": customer["city"],
        "segment": customer["plan_type"],
        "acquisition_channel": _pick(rng, CHANNELS),
        "device_type": device_type_for(cfg, n),
        "initial_balance": customer["balance"],
        "home_tower_id": customer["home_tower_id"],
    })
    return event


def build_profile_event(cfg, customer, n, signup_index):
    """profile_events record (version 1) with masked phone and CNIC."""
    rng = make_rng(cfg["seed"], "profile", n)
    profile_version = 1
    event, _ = _envelope(
        cfg, "profile_events", customer["customer_id"], signup_index,
        profile_version,
    )
    age_band = _pick(rng, AGE_BANDS)
    gender = _pick(rng, GENDERS)
    language_pref = _pick(rng, LANGUAGES)
    arpu_band = _arpu_band(rng, customer["plan_type"])
    phone_masked = _mask_phone(rng)
    cnic_masked = _mask_cnic(rng, gender)
    event.update({
        "customer_id": customer["customer_id"],
        "profile_version": profile_version,
        "age_band": age_band,
        "gender": gender,
        "phone_masked": phone_masked,
        "cnic_masked": cnic_masked,
        "language_pref": language_pref,
        "arpu_band": arpu_band,
    })
    return event