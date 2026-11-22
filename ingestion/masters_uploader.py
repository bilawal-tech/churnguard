"""Upload local master JSONL snapshots to S3."""
import argparse
import gzip
from datetime import datetime, timezone
from pathlib import Path

import boto3

from ingestion.settings import IngestionSettings
from ingestion.settings import load_settings as load_ingestion_settings


def _s3_key(root: str, *parts: str) -> str:
    return "/".join(part.strip("/") for part in (root, *parts) if part.strip("/"))


def upload_masters(
    settings: IngestionSettings,
    raw_dir: str | Path | None = None,
    snapshot_date: str | None = None,
    s3_client=None,
) -> dict[str, dict[str, int | str]]:
    source_dir = Path(raw_dir if raw_dir is not None else settings.raw_data_dir)
    date_partition = snapshot_date or datetime.now(timezone.utc).date().isoformat()
    client = (
        s3_client
        if s3_client is not None
        else boto3.client("s3", region_name=settings.s3_region)
    )
    summary = {}
    if not source_dir.is_dir():
        return summary

    for master_dir in sorted(source_dir.iterdir()):
        if not master_dir.is_dir():
            continue
        master_name = master_dir.name
        jsonl_path = master_dir / f"{master_name}.jsonl"
        if not jsonl_path.is_file():
            continue

        payload = jsonl_path.read_bytes()
        compressed = gzip.compress(payload)
        s3_key = _s3_key(
            settings.s3_root,
            "masters",
            master_name,
            f"snapshot_date={date_partition}",
            f"{master_name}.jsonl.gz",
        )
        client.put_object(
            Bucket=settings.s3_bucket,
            Key=s3_key,
            Body=compressed,
            ContentType="application/x-ndjson",
            ContentEncoding="gzip",
        )
        summary[master_name] = {
            "s3_key": s3_key,
            "records": sum(
                1 for line in payload.splitlines() if line.strip()
            ),
            "bytes_gz": len(compressed),
        }

    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--raw-dir")
    parser.add_argument("--snapshot-date")
    args = parser.parse_args(argv)

    settings = load_ingestion_settings(args.config)
    summary = upload_masters(
        settings,
        raw_dir=args.raw_dir,
        snapshot_date=args.snapshot_date,
    )
    for master_name, result in summary.items():
        print(
            f"{master_name}: {result['records']} records -> "
            f"s3://{settings.s3_bucket}/{result['s3_key']} "
            f"({result['bytes_gz']} compressed bytes)"
        )
    return summary


if __name__ == "__main__":
    main()
