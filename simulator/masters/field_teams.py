import numpy as np

from simulator.common import make_id, make_rng
from simulator.masters.towers import CITY_CENTERS, CITY_NO, KM_PER_DEG

RADIUS_KM = 8


def build_field_teams(cfg):
    """Config ke geography ke hisaab se field teams banata hai (fixed base location).
    Har team ka apna seed hai, is liye teams barhane par purani teams nahi badlti."""
    seed = cfg["seed"]
    teams = []
    for city, spec in cfg["geography"].items():
        lat0, lon0 = CITY_CENTERS[city]
        for i in range(spec["teams"]):
            tid = make_id("FT", 4, CITY_NO[city] * 100 + i + 1)
            rng = make_rng(seed, "team", tid)

            angle = rng.uniform(0, 2 * np.pi)
            dist = RADIUS_KM * np.sqrt(rng.uniform(0, 1))
            lat = lat0 + (dist * np.sin(angle)) / KM_PER_DEG
            lon = lon0 + (dist * np.cos(angle)) / (KM_PER_DEG * np.cos(np.radians(lat0)))

            ns = "N" if lat >= lat0 else "S"
            ew = "E" if lon >= lon0 else "W"
            teams.append({
                "team_id": tid,
                "region": city,
                "city": city,
                "zone": f"{city}-{ns}{ew}",
                "base_lat": round(float(lat), 5),
                "base_lon": round(float(lon), 5),
            })
    return teams