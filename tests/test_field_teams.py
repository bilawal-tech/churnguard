import copy

from simulator.common import load_config
from simulator.masters.field_teams import build_field_teams
from simulator.masters.towers import CITY_CENTERS, build_towers


def make(cfg=None):
    return build_field_teams(cfg or load_config("config_test.yaml"))


def test_count_matches_config():
    cfg = load_config("config_test.yaml")
    expected = sum(v["teams"] for v in cfg["geography"].values())
    assert len(make(cfg)) == expected


def test_ids_unique():
    ids = [t["team_id"] for t in make()]
    assert len(ids) == len(set(ids))


def test_same_seed_same_data():
    assert make() == make()


def test_zone_matches_location():
    for t in make():
        lat0, lon0 = CITY_CENTERS[t["city"]]
        ns = "N" if t["base_lat"] >= lat0 else "S"
        ew = "E" if t["base_lon"] >= lon0 else "W"
        assert t["zone"] == f"{t['city']}-{ns}{ew}"


def test_adding_teams_keeps_old_ones():
    cfg = load_config("config_test.yaml")
    bigger = copy.deepcopy(cfg)
    bigger["geography"]["Karachi"]["teams"] += 3
    old = {t["team_id"]: t for t in build_field_teams(cfg)}
    new = {t["team_id"]: t for t in build_field_teams(bigger)}
    for tid, t in old.items():
        assert new[tid] == t


def test_every_tower_city_has_a_team():
    cfg = load_config("config_test.yaml")
    team_cities = {t["city"] for t in build_field_teams(cfg)}
    assert {t["city"] for t in build_towers(cfg)} <= team_cities

    