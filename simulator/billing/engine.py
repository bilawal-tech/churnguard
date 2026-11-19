"""Core billing logic: recharge, package choice, quota deduction, balance cap."""
from simulator.common import make_rng
from simulator.core.clock import BANDS_PER_DAY
from simulator.customers.events import _arpu_band, _pick, device_type_for
from simulator.usage.generator import customer_no, persona_for

# Recharge rules
RECHARGE_THRESHOLD_PKR = 50.0
RECHARGE_AMOUNTS = (100, 200, 300, 500, 1000)
RECHARGE_AMOUNT_WEIGHTS = {
    "low":  ((100, 0.40), (200, 0.35), (300, 0.15), (500, 0.08), (1000, 0.02)),
    "mid":  ((100, 0.15), (200, 0.30), (300, 0.25), (500, 0.22), (1000, 0.08)),
    "high": ((100, 0.05), (200, 0.10), (300, 0.20), (500, 0.40), (1000, 0.25)),
}
RECHARGE_CHANNELS = (
    ("retailer", 0.50),
    ("easypaisa", 0.20),
    ("jazzcash", 0.15),
    ("app", 0.10),
    ("card", 0.05),
)

# Package purchase rules
NO_PACKAGE_SHARE = 0.15
PACKAGE_BUY_CHANCE = 0.065
AUTO_RENEW_ON_CHANCE = 0.20
ADDON_BUY_CHANCE = 0.50

PERSONA_PKG_TYPES = {
    "call_heavy":    (("combo", 0.80), ("voice", 0.20)),
    "sms_heavy":     (("combo", 0.80), ("voice", 0.20)),
    "whatsapp_only": (("combo", 0.60), ("social", 0.40)),
    "data_heavy":    (("combo", 0.80), ("data", 0.20)),
}

# Out-of-bundle PKR rates (also used for Option A spend_from_package value)
RATE_ONNET_MIN = 1.5
RATE_OFFNET_MIN = 2.5
RATE_INTL_MIN = 15.0
RATE_SMS = 0.5
RATE_DATA_MB = 0.1

# Mapping Jazz CSV regions to our 8 cities
REGION_TO_CITIES = {
    "all": {
        "Karachi", "Lahore", "Islamabad_Rawalpindi", "Faisalabad",
        "Peshawar", "Multan", "Quetta", "Other_cities",
    },
    "Karachi": {"Karachi"},
    "Hyderabad": {"Other_cities"},
    "Badin": {"Other_cities"},
    "Sindh": {"Karachi", "Other_cities"},
    "South": {"Karachi", "Multan", "Quetta", "Other_cities"},
    "Attock": {"Islamabad_Rawalpindi", "Other_cities"},
    "Taxila": {"Islamabad_Rawalpindi", "Other_cities"},
    "Peshawar": {"Peshawar"},
    "Nowshera": {"Peshawar", "Other_cities"},
    "Kohat": {"Peshawar", "Other_cities"},
    "Abbottabad": {"Other_cities"},
    "Chakwal": {"Other_cities"},
    "Gujrat": {"Other_cities"},
    "Chenab": {"Faisalabad", "Other_cities"},
    "Sargodha": {"Faisalabad", "Other_cities"},
    "Quetta": {"Quetta"},
}

QUOTA_FIELDS = (
    "rem_onnet_min", "rem_offnet_min", "rem_anynet_min", "rem_intl_min",
    "rem_sms", "rem_data_mb", "rem_social_mb",
)


def arpu_band_for(cfg, n, plan_type):
    rng = make_rng(cfg["seed"], "customer_event", n)
    return _arpu_band(rng, plan_type)


def has_no_package_habit(cfg, n):
    rng = make_rng(cfg["seed"], "no_package_habit", n)
    return rng.random() < NO_PACKAGE_SHARE


def package_for_city(pkg, city):
    regions = pkg.get("region") or ["all"]
    for r in regions:
        if city in REGION_TO_CITIES.get(r, set()):
            return True
    return False


