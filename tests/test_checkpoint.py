import copy

import pytest

from simulator.core.checkpoint import Checkpoint, ConfigMismatchError
from simulator.core.state_store import StateStore

CFG = {
    "seed": 42,
    "start_date": "2026-04-01",
    "history_days": 180,
    "ids": {
        "customer_prefix": "C", "customer_width": 7,
        "tower_prefix": "T", "tower_width": 5,
    },
}


def test_new_run_starts_at_zero(tmp_path):
    s = StateStore(tmp_path / "s.db")
    cp = Checkpoint(s, CFG)
    assert cp.start() == 0
    assert s.get_meta("config_hash") == cp.fingerprint
    assert cp.next_customer_no() == 1


def test_resume_gives_saved_index(tmp_path):
    p = tmp_path / "s.db"
    s = StateStore(p)
    cp = Checkpoint(s, CFG)
    cp.start()
    with s.transaction():
        cp.save(300, 20001)
    s.close()
    cp2 = Checkpoint(StateStore(p), CFG)
    assert cp2.start() == 300
    assert cp2.next_customer_no() == 20001


def test_seed_change_stops(tmp_path):
    p = tmp_path / "s.db"
    Checkpoint(StateStore(p), CFG).start()
    bad = copy.deepcopy(CFG)
    bad["seed"] = 7
    with pytest.raises(ConfigMismatchError):
        Checkpoint(StateStore(p), bad).start()


def test_scale_change_is_allowed(tmp_path):
    p = tmp_path / "s.db"
    Checkpoint(StateStore(p), CFG).start()
    scaled = copy.deepcopy(CFG)
    scaled["history_days"] = 365
    assert Checkpoint(StateStore(p), scaled).start() == 0


def test_save_rolls_back_with_state(tmp_path):
    s = StateStore(tmp_path / "s.db")
    cp = Checkpoint(s, CFG)
    cp.start()
    try:
        with s.transaction():
            cp.save(5, 99)
            raise RuntimeError("crash")
    except RuntimeError:
        pass
    assert cp.start() == 0