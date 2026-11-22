import gzip
import json
import re
import sys
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from ingestion import masters_uploader
from ingestion.consumer import S3BronzeConsumer
from ingestion.settings import IngestionSettings


class FakeS3Client:
    def __init__(self, order=None, fail=False):
        self.objects = []
        self.order = order if order is not None else []
        self.fail = fail

    def put_object(self, **kwargs):
        if self.fail:
            raise RuntimeError("S3 upload failed")
        self.objects.append(kwargs)
        self.order.append(("put", kwargs["Key"]))


class FakeKafkaProducer:
    def __init__(self, messages, order=None):
        self.messages = list(messages)
        self.order = order if order is not None else []
        self.commits = 0
        self.closed = False

    def poll(self, timeout_ms, max_records):
        if not self.messages:
            time.sleep(timeout_ms / 1000)
            return {}
        batch = self.messages[:max_records]
        self.messages = self.messages[max_records:]
        return {None: batch}

    def commit(self):
        self.commits += 1
        self.order.append(("commit", None))

    def close(self):
        self.closed = True


def bronze_settings(**overrides):
    values = {
        "s3_bucket": "test-bucket",
        "s3_region": "us-east-1",
        "s3_root": "bronze",
        "batch_records": 100,
        "batch_seconds": 1,
        "consumer_group": "test-consumer",
    }
    values.update(overrides)
    return IngestionSettings(**values)


def kafka_message(topic, offset, value, partition=0):
    return SimpleNamespace(
        topic=topic,
        partition=partition,
        offset=offset,
        value=value,
    )


def gunzip_records(body):
    return [
        json.loads(line)
        for line in gzip.decompress(body).decode("utf-8").splitlines()
    ]


def test_masters_uploader_discovers_uploads_and_counts_records(tmp_path):
    raw_dir = tmp_path / "raw"
    masters = {
        "tower_master": [
            {"tower_id": "T01001", "install_date": "2022-11-11"},
            {"tower_id": "T01002", "install_date": "2023-04-10"},
        ],
        "packages_master": [{"package_id": "P_DAT_7D_1234"}],
        "custom_master": [{"item_id": "X1"}],
    }
    for name, records in masters.items():
        path = raw_dir / name / f"{name}.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text(
            "".join(json.dumps(record) + "\n" for record in records),
            encoding="utf-8",
        )
    (raw_dir / "ignored" / "not_ignored.jsonl").parent.mkdir(parents=True)
    (raw_dir / "ignored" / "not_ignored.jsonl").write_text("{}\n", encoding="utf-8")
    s3 = FakeS3Client()

    result = masters_uploader.upload_masters(
        bronze_settings(), raw_dir, "2026-04-01", s3_client=s3
    )

    assert set(result) == set(masters)
    assert len(s3.objects) == len(masters)
    for uploaded in s3.objects:
        master_name = uploaded["Key"].split("/")[2]
        expected_key = (
            f"bronze/masters/{master_name}/snapshot_date=2026-04-01/"
            f"{master_name}.jsonl.gz"
        )
        assert uploaded["Key"] == expected_key
        assert uploaded["ContentType"] == "application/x-ndjson"
        assert uploaded["ContentEncoding"] == "gzip"
        records = [
            json.loads(line)
            for line in gzip.decompress(uploaded["Body"]).decode().splitlines()
        ]
        assert len(records) == result[master_name]["records"]
        assert result[master_name]["bytes_gz"] == len(uploaded["Body"])


def test_masters_uploader_cli(tmp_path, monkeypatch, capsys):
    raw_dir = tmp_path / "raw"
    path = raw_dir / "tower_master" / "tower_master.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text('{"tower_id":"T01001"}\n', encoding="utf-8")
    s3 = FakeS3Client()
    monkeypatch.setattr(
        masters_uploader,
        "load_ingestion_settings",
        lambda _: bronze_settings(),
    )
    monkeypatch.setattr(masters_uploader.boto3, "client", lambda *args, **kwargs: s3)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "masters_uploader",
            "--config", "config/config_test.yaml",
            "--raw-dir", str(raw_dir),
            "--snapshot-date", "2026-04-01",
        ],
    )

    summary = masters_uploader.main()

    assert summary["tower_master"]["records"] == 1
    assert "snapshot_date=2026-04-01" in capsys.readouterr().out