def eligible_packages(packages, city, device, pkg_type):
    out = []
    for p in packages:
        if p["package_type"] != pkg_type:
            continue
        if device == "feature_phone" and p["package_type"] in ("data", "social"):
            continue
        if not package_for_city(p, city):
            continue
        out.append(p)
    return sorted(out, key=lambda x: (x["price_pkr"], x["package_id"]))


def choose_package(cfg, n, plan_type, city, packages, max_price=None):
    """Pick a deterministic preferred package for customer n based on persona & ARPU."""
    device = device_type_for(cfg, n)
    persona = persona_for(cfg, n)
    arpu = arpu_band_for(cfg, n, plan_type)
    rng = make_rng(cfg["seed"], "pkg_preference", n)

    type_table = PERSONA_PKG_TYPES[persona]
    if device == "feature_phone":
        # Feature phones cannot buy data or social packages
        allowed = tuple((t, w) for t, w in type_table if t not in ("data", "social"))
        total = sum(w for _, w in allowed)
        type_table = tuple((t, w / total) for t, w in allowed)

    chosen_type = _pick(rng, type_table)
    pool = eligible_packages(packages, city, device, chosen_type)
    if max_price is not None:
        pool = [p for p in pool if p["price_pkr"] <= max_price]
        if not pool:
            pool = [
                p for p in eligible_packages(packages, city, device, "combo")
                if p["price_pkr"] <= max_price
            ]
        if not pool:
            pool = sorted(
                (
                    p
                    for pkg_type in {p["package_type"] for p in packages}
                    for p in eligible_packages(packages, city, device, pkg_type)
                    if p["price_pkr"] <= max_price
                ),
                key=lambda p: (p["price_pkr"], p["package_id"]),
            )
    elif not pool:
        # Fallback to combo if chosen type has no regional match
        pool = eligible_packages(packages, city, device, "combo")
    if not pool:
        return None

    # Price tier weighting by arpu_band (sorted cheapest -> most expensive)
    k = len(pool)
    weights = []
    for idx in range(k):
        pos = idx / max(1, k - 1)  # 0.0 (cheapest) to 1.0 (costliest)
        if arpu == "low":
            w = 2.0 - 1.8 * pos
        elif arpu == "mid":
            w = 1.4 - 1.0 * pos
        else:
            w = 0.8 + 0.4 * pos
        weights.append(max(0.1, w))
    total_w = sum(weights)
    pick_val = rng.random() * total_w
    acc = 0.0
    for p, w in zip(pool, weights):
        acc += w
        if pick_val <= acc:
            return p
    return pool[-1]


def init_active_package_row(customer_id, sub_id, pkg, band_index, auto_renew):
    expires_at = band_index + int(pkg["validity_days"]) * BANDS_PER_DAY
    return {
        "customer_id": customer_id,
        "package_id": pkg["package_id"],
        "subscription_id": sub_id,
        "rem_onnet_min": float(pkg["quota_onnet_min"]),
        "rem_offnet_min": float(pkg["quota_offnet_min"]),
        "rem_anynet_min": float(pkg["quota_anynet_min"]),
        "rem_intl_min": float(pkg["quota_intl_min"]),
        "rem_sms": float(pkg["quota_sms"]),
        "rem_data_mb": float(pkg["quota_data_mb"]),
        "rem_social_mb": float(pkg["quota_social_mb"]),
        "expires_at": expires_at,
        "auto_renew": 1 if auto_renew else 0,
    }


def is_quota_exhausted(pkg_row):
    return all(float(pkg_row[f]) <= 1e-6 for f in QUOTA_FIELDS)


def choose_recharge(cfg, n, plan_type, band_index):
    arpu = arpu_band_for(cfg, n, plan_type)
    rng = make_rng(cfg["seed"], "recharge", n, band_index)
    amount = _pick(rng, RECHARGE_AMOUNT_WEIGHTS[arpu])
    channel = _pick(rng, RECHARGE_CHANNELS)
    return int(amount), channel


def _deduct_from_bucket(pkg_row, field, needed, usable_ratio):
    if needed <= 0 or usable_ratio <= 0:
        return 0.0
    avail = float(pkg_row[field]) * usable_ratio
    used = min(needed, avail)
    pkg_row[field] = round(max(0.0, float(pkg_row[field]) - used), 4)
    return used


