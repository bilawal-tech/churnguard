import copy

from simulator.common import load_config
from simulator.masters.towers import build_towers, add_neighbors


def make(cfg=None):
    cfg = cfg or load_config("config_test.yaml")
    return add_neighbors(build_towers(cfg))


def test_count_matches_config():
    cfg = load_config("config_test.yaml")
    expected = sum(v["towers"] for v in cfg["geography"].values())
    assert len(make(cfg)) == expected


def test_ids_unique():
    ids = [t["tower_id"] for t in make()]
    assert len(ids) == len(set(ids))


def test_same_seed_same_data():
    assert make() == make()


def test_neighbors_valid():
    towers = make()
    by = {t["tower_id"]: t for t in towers}
    for t in towers:
        n = t["neighbor_tower_ids"]
        assert t["tower_id"] not in n
        assert len(n) <= 3
        assert all(by[x]["city"] == t["city"] for x in n)


def test_adding_towers_keeps_old_ones():
    cfg = load_config("config_test.yaml")
    bigger = copy.deepcopy(cfg)
    bigger["geography"]["Karachi"]["towers"] += 5
    old = {t["tower_id"]: t for t in build_towers(cfg)}
    new = {t["tower_id"]: t for t in build_towers(bigger)}
    for tid, t in old.items():
    	assert new[tid] == t   

def test_zone_matches_location():
    from simulator.masters.towers import CITY_CENTERS
    for t in make():
        lat0, lon0 = CITY_CENTERS[t["city"]]
        ns = "N" if t["lat"] >= lat0 else "S"
        ew = "E" if t["lon"] >= lon0 else "W"
        assert t["zone"] == f"{t['city']}-{ns}{ew}"