from types import SimpleNamespace

from simulator.common import load_config
from simulator.core.clock import SimClock
from simulator.core.state_store import StateStore
from simulator.masters.towers import add_neighbors, build_towers
from simulator.usage.generator import build_usage_event, neighbor_map
from simulator.usage.hook import make_usage_hook

CFG = load_config("config_test.yaml")
CLOCK = SimClock.from_config(CFG, index=3)
NEIGH = {"T00001": ["T00002", "T00003"]}


def cid(n):
    return f"C{n:07d}"


def ev(n, health=None, neighbors=NEIGH):
    return build_usage_event(CFG, cid(n), "T00001", neighbors, CLOCK,
                             tower_health=health)


def total_dropped(health, neighbors=NEIGH, n=300):
    return sum(ev(i, health, neighbors)["dropped_calls"] for i in range(1, n + 1))


def same(state):
    return {"T00001": state, "T00002": state, "T00003": state}


def test_healthy_or_missing_health_changes_nothing():
    healthy = same("HEALTHY")
    for i in range(1, 40):
        base = build_usage_event(CFG, cid(i), "T00001", NEIGH, CLOCK)
        assert ev(i, None) == base
        assert ev(i, {}) == base
        assert ev(i, healthy) == base


def test_down_home_tower_shifts_to_neighbor():
    health = {"T00001": "DOWN", "T00002": "HEALTHY", "T00003": "HEALTHY"}
    for i in range(1, 60):
        assert ev(i, health)["tower_id"] in ("T00002", "T00003")


def test_all_towers_down_stays_put():
    health = same("DOWN")
    for i in range(1, 40):
        base = build_usage_event(CFG, cid(i), "T00001", NEIGH, CLOCK)
        assert ev(i, health)["tower_id"] == base["tower_id"]


def test_single_tower_city_stays_on_down_tower_with_more_drops():
    alone = {}
    down = {"T00001": "DOWN"}
    for i in range(1, 40):
        assert ev(i, down, alone)["tower_id"] == "T00001"
    healthy_total = total_dropped({"T00001": "HEALTHY"}, alone)
    down_total = total_dropped(down, alone)
    assert down_total > 5 * healthy_total


def test_worse_health_means_more_dropped_calls():
    h = total_dropped(same("HEALTHY"))
    d = total_dropped(same("DEGRADED"))
    c = total_dropped(same("CRITICAL"))
    assert h < d < c


def test_deterministic():
    health = same("CRITICAL")
    assert ev(7, health) == ev(7, health)


def test_hook_reads_tower_state(tmp_path):
    towers = add_neighbors(build_towers(CFG))
    home = next(t["tower_id"] for t in towers if t["neighbor_tower_ids"])
    near = neighbor_map(towers)[home]
    store = StateStore(tmp_path / "s.db")
    store.upsert_customers([{
        "customer_id": cid(1), "plan_type": "prepaid", "status": "ACTIVE",
        "status_since": 0, "balance": 100.0, "home_tower_id": home,
        "last_active": 0, "at_risk": 0,
    }])
    store.upsert_towers([{
        "tower_id": home, "health": "DOWN", "load": 0.0, "signal_dbm": -75.0,
    }])
    ctx = SimpleNamespace(store=store, clock=CLOCK)
    out = make_usage_hook(CFG, towers)(ctx)
    assert len(out) == 1
    assert out[0][1]["tower_id"] in near