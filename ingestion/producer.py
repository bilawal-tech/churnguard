"""Kafka producer and producer-side dead-letter writing."""
import json
import threading
from pathlib import Path

from kafka import KafkaProducer

from ingestion.settings import IngestionSettings
from ingestion.topics import key_for


class EventProducer:
    def __init__(
        self,
        settings: IngestionSettings,
        producer=None,
        dlq_dir: str | Path | None = None,
        max_retries: int = 3,
    ):
        if max_retries < 1:
            raise ValueError("max_retries must be at least 1")
        self.settings = settings
        self.dlq_dir = Path(
            dlq_dir if dlq_dir is not None else settings.producer_dlq_dir
        )
        self.max_retries = max_retries
        self.owns_producer = producer is None
        self._dlq_lock = threading.Lock()
        self._async_dlq_counts: dict[str, int] = {}
        self.producer = (
            producer
            if producer is not None
            else KafkaProducer(
                bootstrap_servers=settings.bootstrap_servers,
                acks="all",
                retries=max_retries,
                linger_ms=50,
                batch_size=262144,
                key_serializer=lambda key: key.encode("utf-8") if key is not None else None,
                value_serializer=lambda value: json.dumps(
                    value, ensure_ascii=False
                ).encode("utf-8"),
            )
        )

    def _write_dlq(self, topic: str, record: dict) -> None:
        with self._dlq_lock:
            self.dlq_dir.mkdir(parents=True, exist_ok=True)
            path = self.dlq_dir / f"producer_{topic}.jsonl"
            with path.open("a", encoding="utf-8") as dlq_file:
                dlq_file.write(json.dumps(record, ensure_ascii=False) + "\n")

    def send_event(self, topic: str, event: dict, async_batch: bool = False) -> bool:
        try:
            key = key_for(topic, event)
        except ValueError as exc:
            self._write_dlq(topic, {
                "topic": topic,
                "error": str(exc),
                "record": event,
            })
            return False

        if async_batch and self.owns_producer:
            def _on_error(exc):
                self._write_dlq(topic, {
                    "topic": topic,
                    "error": str(exc),
                    "record": event,
                })
                with self._dlq_lock:
                    self._async_dlq_counts[topic] = self._async_dlq_counts.get(topic, 0) + 1

            try:
                future = self.producer.send(topic, key=key, value=event)
                add_errback = getattr(future, "add_errback", None)
                if callable(add_errback):
                    add_errback(_on_error)
                return True
            except Exception as exc:
                _on_error(exc)
                return False

        last_error = None
        for _ in range(self.max_retries):
            try:
                result = self.producer.send(topic, key=key, value=event)
                get_result = getattr(result, "get", None)
                if callable(get_result):
                    get_result(timeout=10)
                return True
            except Exception as exc:
                last_error = exc

        self._write_dlq(topic, {
            "topic": topic,
            "error": str(last_error),
            "record": event,
        })
        return False

    def pop_async_dlq_count(self, topic: str) -> int:
        with self._dlq_lock:
            return self._async_dlq_counts.pop(topic, 0)

    def write_dlq_raw(self, topic: str, raw_line: str, error: str) -> None:
        self._write_dlq(topic, {
            "topic": topic,
            "error": error,
            "raw": raw_line,
        })

    def flush(self) -> None:
        self.producer.flush()

    def close(self) -> None:
        if self.owns_producer:
            self.flush()
            self.producer.close()

