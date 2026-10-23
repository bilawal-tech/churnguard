import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (student project; contact: bilawalazeemnavtac@gmail.com)"}

for site in ["https://jazz.com.pk", "https://propakistani.pk"]:
    r = requests.get(site + "/robots.txt", headers=HEADERS, timeout=20)
    print("=====", site, "robots.txt:", r.status_code)
    print(r.text[:800])

url = "https://propakistani.pk/packages/jazz-monthly-freedom/"
r = requests.get(url, headers=HEADERS, timeout=20)
print("=====", url, r.status_code, len(r.text))
print("price text milta hai:", "2608" in r.text or "2,608" in r.text)