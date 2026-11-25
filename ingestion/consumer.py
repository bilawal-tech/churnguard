"""Consume Kafka event topics and write partitioned Bronze batches to S3."""
import argparse
import gzip
import json
import math
import re
import time
import uuid
from collections import defaultdict
from datetime import date, datetime, timezone

import boto3
from kafka import KafkaConsumer

from ingestion.settings import IngestionSettings
from ingestion.settings import load_settings as load_ingestion_settings
from ingestion.topics import EVENT_TOPICS

_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIMESTAMP_FIELDS = ("event_date", "event_time", "event_ts", "timestamp", "ts", "created_at")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _date_from_event(event: dict, fallback: date) -> str:
    for field in _TIMESTAMP_FIELDS:
        value = event.get(field)
        if not isinstance(value, str):
            continue
        prefix = value[:10]
        if not _DATE_PREFIX.fullmatch(prefix):
            continue
        try:
            return date.fromisoformat(prefix).isoformat()
        except ValueError:
            continue
    return fallback.isoformat()


def _raw_value(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return str(value)


def _s3_key(root: str, *parts: str) -> str:
    return "/".join(part.strip("/") for part in (root, *parts) if part.strip("/"))


def _gzip_ndjson(records: list[dict]) -> bytes:
    text = "".join(
        json.dumps(record, ensure_ascii=False) + "\n"
        for record in records
    )
    return gzip.compress(text.encode("utf-8"))


class S3BronzeConsumer:
    def __init__(
        self,
        settings: IngestionSettings,
        consumer=None,
        s3_client=None,
    ):
        self.settings = settings
        self.owns_consumer = consumer is None
        self.consumer = (
            consumer
            if consumer is not None
            else KafkaConsumer(
                *EVENT_TOPICS,
                bootstrap_servers=settings.bootstrap_servers,
                group_id=settings.consumer_group,
                enable_auto_commit=False,
                auto_offset_reset="earliest",
            )
        )
        self.s3_client = (
            s3_client
            if s3_client is not None
            else boto3.client("s3", region_name=settings.s3_region)
        )

    @staticmethod
    def _messages_from_poll(polled):
        for records in polled.values():
            yield from records

    def _upload_batch(self, messages):
        event_groups = defaultdict(list)
        dlq_groups = defaultdict(list)
        utc_now = _utc_now()
        fallback_date = utc_now.date()

        for message in messages:
            raw_value = _raw_value(message.value)
            try:
                event = json.loads(message.value)
            except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
                dlq_groups[fallback_date.isoformat()].append({
                    "topic": message.topic,
                    "partition": message.partition,
                    "offset": message.offset,
                    "error": str(exc),
                    "raw_value": raw_value,
                    "ingested_at": utc_now.isoformat(),
                })
                continue

            if not isinstance(event, dict):
                dlq_groups[fallback_date.isoformat()].append({
                    "topic": message.topic,
                    "partition": message.partition,
                    "offset": message.offset,
                    "error": "JSON payload is not an object",
                    "raw_value": raw_value,
                    "ingested_at": utc_now.isoformat(),
                })
                continue

            dt = _date_from_event(event, fallback_date)
            event.setdefault("ingest_time", utc_now.isoformat())
            event_groups[(message.topic, dt)].append(event)

        uploads = 0
        for (topic, dt), records in event_groups.items():
            batch_id = f"{_utc_now().strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
            key = _s3_key(
                self.settings.s3_root,
                "events",
                topic,
                f"dt={dt}",
                f"batch_{batch_id}.jsonl.gz",
            )
            self.s3_client.put_object(
                Bucket=self.settings.s3_bucket,
                Key=key,
                Body=_gzip_ndjson(records),
                ContentType="application/x-ndjson",
                ContentEncoding="gzip",
            )
            uploads += 1

        for dt, records in dlq_groups.items():
            batch_id = f"{_utc_now().strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
            key = _s3_key(
                self.settings.s3_root,
                "dlq",
                f"dt={dt}",
                f"batch_{batch_id}.jsonl.gz",
            )
            self.s3_client.put_object(
                Bucket=self.settings.s3_bucket,
                Key=key,
                Body=_gzip_ndjson(records),
                ContentType="application/x-ndjson",
                ContentEncoding="gzip",
            )
            uploads += 1

        return uploads, sum(map(len, event_groups.values())), sum(
            map(len, dlq_groups.values())
        )

    def run(
        self,
        max_batches: int | None = None,
        batch_records: int | None = None,
        batch_seconds: float | None = None,
        idle_timeout_ms: int = 1000,
    ) -> dict[str, int]:
        record_limit = (
            batch_records
            if batch_records is not None
            else self.settings.batch_records
        )
        time_limit = (
            batch_seconds
            if batch_seconds is not None
            else self.settings.batch_seconds
        )
        if record_limit < 1:
            raise ValueError("batch_records must be at least 1")
        if time_limit <= 0:
            raise ValueError("batch_seconds must be greater than 0")
        if idle_timeout_ms < 0:
            raise ValueError("idle_timeout_ms cannot be negative")
        if max_batches is not None and max_batches < 0:
            raise ValueError("max_batches cannot be negative")

        summary = {"batches": 0, "records": 0, "dlq": 0, "uploads": 0}
        idle_seconds = idle_timeout_ms / 1000
        last_activity = time.monotonic()

        while max_batches is None or summary["batches"] < max_batches:
            batch_started = time.monotonic()
            messages = []
            while len(messages) < record_limit:
                now = time.monotonic()
                batch_remaining = time_limit - (now - batch_started)
                idle_remaining = idle_seconds - (now - last_activity)
                if batch_remaining <= 0 or idle_remaining <= 0:
                    break

                timeout_ms = max(
                    1,
                    math.ceil(min(batch_remaining, idle_remaining) * 1000),
                )
                polled = self.consumer.poll(
                    timeout_ms=timeout_ms,
                    max_records=record_limit - len(messages),
                ) or {}
                new_messages = list(self._messages_from_poll(polled))
                if new_messages:
                    messages.extend(new_messages)
                    last_activity = time.monotonic()

            if not messages:
                if time.monotonic() - last_activity >= idle_seconds:
                    break
                continue

            uploads, event_count, dlq_count = self._upload_batch(messages)
            self.consumer.commit()
            summary["batches"] += 1
            summary["records"] += event_count
            summary["dlq"] += dlq_count
            summary["uploads"] += uploads

        return summary

    def close(self) -> None:
        if self.owns_consumer:
            self.consumer.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--max-batches", type=int)
    parser.add_argument("--batch-records", type=int)
    parser.add_argument("--batch-seconds", type=float)
    parser.add_argument("--idle-timeout-ms", type=int, default=1000)
    args = parser.parse_args(argv)

    settings = load_ingestion_settings(args.config)
    consumer = S3BronzeConsumer(settings)
    try:
        summary = consumer.run(
            max_batches=args.max_batches,
            batch_records=args.batch_records,
            batch_seconds=args.batch_seconds,
            idle_timeout_ms=args.idle_timeout_ms,
        )
    finally:
        consumer.close()
    print(
        f"Batches: {summary['batches']}, records: {summary['records']}, "
        f"DLQ: {summary['dlq']}, S3 objects: {summary['uploads']}"
    )
    return summary


if __name__ == "__main__":
    main()