def test_consumer_partitions_events_and_commits_after_uploads():
    order = []
    messages = [
        kafka_message(
            "usage_events", 1,
            b'{"event_id":"u1","event_ts":"2026-04-01T10:00:00+05:00"}',
        ),
        kafka_message(
            "usage_events", 2,
            b'{"event_id":"u2","event_ts":"2026-04-02T10:00:00+05:00"}',
        ),
        kafka_message(
            "offer_events", 3,
            b'{"event_id":"o1","timestamp":"2026-04-01T10:00:00+05:00"}',
        ),
    ]
    consumer = FakeKafkaProducer(messages, order)
    s3 = FakeS3Client(order)
    worker = S3BronzeConsumer(bronze_settings(), consumer, s3)

    summary = worker.run(max_batches=1, idle_timeout_ms=1)

    keys = [item["Key"] for item in s3.objects]
    assert len(keys) == 3
    assert all(
        re.fullmatch(
            r"bronze/events/(usage_events|offer_events)/dt=2026-04-0[12]/"
            r"batch_\d{8}T\d{6}Z_[0-9a-f]{8}\.jsonl\.gz",
            key,
        )
        for key in keys
    )
    uploaded = {
        tuple(item["Key"].split("/")[2:4]): gunzip_records(item["Body"])
        for item in s3.objects
    }
    assert uploaded[("usage_events", "dt=2026-04-01")] == [
        {"event_id": "u1", "event_ts": "2026-04-01T10:00:00+05:00"}
    ]
    assert uploaded[("usage_events", "dt=2026-04-02")] == [
        {"event_id": "u2", "event_ts": "2026-04-02T10:00:00+05:00"}
    ]
    assert uploaded[("offer_events", "dt=2026-04-01")] == [
        {"event_id": "o1", "timestamp": "2026-04-01T10:00:00+05:00"}
    ]
    assert summary == {"batches": 1, "records": 3, "dlq": 0, "uploads": 3}
    assert consumer.commits == 1
    assert [action[0] for action in order] == ["put", "put", "put", "commit"]


def test_consumer_routes_corrupt_payloads_to_dlq_and_commits():
    today = datetime.now(timezone.utc).date().isoformat()
    messages = [
        kafka_message("usage_events", 1, b"{not-json"),
        kafka_message("offer_events", 2, b"[]"),
    ]
    consumer = FakeKafkaProducer(messages)
    s3 = FakeS3Client()
    worker = S3BronzeConsumer(bronze_settings(), consumer, s3)

    summary = worker.run(max_batches=1, idle_timeout_ms=1)

    assert len(s3.objects) == 1
    uploaded = s3.objects[0]
    assert re.fullmatch(
        rf"bronze/dlq/dt={today}/batch_\d{{8}}T\d{{6}}Z_[0-9a-f]{{8}}\.jsonl\.gz",
        uploaded["Key"],
    )
    records = gunzip_records(uploaded["Body"])
    assert len(records) == 2
    assert records[0]["topic"] == "usage_events"
    assert records[0]["partition"] == 0
    assert records[0]["offset"] == 1
    assert records[0]["raw_value"] == "{not-json"
    assert records[0]["ingested_at"].startswith(today)
    assert records[1]["topic"] == "offer_events"
    assert records[1]["error"] == "JSON payload is not an object"
    assert summary == {"batches": 1, "records": 0, "dlq": 2, "uploads": 1}
    assert consumer.commits == 1


def test_s3_upload_failure_does_not_commit_offsets():
    message = kafka_message(
        "usage_events", 1, b'{"event_id":"u1","event_date":"2026-04-01"}'
    )
    consumer = FakeKafkaProducer([message])
    s3 = FakeS3Client(fail=True)
    worker = S3BronzeConsumer(bronze_settings(), consumer, s3)

    with pytest.raises(RuntimeError, match="S3 upload failed"):
        worker.run(max_batches=1, idle_timeout_ms=1)

    assert consumer.commits == 0
