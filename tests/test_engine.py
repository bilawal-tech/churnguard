import copy
import json

import pytest

from simulator.core.engine import Simulator
from simulator.core.state_store import StateStore

CFG = {
    "seed": 42,
    "start_date": "2026-04-01",
    "history_days": 5,
    "live_speed_sim_hours_per_real_sec": 2.0,
    "ids": {
        "customer_prefix": "C", "customer_width": 7,
        "tower_prefix": "T", "tower_width": 5,
    },
}


def one_event(ctx):
    return [("test_events", {"band": ctx.clock.index})]


def test_backfill_runs_and_stops(tmp_path):
    s = StateStore(tmp_path / "s.db")
    sim = Simulator(CFG, s, tmp_path / "out")
    assert sim.run() == 20
    assert s.get_meta("index") == "20"


def test_stop_and_resume(tmp_path):
    p = tmp_path / "s.db"
    Simulator(CFG, StateStore(p), tmp_path / "out").run(stop_after=7)
    s2 = StateStore(p)
    assert s2.get_meta("index") == "7"
    assert Simulator(CFG, s2, tmp_path / "out").run() == 20


def test_events_written_once_per_band(tmp_path):
    s = StateStore(tmp_path / "s.db")
    Simulator(CFG, s, tmp_path / "out", hooks=[one_event]).run()
    lines = (tmp_path / "out" / "test_events.jsonl").read_text().splitlines()
    assert [json.loads(x)["band"] for x in lines] == list(range(20))


def test_crash_keeps_last_good_index(tmp_path):
    def bad(ctx):
        if ctx.clock.index == 3:
            raise RuntimeError("crash")
        return []

    s = StateStore(tmp_path / "s.db")
    with pytest.raises(RuntimeError):
        Simulator(CFG, s, tmp_path / "out", hooks=[bad]).run()
    assert s.get_meta("index") == "3"


def test_live_waits_between_bands(tmp_path):
    cfg = copy.deepcopy(CFG)
    cfg["history_days"] = 0
    waits = []
    s = StateStore(tmp_path / "s.db")
    Simulator(cfg, s, tmp_path / "out", sleep=waits.append).run(
        live=True, stop_after=2
    )
    assert waits == [3.0, 3.0]