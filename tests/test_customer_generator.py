from collections import Counter

import pytest

from simulator.common import customer_id, load_config
from simulator.customers.generator import build_customer, towers_by_city
from simulator.masters.towers import build_towers


@pytest.fixture(scope="module")
def setup():
    cfg = load_config("config_test.yaml")
    towers = build_towers(cfg)
    return cfg, towers, towers_by_city(towers, cfg)


def test_same_n_same_customer(setup):
    cfg, _, tbc = setup
    assert build_customer(cfg, tbc, 5, 3) == build_customer(cfg, tbc, 5, 3)


def test_customers_vary(setup):
    cfg, _, tbc = setup
    rows = [build_customer(cfg, tbc, n, 0) for n in range(1, 201)]
    assert len({r["city"] for r in rows}) > 1
    assert len({r["balance"] for r in rows}) > 1


def test_fixed_fields(setup):
    cfg, _, tbc = setup
    c = build_customer(cfg, tbc, 7, 12)
    assert c["customer_id"] == customer_id(cfg, 7)
    assert c["status"] == "ACTIVE" and c["at_risk"] == 0
    assert c["status_since"] == 12 and c["last_active"] == 12


def test_home_tower_in_own_city(setup):
    cfg, towers, tbc = setup
    tower_city = {t["tower_id"]: t["city"] for t in towers}
    for n in range(1, 501):
        c = build_customer(cfg, tbc, n, 0)
        assert tower_city[c["home_tower_id"]] == c["city"]


def test_shares_match_config(setup):
    cfg, _, tbc = setup
    total = 10000
    rows = [build_customer(cfg, tbc, n, 0) for n in range(1, total + 1)]
    cities = Counter(r["city"] for r in rows)
    for name, g in cfg["geography"].items():
        assert abs(cities[name] / total - g["share"]) < 0.02
    prepaid = sum(r["plan_type"] == "prepaid" for r in rows) / total
    assert abs(prepaid - cfg["customers"]["prepaid_share"]) < 0.02
    for r in rows:
        if r["plan_type"] == "prepaid":
            assert 50 <= r["balance"] <= 500
        else:
            assert r["balance"] == 0.0


def test_missing_city_raises(setup):
    cfg, towers, _ = setup
    no_karachi = [t for t in towers if t["city"] != "Karachi"]
    with pytest.raises(ValueError):
        towers_by_city(no_karachi, cfg)