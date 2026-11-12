"""Tower health ka dimaagh: signal, health aur kharabi ka faisla.

Sirf hisaab hai, koi file ya SQLite nahi. Waqt ghante ke index mein hai
(hour_index = band_index * 6 + ghanta). Har tower ke har ghante ka apna
random generator hai, is liye resume ke baad bhi wahi nateeja aata hai.
"""
from simulator.common import make_rng

HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
CRITICAL = "CRITICAL"
DOWN = "DOWN"

BASELINE_DBM = {"3G": -78.0, "4G": -75.0, "5G": -72.0}
OFFSET_RANGE = 5.0
NOISE_SD = 2.0
PRECURSOR_END_DBM = -110.0
DIP_DBM_RANGE = (-103.0, -96.0)

SUDDEN_RATE = 0.0001          # HEALTHY tower, har ghante, achanak DOWN
DIP_RATE = 0.00016            # HEALTHY tower, har ghante, temporary dip
DIP_LOAD_MULTIPLIER = 5.0     # load critical_load se upar ho to dip ka chance

PRECURSOR_HOURS = (24, 168)   # 1 se 7 din
DIP_HOURS = (2, 8)
DOWN_HOURS = (3, 12)
CONGESTION_LOOKBACK_HOURS = 6

_OUTAGE_COLS = (
    "outage_id", "outage_cause", "outage_severity", "outage_affected_pct",
)


def baseline_signal(cfg, tower):
    """Tower ka apna normal signal: tower_type ka base plus seed se fixed offset."""
    kind = tower["tower_type"]
    if kind not in BASELINE_DBM:
        raise ValueError(f"Unknown tower_type: {kind!r}")
    rng = make_rng(cfg["seed"], "tower_offset", tower["tower_id"])
    return BASELINE_DBM[kind] + float(rng.uniform(-OFFSET_RANGE, OFFSET_RANGE))


def health_from_signal(cfg, signal):
    """Signal -95 se upar HEALTHY, -95 se -105 DEGRADED, -105 se neeche CRITICAL."""
    t = cfg["towers"]
    if signal >= t["degraded_signal_dbm"]:
        return HEALTHY
    if signal >= t["critical_signal_dbm"]:
        return DEGRADED
    return CRITICAL


def precursor_rate(cfg):
    """Achanak aur precursor failures ka 30/70 rishta (failure_precursor_share) se."""
    share = cfg["towers"]["failure_precursor_share"]
    return SUDDEN_RATE * share / (1.0 - share)


def dip_signal(cfg, tower_id, dip_until_hour):
    """Dip ke dauran signal (-96 se -103); dip_until_hour se deterministic."""
    rng = make_rng(cfg["seed"], "tower_dip", tower_id, dip_until_hour)
    return float(rng.uniform(DIP_DBM_RANGE[0], DIP_DBM_RANGE[1]))


def initial_state(tower_id, baseline):
    """Naye tower ki shuru ki state: HEALTHY, koi kharabi nahi."""
    return {
        "tower_id": tower_id,
        "health": HEALTHY,
        "load": 0.0,
        "signal_dbm": baseline,
        "precursor_active": 0,
        "failure_at": None,
        "precursor_start_hour": None,
        "dip_until_hour": None,
        "down_until_hour": None,
        "outage_id": None,
        "outage_cause": None,
        "outage_severity": None,
        "outage_affected_pct": None,
    }


def next_hour(cfg, tower_id, baseline, state, hour_index, load):
    """Ek ghante mein tower ki state aage badhao.

    Wapas deta hai (nayi_state, event). event = {"went_down", "recovered", "kind"},
    kind "sudden" ya "precursor" (sirf went_down par). DOWN ghante mein signal
    purana hi rehta hai. outage_* columns START par hook bharta hai.
    """
    rng = make_rng(cfg["seed"], "tower_hour", tower_id, hour_index)
    roll = float(rng.random())
    noise = float(rng.normal(0.0, NOISE_SD))
    precursor_len = int(rng.integers(PRECURSOR_HOURS[0], PRECURSOR_HOURS[1] + 1))
    dip_len = int(rng.integers(DIP_HOURS[0], DIP_HOURS[1] + 1))
    down_len = int(rng.integers(DOWN_HOURS[0], DOWN_HOURS[1] + 1))

    new = dict(state)
    new["load"] = load
    event = {"went_down": False, "recovered": False, "kind": None}

    def go_down(kind):
        new.update(
            health=DOWN, precursor_active=0, failure_at=None,
            precursor_start_hour=None, dip_until_hour=None,
            down_until_hour=hour_index + down_len,
        )
        event["went_down"] = True
        event["kind"] = kind
        return new, event

    if state["health"] == DOWN:
        if hour_index < state["down_until_hour"]:
            return new, event
        # wapas aa gaya: is ghante koi nayi kharabi nahi
        new.update(down_until_hour=None, precursor_active=0, failure_at=None,
                   precursor_start_hour=None, dip_until_hour=None)
        for col in _OUTAGE_COLS:
            new[col] = None
        signal = baseline + noise
        new["signal_dbm"] = signal
        new["health"] = health_from_signal(cfg, signal)
        event["recovered"] = True
        return new, event

    if state["precursor_active"]:
        if hour_index >= state["failure_at"]:
            return go_down("precursor")
        start = state["precursor_start_hour"]
        span = state["failure_at"] - start
        frac = (hour_index - start) / span
        signal = baseline + (PRECURSOR_END_DBM - baseline) * frac + noise
    else:
        dip_until = state["dip_until_hour"]
        if dip_until is not None and hour_index < dip_until:
            signal = dip_signal(cfg, tower_id, dip_until)
        else:
            new["dip_until_hour"] = None
            p_sudden = SUDDEN_RATE
            p_precursor = precursor_rate(cfg)
            over = load > cfg["towers"]["critical_load"]
            p_dip = DIP_RATE * (DIP_LOAD_MULTIPLIER if over else 1.0)
            if roll < p_sudden:
                return go_down("sudden")
            if roll < p_sudden + p_precursor:
                new.update(
                    precursor_active=1, precursor_start_hour=hour_index,
                    failure_at=hour_index + precursor_len,
                )
                signal = baseline + noise
            elif roll < p_sudden + p_precursor + p_dip:
                new["dip_until_hour"] = hour_index + dip_len
                signal = dip_signal(cfg, tower_id, hour_index + dip_len)
            else:
                signal = baseline + noise

    new["signal_dbm"] = signal
    new["health"] = health_from_signal(cfg, signal)
    return new, event


def outage_cause(cfg, tower_id, hour_index, kind, recent_loads):
    """Achanak: power_cut ya fibre_cut. Precursor: congestion agar pichle
    6 ghanton mein load critical_load se upar tha, warna hardware."""
    if kind == "sudden":
        rng = make_rng(cfg["seed"], "tower_cause", tower_id, hour_index)
        return "power_cut" if rng.random() < 0.5 else "fibre_cut"
    limit = cfg["towers"]["critical_load"]
    recent = list(recent_loads)[-CONGESTION_LOOKBACK_HOURS:]
    if any(x > limit for x in recent):
        return "congestion"
    return "hardware"


def severity_from_pct(affected_pct):
    """3% se kam 1, 3% se 6% tak 2, 6% se zyada 3."""
    if affected_pct < 3.0:
        return 1
    if affected_pct <= 6.0:
        return 2
    return 3


def outage_id(tower_id, start_hour):
    """START aur END mein wahi id (tower_id aur START ka ghanta)."""
    return f"OUT-{tower_id}-{start_hour}"