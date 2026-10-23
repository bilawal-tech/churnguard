import csv
import hashlib

from simulator.common import ROOT

CSV_PATH = ROOT / "config" / "reference" / "operator_packages.csv"
TYPE_CODE = {"combo": "CMB", "social": "SOC", "voice": "VOI", "data": "DAT"}
TIERS = ["Lite", "Standard", "Plus", "Pro", "Max"]
APPS = ["TikTok", "YouTube", "Instagram", "Snapchat", "WhatsApp"]


def _int(x):
    x = (x or "").strip()
    return int(float(x)) if x else 0


def _region(s):
    s = (s or "").strip()
    if s in ("", "all", "check"):
        return ["all"]
    return [x.strip() for x in s.split(";") if x.strip()]


def _total_min(p):
    return (p["quota_onnet_min"] + p["quota_offnet_min"]
            + p["quota_anynet_min"] + p["quota_intl_min"])


def _package_type(p):
    has_data = p["quota_data_mb"] > 0
    has_social = p["quota_social_mb"] > 0
    has_voice = _total_min(p) > 0
    has_sms = p["quota_sms"] > 0
    if has_social and not has_data and not has_voice:
        return "social"
    if has_voice and not has_data and not has_social:
        return "voice"
    if has_data and not has_voice and not has_social and not has_sms:
        return "data"
    return "combo"


def _validity_label(days):
    return {1: "Daily", 3: "3-Day", 7: "Weekly", 30: "Monthly"}.get(days, f"{days}-Day")


def _size_label(mb):
    return f"{round(mb / 1024)}GB" if mb >= 1024 else f"{mb}MB"


def _base_name(p):
    val = _validity_label(p["validity_days"])
    t = p["package_type"]
    if t == "social":
        note = p["_note"].lower()
        app = next((a for a in APPS if a.lower() in note), "Multi")
        return f"{val} Social {app}"
    if t == "voice":
        return f"{val} Voice {_total_min(p)}min"
    if t == "data":
        night = " Night" if p["night_only"] else ""
        return f"{val} Data{night} {_size_label(p['quota_data_mb'])}"
    if p["quota_data_mb"] > 0:
        size = _size_label(p["quota_data_mb"])
    elif p["quota_social_mb"] > 0:
        size = _size_label(p["quota_social_mb"]) + " Social"
    else:
        size = f"{_total_min(p)}min"
    return f"{val} Combo {size}"


def build_packages(csv_path=CSV_PATH):
    """operator_packages.csv se hamare apne naam aur stable package_id wale packages banata hai."""
    pkgs = []
    with open(csv_path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            p = {
                "price_pkr": _int(r["price_pkr"]),
                "validity_days": _int(r["validity_days"]),
                "quota_onnet_min": _int(r["onnet_min"]),
                "quota_offnet_min": _int(r["offnet_min"]),
                "quota_anynet_min": _int(r["any_net_min"]),
                "quota_intl_min": _int(r["intl_min"]),
                "quota_sms": _int(r["sms"]),
                "quota_data_mb": _int(r["data_mb"]),
                "quota_social_mb": _int(r["social_mb"]),
                "night_only": r["night_only"].strip() == "1",
                "region": _region(r["region"]),
                "_source": r["source_name"].strip(),
                "_note": r["note"] or "",
            }
            p["package_type"] = _package_type(p)
            h = hashlib.sha256(p["_source"].encode("utf-8")).hexdigest()[:4]
            p["package_id"] = f"P_{TYPE_CODE[p['package_type']]}_{p['validity_days']}D_{h}"
            p["name"] = _base_name(p)
            p["auto_renew_allowed"] = True
            p["min_balance_required"] = p["price_pkr"]
            pkgs.append(p)

    # same naam wale packages ko price ke hisaab se tier dena
    groups = {}
    for p in pkgs:
        groups.setdefault(p["name"], []).append(p)
    for name, g in groups.items():
        if len(g) == 1:
            continue
        if len(g) > len(TIERS):
            raise ValueError(f"'{name}' ke {len(g)} packages hain, tiers sirf {len(TIERS)}")
        g.sort(key=lambda p: (p["price_pkr"], _total_min(p) + p["quota_sms"], p["package_id"]))
        for tier, p in zip(TIERS, g):
            p["name"] = f"{name} {tier}"

    ids = [p["package_id"] for p in pkgs]
    if len(ids) != len(set(ids)):
        raise ValueError("package_id mein takrao (hash collision)")

    for p in pkgs:
        p.pop("_source")
        p.pop("_note")
    return sorted(pkgs, key=lambda p: p["package_id"])