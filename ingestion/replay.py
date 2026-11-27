"""Replay local event JSONL files to Kafka with resumable checkpoints."""
import argparse
import json
import os
from pathlib import Path
import time

from ingestion.producer import EventProducer
from ingestion.settings import IngestionSettings, load_settings
from ingestion.topics import EVENT_TOPICS


def load_checkpoint(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as checkpoint_file:
        return json.load(checkpoint_file)


def _replace_with_retry(src: Path, dst: Path, tries: int = 10, delay: float = 0.2) -> None:
    """Windows par file kabhi kabhi kuch der lock rehti hai (antivirus, indexer)."""
    for attempt in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(delay * (attempt + 1))


def save_checkpoint(path: Path, state: dict[str, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as checkpoint_file:
        json.dump(state, checkpoint_file, ensure_ascii=False)
    _replace_with_retry(temporary_path, path)


def replay_jsonl(
    settings: IngestionSettings,
    producer: EventProducer | None = None,
    raw_dir: str | Path | None = None,
    checkpoint_path: str | Path | None = None,
    topics: list[str] | None = None,
    limit: int | None = None,
    chunk_size: int = 1000,
) -> dict[str, dict[str, int]]:
    selected_topics = EVENT_TOPICS if topics is None else topics
    unknown_topics = [topic for topic in selected_topics if topic not in EVENT_TOPICS]
    if unknown_topics:
        raise ValueError(f"Unknown event topics: {unknown_topics}")
    if chunk_size < 1:
        raise ValueError("chunk_size must be at least 1")
    if limit is not None and limit < 0:
        raise ValueError("limit cannot be negative")

    source_dir = Path(raw_dir if raw_dir is not None else settings.raw_data_dir)
    state_path = Path(
        checkpoint_path
        if checkpoint_path is not None
        else settings.checkpoint_path
    )
    checkpoint = load_checkpoint(state_path)
    owns_producer = producer is None
    active_producer = producer if producer is not None else EventProducer(settings)
    stats = {
        topic: {"sent": 0, "dlq": 0, "skipped": 0}
        for topic in selected_topics
    }

    def process_chunk(topic, filename, chunk):
        for _, line in chunk:
            raw_line = line.rstrip("\r\n")
            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                active_producer.write_dlq_raw(topic, raw_line, str(exc))
                stats[topic]["dlq"] += 1
                continue

            if not isinstance(event, dict):
                active_producer.write_dlq_raw(
                    topic, raw_line, "JSON record must be an object"
                )
                stats[topic]["dlq"] += 1
            elif active_producer.send_event(topic, event, async_batch=True):
                stats[topic]["sent"] += 1
            else:
                stats[topic]["dlq"] += 1

        active_producer.flush()
        pop_dlq = getattr(active_producer, "pop_async_dlq_count", None)
        if callable(pop_dlq):
            async_failed = pop_dlq(topic)
            if async_failed:
                stats[topic]["sent"] = max(0, stats[topic]["sent"] - async_failed)
                stats[topic]["dlq"] += async_failed
        checkpoint[filename] = chunk[-1][0] + 1
        save_checkpoint(state_path, checkpoint)

    try:
        for topic in selected_topics:
            filename = f"{topic}.jsonl"
            input_path = source_dir / filename
            if not input_path.is_file():
                continue

            offset = checkpoint.get(filename, 0)
            chunk = []
            new_lines = 0
            with input_path.open(encoding="utf-8") as event_file:
                for line_number, line in enumerate(event_file):
                    if line_number < offset:
                        stats[topic]["skipped"] += 1
                        continue
                    if limit is not None and new_lines >= limit:
                        break

                    chunk.append((line_number, line))
                    new_lines += 1
                    if len(chunk) == chunk_size:
                        process_chunk(topic, filename, chunk)
                        chunk = []

                if chunk:
                    process_chunk(topic, filename, chunk)
    finally:
        if owns_producer:
            active_producer.close()

    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--raw-dir")
    parser.add_argument("--checkpoint")
    parser.add_argument("--topics")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--chunk-size", type=int, default=1000)
    args = parser.parse_args()

    selected_topics = (
        [topic.strip() for topic in args.topics.split(",") if topic.strip()]
        if args.topics is not None
        else None
    )
    stats = replay_jsonl(
        load_settings(args.config),
        raw_dir=args.raw_dir,
        checkpoint_path=args.checkpoint,
        topics=selected_topics,
        limit=args.limit,
        chunk_size=args.chunk_size,
    )
    for topic, topic_stats in stats.items():
        print(
            f"{topic}: sent {topic_stats['sent']}, "
            f"DLQ {topic_stats['dlq']}, skipped {topic_stats['skipped']}"
        )

    totals = {
        key: sum(topic_stats[key] for topic_stats in stats.values())
        for key in ("sent", "dlq", "skipped")
    }
    print(
        f"Total: sent {totals['sent']}, DLQ {totals['dlq']}, "
        f"skipped {totals['skipped']}"
    )


if __name__ == "__main__":
    main()

