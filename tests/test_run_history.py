import json
import pytest

from simulator.core.state_store import StateStore
from simulator.lifecycle import model as lifecycle_model
from simulator.run_history import TOPICS, main


@pytest.fixture(autouse=True)
def _fast_lifecycle_for_2day_smoke_test(monkeypatch):
    monkeypatch.setattr(lifecycle_model, "BASE_DAILY_CHURN", 0.05)
    monkeypatch.setattr(lifecycle_model, "INACTIVE_SUSPEND_DAYS", 2)
    monkeypatch.setattr(lifecycle_model, "INACTIVE_CHURN_DAYS", 4)
    monkeypatch.setattr(lifecycle_model, "REACTIVATE_CHANCE_PER_DAY", 0.3)


def run_args(out_dir, db_path, *extra):
    return [
        "--config", "config_test.yaml",
        "--out-dir", str(out_dir),
        "--db-path", str(db_path),
        "--days", "2",
        *extra,
    ]


def test_full_bounded_run_creates_masters_and_events(tmp_path):
    out_dir = tmp_path / "raw"
    db_path = tmp_path / "state" / "sim.db"

    assert main(run_args(out_dir, db_path)) == 0

    assert {
        "tower_master",
        "packages_master",
        "field_teams_master",
    } <= {path.name for path in out_dir.iterdir() if path.is_dir()}
    for topic in TOPICS:
        lines = (out_dir / f"{topic}.jsonl").read_text(encoding="utf-8").splitlines()
        assert lines
        assert all(isinstance(json.loads(line), dict) for line in lines)


def test_rerun_resumes_without_duplicating_output(tmp_path):
    out_dir = tmp_path / "raw"
    db_path = tmp_path / "state" / "sim.db"
    args = run_args(out_dir, db_path)

    main(args)
    before = {topic: (out_dir / f"{topic}.jsonl").read_text(encoding="utf-8")
              for topic in TOPICS}
    main(args)

    after = {topic: (out_dir / f"{topic}.jsonl").read_text(encoding="utf-8")
             for topic in TOPICS}
    assert after == before
    store = StateStore(db_path)
    try:
        assert store.get_meta("index") == "8"
    finally:
        store.close()


def test_reset_recreates_identical_deterministic_output(tmp_path):
    out_dir = tmp_path / "raw"
    db_path = tmp_path / "state" / "sim.db"
    args = run_args(out_dir, db_path)

    main(args)
    first = {
        topic: (out_dir / f"{topic}.jsonl").read_text(encoding="utf-8")
        for topic in TOPICS
    }
    main(run_args(out_dir, db_path, "--reset"))

    second = {
        topic: (out_dir / f"{topic}.jsonl").read_text(encoding="utf-8")
        for topic in TOPICS
    }
    assert second == first
