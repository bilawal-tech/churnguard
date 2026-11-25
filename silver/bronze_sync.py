from __future__ import annotations

import argparse
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import boto3

from silver.settings import (
    EVENT_TOPICS,
    MASTER_TABLES,
    SilverSettings,
    load_silver_settings,
)


@dataclass(frozen=True)
class SyncItem:
    s3_key: str
    local_path: Path
    size_bytes: int


@dataclass(frozen=True)
class SyncSummary:
    total_files: int
    skipped_files: int
    downloaded_files: int
    downloaded_bytes: int


def list_bronze_objects(
    s3_client,
    settings: SilverSettings,
    topics: tuple[str, ...] = EVENT_TOPICS,
    masters: tuple[str, ...] = MASTER_TABLES,
) -> list[SyncItem]:
    items: list[SyncItem] = []
    paginator = s3_client.get_paginator("list_objects_v2")
    raw_prefix = settings.s3_raw_prefix

    prefixes: list[str] = [f"{raw_prefix}/events/{t}/" for t in topics]
    prefixes.extend(f"{raw_prefix}/masters/{m}/" for m in masters)

    for prefix in prefixes:
        for page in paginator.paginate(Bucket=settings.s3_bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith("/"):
                    continue
                rel_key = key[len(raw_prefix) + 1 :] if key.startswith(f"{raw_prefix}/") else key
                local_path = settings.bronze_dir / Path(rel_key)
                items.append(
                    SyncItem(
                        s3_key=key,
                        local_path=local_path,
                        size_bytes=int(obj["Size"]),
                    )
                )
    return items


def _download_one(s3_client, bucket: str, item: SyncItem) -> tuple[bool, int]:
    if item.local_path.exists() and item.local_path.stat().st_size == item.size_bytes:
        return False, 0

    item.local_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = item.local_path.with_name(item.local_path.name + ".part")
    if part_path.exists():
        part_path.unlink()

    s3_client.download_file(bucket, item.s3_key, str(part_path))
    os.replace(part_path, item.local_path)
    return True, item.size_bytes


def sync_bronze(
    settings: SilverSettings | None = None,
    topics: tuple[str, ...] = EVENT_TOPICS,
    masters: tuple[str, ...] = MASTER_TABLES,
    workers: int = 8,
    s3_client=None,
) -> SyncSummary:
    cfg = settings or load_silver_settings()
    client = s3_client or boto3.client("s3", region_name=cfg.s3_region)

    items = list_bronze_objects(client, cfg, topics=topics, masters=masters)
    skipped = 0
    downloaded = 0
    downloaded_bytes = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_download_one, client, cfg.s3_bucket, item): item
            for item in items
        }
        for idx, future in enumerate(as_completed(futures), start=1):
            was_downloaded, n_bytes = future.result()
            if was_downloaded:
                downloaded += 1
                downloaded_bytes += n_bytes
            else:
                skipped += 1
            if idx % 250 == 0 or idx == len(items):
                print(
                    f"[bronze_sync] {idx}/{len(items)} files "
                    f"(downloaded={downloaded}, skipped={skipped}, "
                    f"new={downloaded_bytes / 1024**2:.1f} MB)"
                )

    return SyncSummary(
        total_files=len(items),
        skipped_files=skipped,
        downloaded_files=downloaded,
        downloaded_bytes=downloaded_bytes,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync S3 Bronze raw/ to local data/bronze/")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--bronze-dir", default=None)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    cfg = load_silver_settings(config_path=args.config, bronze_dir=args.bronze_dir)
    summary = sync_bronze(settings=cfg, workers=args.workers)
    print(
        f"DONE: total={summary.total_files}, downloaded={summary.downloaded_files}, "
        f"skipped={summary.skipped_files}, downloaded_mb={summary.downloaded_bytes / 1024**2:.2f}"
    )


if __name__ == "__main__":
    main()