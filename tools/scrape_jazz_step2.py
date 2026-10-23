import csv
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (student project)"}
raw = Path("data/reference/jazz_raw")
ref = Path("data/reference")

html = (raw / "prepaid_data.html").read_text(encoding="utf-8")
soup = BeautifulSoup(html, "html.parser")

rows = []
for card in soup.select("div.offer-box"):
    parts = [card.select_one("h5.color-grey"), card.select_one("h4.color-red")]
    name = " ".join(p.get_text(" ", strip=True) for p in parts if p).strip()
    price_el = card.select_one("div.offer-price")
    price_text = price_el.get_text(" ", strip=True) if price_el else ""
    m = re.search(r"Rs\.?\s*([\d,]+(?:\.\d+)?)", price_text)
    price_value = float(m.group(1).replace(",", "")) if m else None
    a = card.select_one("a[href]")
    url = a["href"] if a else ""
    rows.append({"name": name, "price_text": price_text,
                 "price_value": price_value, "url": url})

with open(ref / "jazz_listing.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["name", "price_text", "price_value", "url"])
    w.writeheader()
    w.writerows(rows)

with_price = [r for r in rows if r["price_value"] is not None]
print("cards:", len(rows), "| price wale:", len(with_price))
for r in with_price[:15]:
    print(r["name"], "|", r["price_text"], "|", r["url"])

# 3 detail pages ka sample (dheere dheere)
samples = [
    "https://jazz.com.pk/prepaid/monthly-freedom",
    "https://jazz.com.pk/prepaid/weekly-super-max",
    "https://jazz.com.pk/prepaid/3-day-max-offer",
]
for u in samples:
    r = requests.get(u, headers=HEADERS, timeout=30)
    slug = u.rstrip("/").split("/")[-1]
    (raw / f"detail_{slug}.html").write_text(r.text, encoding="utf-8")
    i = r.text.find("Subscription Fee")
    print("=====", slug, r.status_code)
    print(r.text[max(0, i - 1500): i + 200])
    time.sleep(2)