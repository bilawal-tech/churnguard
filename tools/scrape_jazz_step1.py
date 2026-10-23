import re
from pathlib import Path

import requests

URL = "https://jazz.com.pk/prepaid/data"
HEADERS = {"User-Agent": "Mozilla/5.0 (student project)"}

out = Path("data/reference/jazz_raw")
out.mkdir(parents=True, exist_ok=True)

r = requests.get(URL, headers=HEADERS, timeout=30)
print("status:", r.status_code, "size:", len(r.text))
(out / "prepaid_data.html").write_text(r.text, encoding="utf-8")

links = sorted(set(re.findall(r'href="([^"#?]*?/prepaid/[^"#?]+)"', r.text)))
print("prepaid links:", len(links))
prices = re.findall(r"Rs\.?\s?[\d,]+(?:\.\d+)?\s*\(Incl\. Tax\)", r.text)
print("price tags:", len(prices))

i = r.text.find("prepaid/monthly-freedom")
print("----- HTML ka hissa (Monthly Freedom card) -----")
print(r.text[max(0, i - 1200): i + 300])