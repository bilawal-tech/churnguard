from simulator.core.engine import BandContext, Simulator
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


def producer(ctx):
    return [("a_events", {"band": ctx.clock.index})]


def test_band_context_defaults():
    ctx = BandContext(None, None, 1)
    assert ctx.band_events == []
    assert ctx.band_events_for("a_events") == []


def test_later_hook_sees_earlier_events(tmp_path):
    seen = []

    def watcher(ctx):
        seen.append(ctx.band_events_for("a_events"))
        return []

    s = StateStore(tmp_path / "s.db")
    Simulator(CFG, s, tmp_path / "out", hooks=[producer, watcher]).run(stop_after=2)
    assert seen == [[{"band": 0}], [{"band": 1}]]


def test_first_hook_sees_nothing(tmp_path):
    seen = []

    def watcher(ctx):
        seen.append(list(ctx.band_events))
        return []

    s = StateStore(tmp_path / "s.db")
    Simulator(CFG, s, tmp_path / "out", hooks=[watcher, producer]).run(stop_after=2)
    assert seen == [[], []]


def test_other_topic_is_empty(tmp_path):
    seen = []

    def watcher(ctx):
        seen.append(ctx.band_events_for("zzz_events"))
        return []

    s = StateStore(tmp_path / "s.db")
    Simulator(CFG, s, tmp_path / "out", hooks=[producer, watcher]).run(stop_after=1)
    assert seen == [[]]