from simulator.core.clock import SimClock
from simulator.core.engine import Simulator
from simulator.core.state_store import StateStore
from simulator.dirty.model import NULLABLE_FIELDS_BY_TOPIC
from simulator.dirty.processor import make_dirty_processor


CFG = {
    "seed": 42,
    "start_date": "2026-04-01",
    "history_days": 2,
    "live_speed_sim_hours_per_real_sec": 2.0,
    "ids": {
        "customer_prefix": "C", "customer_width": 7,
        "tower_prefix": "T", "tower_width": 5,
    },
}
TOPICS = tuple(NULLABLE_FIELDS_BY_TOPIC)
ENVELOPE = {
    "event_time": "2026-04-01T00:00:00+05:00",
    "schema_version": "1.0",
    "source": "simulator",
}


def dirty_cfg(**settings):
    cfg = dict(CFG)
    cfg["dirty_data"] = {
        "enabled": True,
        "null_rate": 0.0,
        "duplicate_rate": 0.0,
        "late_rate": 0.0,
        "late_max_hours": 24,
        **settings,
    }
    return cfg


def context(store, band_index):
    return type("Context", (), {
        "clock": SimClock.from_config(CFG, index=band_index),
        "store": store,
    })()


def test_delayed_events_wait_until_due_and_pop_in_insertion_order(tmp_path):
    store = StateStore(tmp_path / "store.db")
    first = {"event_id": "first"}
    second = {"event_id": "second"}
    store.add_delayed_event(3, "test_events", first)
    store.add_delayed_event(3, "test_events", second)

    assert store.pop_delayed_events(0) == []
    assert store.pop_delayed_events(1) == []
    assert store.pop_delayed_events(2) == []
    assert store.pop_delayed_events(3) == [
        ("test_events", first), ("test_events", second),
    ]
    assert store.pop_delayed_events(3) == []


def test_disabled_and_zero_rate_processors_preserve_events(tmp_path):
    event = {"event_id": "event-1", **ENVELOPE}
    events = [("test_events", event)]
    store = StateStore(tmp_path / "store.db")

    disabled = make_dirty_processor(dirty_cfg(enabled=False))
    assert disabled(context(store, 0), events) is events

    no_op = make_dirty_processor(dirty_cfg())
    assert no_op(context(store, 0), events) == events


def test_null_injection_only_changes_nullable_non_key_fields(tmp_path):
    store = StateStore(tmp_path / "store.db")
    processor = make_dirty_processor(dirty_cfg(null_rate=1.0))
    events = []
    expected_fields = []
    for topic, fields in NULLABLE_FIELDS_BY_TOPIC.items():
        for index, field in enumerate(fields):
            payload = {
                **ENVELOPE,
                "event_id": f"{topic}-{index}",
                "customer_id": "C0000001",
                "offer_id": "OFR-C0000001-0-DATA_BOOST",
                "outage_id": "OUT-T01001-0",
                "subscription_id": "SUB-C0000001-0",
                field: "not-null",
            }
            events.append((topic, payload))
            expected_fields.append((topic, payload["event_id"], field))

    output = processor(context(store, 0), events)
    output_by_id = {event["event_id"]: event for _, event in output}
    for topic, event_id, field in expected_fields:
        original = next(e for t, e in events if t == topic and e["event_id"] == event_id)
        processed = output_by_id[event_id]
        assert processed[field] is None
        assert all(processed[key] == original[key] for key in (
            "event_id", "event_time", "schema_version", "source",
            "customer_id", "offer_id", "outage_id", "subscription_id",
        ))


def test_duplicate_rate_emits_identical_event_twice(tmp_path):
    store = StateStore(tmp_path / "store.db")
    processor = make_dirty_processor(
        dirty_cfg(duplicate_rate=1.0, late_rate=0.0)
    )
    event = {"event_id": "event-1", **ENVELOPE, "value": 7}

    output = processor(context(store, 0), [("test_events", event)])

    assert output == [("test_events", event), ("test_events", event)]
    assert output[0][1]["event_id"] == output[1][1]["event_id"]


def test_late_events_are_delivered_with_original_payload(tmp_path):
    store = StateStore(tmp_path / "store.db")
    processor = make_dirty_processor(
        dirty_cfg(late_rate=1.0, late_max_hours=24)
    )
    events = [
        ("test_events", {
            "event_id": f"event-{index}",
            **ENVELOPE,
            "sequence": index,
        })
        for index in range(12)
    ]

    assert processor(context(store, 0), events) == []
    delivered = []
    for band in range(1, 5):
        delivered.extend(processor(context(store, band), []))

    assert len(delivered) == len(events)
    expected_by_id = {event["event_id"]: event for _, event in events}
    for _, event in delivered:
        assert event == expected_by_id[event["event_id"]]
        assert event["event_time"] == ENVELOPE["event_time"]


def test_dirty_simulation_is_deterministic_after_stop_and_resume(tmp_path):
    cfg = dirty_cfg(
        null_rate=1.0, duplicate_rate=1.0, late_rate=1.0,
        late_max_hours=24,
    )

    def produce_band_events(ctx):
        return [
            (topic, {
                **ENVELOPE,
                "event_id": f"{topic}-{ctx.clock.index}",
                "event_time": ctx.clock.band_start.isoformat(),
                "customer_id": "C0000001",
                NULLABLE_FIELDS_BY_TOPIC[topic][0]: "value",
            })
            for topic in TOPICS
        ]

    continuous_store = StateStore(tmp_path / "continuous.db")
    continuous_out = tmp_path / "continuous"
    Simulator(
        cfg, continuous_store, continuous_out,
        hooks=[produce_band_events],
        post_hooks=[make_dirty_processor(cfg)],
    ).run(stop_after=8)

    resumed_store_path = tmp_path / "resumed.db"
    resumed_out = tmp_path / "resumed"
    first_store = StateStore(resumed_store_path)
    Simulator(
        cfg, first_store, resumed_out,
        hooks=[produce_band_events],
        post_hooks=[make_dirty_processor(cfg)],
    ).run(stop_after=3)
    first_store.close()
    resumed_store = StateStore(resumed_store_path)
    Simulator(
        cfg, resumed_store, resumed_out,
        hooks=[produce_band_events],
        post_hooks=[make_dirty_processor(cfg)],
    ).run()

    for topic in TOPICS:
        continuous = (continuous_out / f"{topic}.jsonl").read_text(
            encoding="utf-8"
        )
        resumed = (resumed_out / f"{topic}.jsonl").read_text(encoding="utf-8")
        assert resumed == continuous

    continuous_store.close()
    resumed_store.close()
