import json
from collections import Counter

import pytest

from ingestion.producer import EventProducer
from ingestion.replay import load_checkpoint, replay_jsonl
from ingestion.settings import IngestionSettings


class FakeFuture:
    def get(self, timeout=None):
        return None


class FakeKafkaProducer:
    def __init__(self, send_failures=None, fail_flush=False):
        self.send_failures = Counter(send_failures or {})
        self.send_attempts = Counter()
        self.sent = []
        self.flush_calls = 0
        self.closed = False
        self.fail_flush = fail_flush

    def send(self, topic, key=None, value=None):
        event_id = value.get("event_id") if isinstance(value, dict) else None
        self.send_attempts[event_id] += 1
        if self.send_failures[event_id] > 0:
            self.send_failures[event_id] -= 1
            raise RuntimeError(f"send failed for {event_id}")
        self.sent.append({"topic": topic, "key": key, "value": value})
        return FakeFuture()

    def flush(self):
        self.flush_calls += 1
        if self.fail_flush:
            raise RuntimeError("flush failed")

    def close(self):
        self.closed = True


def settings():
    return IngestionSettings()


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            record if isinstance(record, str) else json.dumps(record) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )


def event(topic, event_id, customer_id="C0000001"):
    record = {"event_id": event_id}
    if topic == "network_events":
        record["region"] = "Lahore"
    elif topic == "tower_metrics_events":
        record["tower_id"] = "T01001"
    else:
        record["customer_id"] = customer_id
    return record


def event_producer(fake, dlq_dir, max_retries=3):
    return EventProducer(
        settings(), producer=fake, dlq_dir=dlq_dir, max_retries=max_retries
    )


def test_normal_replay_sends_records_from_multiple_topics(tmp_path):
    raw_dir = tmp_path / "raw"
    customer = event("customer_events", "customer-1")
    outage = event("network_events", "network-1")
    write_jsonl(raw_dir / "customer_events.jsonl", [customer])
    write_jsonl(raw_dir / "network_events.jsonl", [outage])
    fake = FakeKafkaProducer()

    stats = replay_jsonl(
        settings(),
        producer=event_producer(fake, tmp_path / "dlq"),
        raw_dir=raw_dir,
        checkpoint_path=tmp_path / "checkpoint.json",
        topics=["customer_events", "network_events"],
    )

    assert stats == {
        "customer_events": {"sent": 1, "dlq": 0, "skipped": 0},
        "network_events": {"sent": 1, "dlq": 0, "skipped": 0},
    }
    assert fake.sent == [
        {"topic": "customer_events", "key": "C0000001", "value": customer},
        {"topic": "network_events", "key": "Lahore", "value": outage},
    ]


def test_replay_resumes_from_checkpoint_without_duplicate_sends(tmp_path):
    raw_dir = tmp_path / "raw"
    topic = "usage_events"
    records = [event(topic, f"usage-{index}") for index in range(4)]
    write_jsonl(raw_dir / f"{topic}.jsonl", records)
    checkpoint = tmp_path / "checkpoint.json"
    fake = FakeKafkaProducer()
    producer = event_producer(fake, tmp_path / "dlq")

    first = replay_jsonl(
        settings(), producer=producer, raw_dir=raw_dir,
        checkpoint_path=checkpoint, topics=[topic], limit=2,
    )
    assert first[topic]["sent"] == 2
    assert load_checkpoint(checkpoint)[f"{topic}.jsonl"] == 2

    second = replay_jsonl(
        settings(), producer=producer, raw_dir=raw_dir,
        checkpoint_path=checkpoint, topics=[topic],
    )

    assert second[topic] == {"sent": 2, "dlq": 0, "skipped": 2}
    assert [item["value"]["event_id"] for item in fake.sent] == [
        "usage-0", "usage-1", "usage-2", "usage-3",
    ]


def test_failed_flush_does_not_advance_checkpoint(tmp_path):
    raw_dir = tmp_path / "raw"
    topic = "usage_events"
    write_jsonl(raw_dir / f"{topic}.jsonl", [event(topic, "usage-1")])
    checkpoint = tmp_path / "checkpoint.json"
    fake = FakeKafkaProducer(fail_flush=True)

    with pytest.raises(RuntimeError, match="flush failed"):
        replay_jsonl(
            settings(),
            producer=event_producer(fake, tmp_path / "dlq"),
            raw_dir=raw_dir,
            checkpoint_path=checkpoint,
            topics=[topic],
        )

    assert load_checkpoint(checkpoint) == {}
    assert not checkpoint.exists()


def test_malformed_and_send_failed_records_go_to_dlq(tmp_path):
    raw_dir = tmp_path / "raw"
    topic = "usage_events"
    valid_before = event(topic, "valid-before")
    failed = event(topic, "failed")
    valid_after = event(topic, "valid-after")
    write_jsonl(
        raw_dir / f"{topic}.jsonl",
        [valid_before, "{malformed json}\n", failed, valid_after],
    )
    dlq_dir = tmp_path / "dlq"
    fake = FakeKafkaProducer(send_failures={"failed": 3})

    stats = replay_jsonl(
        settings(),
        producer=event_producer(fake, dlq_dir),
        raw_dir=raw_dir,
        checkpoint_path=tmp_path / "checkpoint.json",
        topics=[topic],
        chunk_size=4,
    )

    assert stats[topic] == {"sent": 2, "dlq": 2, "skipped": 0}
    assert [item["value"]["event_id"] for item in fake.sent] == [
        "valid-before", "valid-after",
    ]
    assert fake.send_attempts["failed"] == 3
    assert load_checkpoint(tmp_path / "checkpoint.json")[f"{topic}.jsonl"] == 4
    dlq_records = [
        json.loads(line)
        for line in (dlq_dir / f"producer_{topic}.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert len(dlq_records) == 2
    assert any(record["raw"] == "{malformed json}" for record in dlq_records)
    assert any(record.get("record") == failed for record in dlq_records)
