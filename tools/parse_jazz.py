import csv
import re
from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup

RAW = Path("data/reference/jazz_raw")
REF = Path("data/reference")

NUM = r"(\d[\d,]*(?:\.\d+)?)"
STOP = re.compile(r"(OVERVIEW|Product Specific|Offer Details|Terms\s*&\s*Conditions|General Terms)", re.I)


def num(s):
    return float(s.replace(",", ""))


def mb(val, unit):
    v = num(val)
    return v * 1024 if unit.upper() == "GB" else v


def page_texts(html):
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style"]):
        t.decompose()
    h3 = soup.find("h3")
    strings = h3.find_all_next(string=True) if h3 else soup.find_all(string=True)
    parts = []
    for s in strings:
        x = str(s).replace("\u200b", " ").replace("\xa0", " ").strip()
        if x:
            parts.append(x)
    full = " ".join(parts)
    m = STOP.search(full)
    top = full[: m.start()] if m else full[:400]
    return full, top


def parse_validity(full):
    m = re.search(r"Validity\s+(.{0,45})", full)
    s = m.group(1) if m else ""
    low = s.lower()
    m = re.search(r"x\s*\+\s*(\d+)", low)
    if m:
        return int(m.group(1)) + 1
    m = re.search(r"(\d+)\s*days?", low)
    if m:
        return int(m.group(1))
    if "month" in low:
        return 30
    if "week" in low:
        return 7
    if "daily" in low:
        return 1
    return None


def parse_quota(top):
    out = {"data_mb": None, "social_mb": None, "jazz_min": None,
           "other_net_min": None, "all_net_min": None, "intl_min": None, "sms": None}
    notes = []

    m = re.search(NUM + r"\s*(GB|MB)\s*data", top, re.I)
    if m:
        out["data_mb"] = mb(m.group(1), m.group(2))
    m = re.search(NUM + r"\s*(GB|MB)\s*(TikTok|YouTube|Instagram|Snapchat|Facebook|WhatsApp|Social)", top, re.I)
    if m:
        out["social_mb"] = mb(m.group(1), m.group(2))
    m = re.search(NUM + r"\s*(?:Jazz|On-?net)\s*Min(?:ute)?s?", top, re.I)
    if m:
        out["jazz_min"] = int(num(m.group(1)))
    m = re.search(NUM + r"\s*(?:Other\s*Network|Off-?net)\s*Min(?:ute)?s?", top, re.I)
    if m:
        out["other_net_min"] = int(num(m.group(1)))
    m = re.search(NUM + r"\s*All\s*Network\s*Min(?:ute)?s?", top, re.I)
    if m:
        out["all_net_min"] = int(num(m.group(1)))
    m = re.search(NUM + r"\s*International\s*Min(?:ute)?s?", top, re.I)
    if m:
        out["intl_min"] = int(num(m.group(1)))

    m = re.search(NUM + r"\s*(?:Jazz|On-?net)\s*Mins?\s*(?:&|and)?\s*SMS", top, re.I)
    if m:
        n = int(num(m.group(1)))
        out["jazz_min"] = n
        out["sms"] = n
        notes.append("sms assumed equal to minutes")
    else:
        m = re.search(NUM + r"\s*(?:Jazz\s*)?SMS", top, re.I)
        if m:
            out["sms"] = int(num(m.group(1)))
    return out, notes


def main():
    with open(REF / "jazz_listing.csv", encoding="utf-8") as f:
        listing = {r["url"]: r for r in csv.DictReader(f)}
    with open(REF / "jazz_packages.csv", encoding="utf-8") as f:
        pkgs = list(csv.DictReader(f))

    rows = []
    for p in pkgs:
        slug = p["url"].rstrip("/").split("/")[-1]
        path = RAW / f"detail_{slug}.html"
        if not path.exists():
            print("html nahi mili:", slug)
            continue
        full, top = page_texts(path.read_text(encoding="utf-8"))

        m = re.search(r"Subscription Fee\s*Rs\.?\s*" + NUM, full)
        price = num(m.group(1)) if m else None
        if price is None:
            lp = listing.get(p["url"], {}).get("price_value")
            price = float(lp) if lp else None

        q, notes = parse_quota(top)
        vdays = parse_validity(full)
        low = top.lower()
        review = (
            all(v is None for v in q.values())
            or price is None
            or vdays is None
            or bool(notes)
            or "unlimited" in low
            or "insurance" in low
            or "healthcare" in low
        )
        rows.append({
            "name": p["name"], "url": p["url"], "price_incl_tax": price,
            "validity_days": vdays, **q,
            "notes": "; ".join(notes), "needs_review": review,
            "quota_text": top[:250], "collected_date": date.today().isoformat(),
        })

    fields = ["name", "url", "price_incl_tax", "validity_days", "data_mb", "social_mb",
              "jazz_min", "other_net_min", "all_net_min", "intl_min", "sms",
              "notes", "needs_review", "quota_text", "collected_date"]
    with open(REF / "jazz_packages_v2.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    print("rows:", len(rows), "| review:", sum(1 for r in rows if r["needs_review"]))
    for r in rows:
        print(r["name"], "|", r["price_incl_tax"], "|", r["validity_days"], "d |",
              r["data_mb"], "MB |", r["social_mb"], "| jazz", r["jazz_min"],
              "| other", r["other_net_min"], "| all", r["all_net_min"],
              "| intl", r["intl_min"], "| sms", r["sms"],
              "| REVIEW" if r["needs_review"] else "")


if __name__ == "__main__":
    main()