import numpy as np
import math

from simulator.common import make_rng, tower_id

# Shehron ke markaz (lat, lon) aur zones. Ye andazan hain, asli map jaisay exact nahi.
CITY_CENTERS = {
    "Karachi": (24.86, 67.01),
    "Lahore": (31.52, 74.36),
    "Islamabad_Rawalpindi": (33.68, 73.05),
    "Faisalabad": (31.42, 73.08),
    "Peshawar": (34.01, 71.52),
    "Multan": (30.20, 71.47),
    "Quetta": (30.18, 66.99),
    "Other_cities": (25.40, 68.36),
}
CITY_NO = {city: i for i, city in enumerate(CITY_CENTERS, start=1)}
RADIUS_KM = 15
KM_PER_DEG = 111.0

TOWER_TYPES = ["3G", "4G", "5G"]
TYPE_WEIGHTS = [0.15, 0.65, 0.20]
CAPACITY_RANGE = {"3G": (150, 300), "4G": (300, 600), "5G": (500, 900)}


def build_towers(cfg):
    """Config ke geography ke hisaab se towers ki list banata hai.
    Har tower ka apna seed hai, is liye towers barhane par purane nahi badalte."""
    seed = cfg["seed"]
    towers = []
    for city, spec in cfg["geography"].items():
        lat0, lon0 = CITY_CENTERS[city]
        for i in range(spec["towers"]):
            tid = tower_id(cfg, CITY_NO[city] * 1000 + i + 1)
            rng = make_rng(seed, "tower", tid)

            # markaz ke aas paas random jagah (gol ilaqa, ~RADIUS_KM)
            angle = rng.uniform(0, 2 * np.pi)
            dist = RADIUS_KM * np.sqrt(rng.uniform(0, 1))
            lat = lat0 + (dist * np.sin(angle)) / KM_PER_DEG
            lon = lon0 + (dist * np.cos(angle)) / (KM_PER_DEG * np.cos(np.radians(lat0)))

            ttype = str(rng.choice(TOWER_TYPES, p=TYPE_WEIGHTS))
            lo, hi = CAPACITY_RANGE[ttype]
            capacity = int(rng.integers(lo, hi + 1))
            ns = "N" if lat >= lat0 else "S"
            ew = "E" if lon >= lon0 else "W"
            zone = f"{city}-{ns}{ew}"
            install_days_ago = int(rng.integers(365, 365 * 8))

            towers.append({
                "tower_id": tid,
                "region": city,
                "city": city,
                 "zone": zone,
                "lat": round(float(lat), 5),
                "lon": round(float(lon), 5),
                "tower_type": ttype,
                "capacity_users": capacity,
                "install_days_ago": install_days_ago,
            })
    return towers


def _distance_km(a, b):
    """Do towers ke beech ka seedha faasla (haversine), km mein."""
    r = 6371.0
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dp = p2 - p1
    dl = math.radians(b["lon"] - a["lon"])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))



#  distance of neighbours is calculated using haversine formula
  
def add_neighbors(towers, k=3):
    """Har tower ke sab se qareebi k towers, sirf usi shehar ke.
    Shehar mein towers kam hon to utne hi neighbors milte hain."""
    by_city = {}
    for t in towers:
        by_city.setdefault(t["city"], []).append(t)

    for t in towers:
        others = [o for o in by_city[t["city"]] if o["tower_id"] != t["tower_id"]]
        others.sort(key=lambda o: (_distance_km(t, o), o["tower_id"]))
        t["neighbor_tower_ids"] = [o["tower_id"] for o in others[:k]]
    return towers