def apply_usage_billing(
    cfg, customer, active_pkgs, pkg_lookup, usage_event, band_idx_in_day, clock_index,
):
    """Deduct quotas and balance for one usage_event.

    Mutates `usage_event` in place (active_package_ids, spend_from_package,
    spend_from_balance, and scales down usage if prepaid balance hits 0).
    Returns:
      - updated_balance (float)
      - updated_pkgs (list of active package dicts)
      - exhausted_subs (list of (pkg_row, pkg_def) that hit 0 total quota)
      - addon_subs (list of (new_pkg_row, pkg_def) if 50% addon bought)
    """
    cid = customer["customer_id"]
    n = customer_no(cfg, cid)
    is_prepaid = customer["plan_type"] == "prepaid"
    balance = float(customer["balance"])

    # Night=0 -> 100% night_only usable; Morning=1 -> 50% (6-9 AM); others -> 0%
    night_ratio = 1.0 if band_idx_in_day == 0 else (0.5 if band_idx_in_day == 1 else 0.0)

    onnet = float(usage_event["calls_onnet_min"])
    offnet = float(usage_event["calls_offnet_min"])
    intl = float(usage_event["calls_intl_min"])
    sms = float(usage_event["sms_count"])
    wa_mb = float(usage_event["data_mb_whatsapp"])
    soc_mb = float(usage_event["data_mb_social"])
    vid_mb = float(usage_event["data_mb_video"])
    brw_mb = float(usage_event["data_mb_browsing"])
    oth_mb = float(usage_event["data_mb_other"])

    pkg_used_value = 0.0
    active_ids = [p["package_id"] for p in active_pkgs]

    def consume_from_packages(pkgs_list):
        nonlocal onnet, offnet, intl, sms, wa_mb, soc_mb, vid_mb, brw_mb, oth_mb, pkg_used_value
        for prow in pkgs_list:
            pdef = pkg_lookup.get(prow["package_id"])
            if not pdef:
                continue
            ratio = night_ratio if pdef.get("night_only") else 1.0
            if ratio <= 0:
                continue

            # On-net calls: onnet -> anynet
            u = _deduct_from_bucket(prow, "rem_onnet_min", onnet, ratio)
            onnet -= u
            pkg_used_value += u * RATE_ONNET_MIN
            u = _deduct_from_bucket(prow, "rem_anynet_min", onnet, ratio)
            onnet -= u
            pkg_used_value += u * RATE_ONNET_MIN

            # Off-net calls: offnet -> anynet
            u = _deduct_from_bucket(prow, "rem_offnet_min", offnet, ratio)
            offnet -= u
            pkg_used_value += u * RATE_OFFNET_MIN
            u = _deduct_from_bucket(prow, "rem_anynet_min", offnet, ratio)
            offnet -= u
            pkg_used_value += u * RATE_OFFNET_MIN

            # Intl calls
            u = _deduct_from_bucket(prow, "rem_intl_min", intl, ratio)
            intl -= u
            pkg_used_value += u * RATE_INTL_MIN

            # SMS
            u = _deduct_from_bucket(prow, "rem_sms", sms, ratio)
            sms -= u
            pkg_used_value += u * RATE_SMS

            # Social & WhatsApp data: social_mb -> data_mb
            for app_name, rem in (("whatsapp", wa_mb), ("social", soc_mb)):
                u1 = _deduct_from_bucket(prow, "rem_social_mb", rem, ratio)
                rem -= u1
                pkg_used_value += u1 * RATE_DATA_MB
                u2 = _deduct_from_bucket(prow, "rem_data_mb", rem, ratio)
                rem -= u2
                pkg_used_value += u2 * RATE_DATA_MB
                if app_name == "whatsapp":
                    wa_mb = rem
                else:
                    soc_mb = rem

            # General data: data_mb
            for app_name, rem in (("video", vid_mb), ("browsing", brw_mb), ("other", oth_mb)):
                u = _deduct_from_bucket(prow, "rem_data_mb", rem, ratio)
                rem -= u
                pkg_used_value += u * RATE_DATA_MB
                if app_name == "video":
                    vid_mb = rem
                elif app_name == "browsing":
                    brw_mb = rem
                else:
                    oth_mb = rem

    consume_from_packages(active_pkgs)

    # Check if any active package exhausted all its quota
    exhausted_subs = []
    addon_subs = []
    remaining_pkgs = []
    rng_addon = make_rng(cfg["seed"], "addon", n, clock_index)

    for prow in active_pkgs:
        if is_quota_exhausted(prow):
            pdef = pkg_lookup.get(prow["package_id"])
            if pdef:
                exhausted_subs.append((prow, pdef))
                price = float(pdef["price_pkr"])
                can_afford = (not is_prepaid) or (balance >= price)
                if can_afford and rng_addon.random() < ADDON_BUY_CHANCE:
                    if is_prepaid:
                        balance = round(balance - price, 2)
                    refilled = init_active_package_row(
                        cid, prow["subscription_id"], pdef, clock_index, prow["auto_renew"]
                    )
                    addon_subs.append((refilled, pdef))
                    remaining_pkgs.append(refilled)
        else:
            remaining_pkgs.append(prow)

    # If an addon was bought in this band, consume remaining uncovered usage from it
    if addon_subs:
        consume_from_packages([r for r, _ in addon_subs])

    # Remaining uncovered usage is charged out-of-bundle
    oob_cost = (
        onnet * RATE_ONNET_MIN
        + offnet * RATE_OFFNET_MIN
        + intl * RATE_INTL_MIN
        + sms * RATE_SMS
        + (wa_mb + soc_mb + vid_mb + brw_mb + oth_mb) * RATE_DATA_MB
    )

    if is_prepaid and oob_cost > balance:
        # Scale down the uncovered portion proportionally so balance stops at 0.0
        scale = balance / oob_cost if oob_cost > 0 else 0.0
        old_minutes = (
            usage_event["calls_onnet_min"]
            + usage_event["calls_offnet_min"]
            + usage_event["calls_intl_min"]
        )
        usage_event["calls_onnet_min"] = int(round(usage_event["calls_onnet_min"] - onnet * (1.0 - scale)))
        usage_event["calls_offnet_min"] = int(round(usage_event["calls_offnet_min"] - offnet * (1.0 - scale)))
        usage_event["calls_intl_min"] = int(round(usage_event["calls_intl_min"] - intl * (1.0 - scale)))
        usage_event["sms_count"] = int(round(usage_event["sms_count"] - sms * (1.0 - scale)))
        usage_event["data_mb_whatsapp"] = round(max(0.0, usage_event["data_mb_whatsapp"] - wa_mb * (1.0 - scale)), 2)
        usage_event["data_mb_social"] = round(max(0.0, usage_event["data_mb_social"] - soc_mb * (1.0 - scale)), 2)
        usage_event["data_mb_video"] = round(max(0.0, usage_event["data_mb_video"] - vid_mb * (1.0 - scale)), 2)
        usage_event["data_mb_browsing"] = round(max(0.0, usage_event["data_mb_browsing"] - brw_mb * (1.0 - scale)), 2)
        usage_event["data_mb_other"] = round(max(0.0, usage_event["data_mb_other"] - oth_mb * (1.0 - scale)), 2)
        new_minutes = (
            usage_event["calls_onnet_min"]
            + usage_event["calls_offnet_min"]
            + usage_event["calls_intl_min"]
        )
        if old_minutes > 0:
            usage_event["dropped_calls"] = int(
                round(usage_event["dropped_calls"] * new_minutes / old_minutes)
            )
        else:
            usage_event["dropped_calls"] = 0
        spend_from_balance = round(balance, 2)
        balance = 0.0
    elif is_prepaid:
        spend_from_balance = round(oob_cost, 2)
        balance = round(max(0.0, balance - spend_from_balance), 2)
    else:
        # Postpaid: balance stays 0.0; spend_from_balance records billed amount
        spend_from_balance = round(oob_cost, 2)
        balance = 0.0

    usage_event["active_package_ids"] = active_ids
    usage_event["spend_from_package"] = round(pkg_used_value, 2)
    usage_event["spend_from_balance"] = spend_from_balance

    return balance, remaining_pkgs, exhausted_subs, addon_subs