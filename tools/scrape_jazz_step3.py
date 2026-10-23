import csv
import re
import time
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (student project)"}
RAW = Path("data/reference/jazz_raw")
REF = Path("data/reference")


def clean(s):
    return s.replace("\u200b", "").strip()


def parse_detail(html):
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style"]):
        t.decompose()
    lines = [clean(x) for x in soup.get_text("\n").split("\n")]
    lines = [x for x in lines if x]
    text = " ".join(lines)

    quota = ""
    for i, x in enumerate(lines):
        if x.lower().startswith("rs"):
            quota = lines[i - 1] if i else ""
            break

    fee = re.search(r"Subscription Fee\s*Rs\.?\s*([\d,]+(?:\.\d+)?)", text)
    price = float(fee.group(1).replace(",", "")) if fee else None

    v = re.search(r"Validity\s+(.+?)\s+(?:Status|Bundle|Subscription|Product|OVERVIEW|Overview|Terms|Rs)", text)
    vtext = v.group(1).strip() if v else ""
    low = vtext.lower()
    vdays = None
    if "month" in low:
        vdays = 30
    elif "week" in low:
        vdays = 7
    elif "daily" in low:
        vdays = 1
    else:
        m = re.search(r"(\d+)\s*day", low)
        vdays = int(m.group(1)) if m else None

    data_mb = None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(GB|MB)\s*data", quota, re.I)
    if m:
        val = float(m.group(1))
        data_mb = val * 1024 if m.group(2).upper() == "GB" else val
    m = re.search(r"(\d+)\s*Jazz\s*Min", quota, re.I)
    jazz_min = int(m.group(1)) if m else None
    m = re.search(r"(\d+)\s*Other\s*Network\s*Min", quota, re.I)
    other_min = int(m.group(1)) if m else None
    m = re.search(r"(\d+)\s*SMS", quota, re.I)
    sms = int(m.group(1)) if m else None

    return {
        "price_incl_tax": price, "validity_text": vtext, "validity_days": vdays,
        "data_mb": data_mb, "jazz_min": jazz_min, "other_net_min": other_min,
        "sms": sms, "quota_line": quota,
    }


def main():
    with open(REF / "jazz_listing.csv", encoding="utf-8") as f:
        listing = list(csv.DictReader(f))

    cands = []
    for r in listing:
        pv = float(r["price_value"]) if r["price_value"] else None
        name = r["name"].lower()
        if pv is None or "/" in r["price_text"] or not (20 <= pv <= 3000):
            continue
        if "roaming" in name or "hajj" in name:
            continue
        cands.append(r)
    print("candidates:", len(cands))

    rows = []
    for r in cands:
        slug = r["url"].rstrip("/").split("/")[-1]
        path = RAW / f"detail_{slug}.html"
        if not path.exists():
            resp = requests.get(r["url"], headers=HEADERS, timeout=30)
            path.write_text(resp.text, encoding="utf-8")
            time.sleep(2)
        info = parse_detail(path.read_text(encoding="utf-8"))
        ql = info["quota_line"].lower()
        review = (
            all(info[k] is None for k in ("data_mb", "jazz_min", "other_net_min", "sms"))
            or ("sms" in ql and info["sms"] is None)
            or info["validity_days"] is None
            or "unlimited" in ql
        )
        row = {"name": r["name"], "url": r["url"],
               "collected_date": date.today().isoformat(),
               "needs_review": review, **info}
        rows.append(row)

    fields = ["name", "url", "price_incl_tax", "validity_text", "validity_days",
              "data_mb", "jazz_min", "other_net_min", "sms", "quota_line",
              "needs_review", "collected_date"]
    with open(REF / "jazz_packages.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    print("rows:", len(rows), "| review chahiye:", sum(1 for x in rows if x["needs_review"]))
    for x in rows:
        print(x["name"], "|", x["price_incl_tax"], "|", x["validity_days"], "d |",
              x["data_mb"], "MB |", x["jazz_min"], "|", x["other_net_min"], "|", x["sms"],
              "| REVIEW" if x["needs_review"] else "")
    print("----- review wali quota lines -----")
    for x in rows:
        if x["needs_review"]:
            print(x["name"], "->", x["quota_line"])


if __name__ == "__main__":
    main()