# Step 12: S3 Bronze

## Overview
Is step mein master snapshots aur Kafka event batches S3 Bronze layer mein gzip NDJSON ke taur par save hote hain. Bucket `s3://churnguard-data-bilawal/raw/` aur region `ap-south-1` hai. Masters snapshot date se partition hote hain; events aur DLQ UTC date se. Is se raw data baad ke Silver processing ke liye mehfooz rehta hai.

## S3 layout

| Data | S3 key |
|---|---|
| Masters | `raw/masters/<master_name>/snapshot_date=YYYY-MM-DD/<master_name>.jsonl.gz` |
| Events | `raw/events/<topic>/dt=YYYY-MM-DD/batch_<utc>_<uuid8>.jsonl.gz` |
| DLQ | `raw/dlq/dt=YYYY-MM-DD/batch_<utc>_<uuid8>.jsonl.gz` |

Master snapshots `tower_master`, `packages_master` aur `field_teams_master` ke liye hain. Event files mein topic ke JSON records newline-delimited hote hain. Har batch ka UTC timestamp aur UUID ka pehla 8-character hissa object name ko alag rakhta hai.

## Files
| File | Kaam |
|---|---|
| `ingestion/settings.py` | S3 bucket, region, root aur batching settings |
| `ingestion/masters_uploader.py` | Master JSONL snapshots ko gzip karke S3 upload |
| `ingestion/consumer.py` | Kafka events ko date aur topic ke hisaab se S3 par likhta hai |
| `tests/test_ingest_s3_bronze.py` | Fake S3/Kafka clients ke saath upload, partition, DLQ aur commit tests |

## Master upload
`ingestion/masters_uploader.py` `<raw_dir>/<master_name>/<master_name>.jsonl` files dhoondta hai. Har file memory mein gzip hoti hai aur `application/x-ndjson` content type aur `gzip` encoding ke saath snapshot key par upload hoti hai. `--snapshot-date` na diya ho to aaj ki UTC tareekh istemal hoti hai.

## Kafka consumer aur batching
`ingestion/consumer.py` topics se micro-batches poll karta hai. Default hadd `batch_records=5000` records ya `batch_seconds=60` seconds hai. `--idle-timeout-ms` khali topics par bounded run ko saaf taur par khatam karne deta hai; `--max-batches` bhi run ko mahdood kar sakta hai.

Event ki `dt` tareekh `event_ts`, `timestamp`, `ts`, ya `created_at` ke ISO date prefix se nikalti hai. Agar koi valid tareekh na mile to current UTC date lagti hai. Valid event dictionaries topic aur `dt` ke mutabiq group hote hain aur gzip NDJSON mein upload hote hain. Corrupt ya non-dictionary payload DLQ mein jata hai; DLQ record mein topic, partition, offset, error, raw value aur `ingested_at` hota hai.

## At-least-once delivery
Kafka offsets ka `consumer.commit()` tabhi chalta hai jab us batch ke **tamam** S3 `put_object` calls kamyab ho jayein. Koi upload exception de to exception dobara raise hoti hai aur offsets commit nahi hote. Is se failed upload ke baad messages dobara mil sakte hain, yani delivery at-least-once hai.

## Commands
Master snapshots upload karne ke liye:

```powershell
python -m ingestion.masters_uploader --config config/config.yaml --raw-dir data/raw
```

Do batches tak consumer chalane aur idle par nikalne ke liye:

```powershell
python -m ingestion.consumer --config config/config.yaml --max-batches 2 --batch-records 5000 --batch-seconds 60 --idle-timeout-ms 1000
```

`boto3` se `raw/` ke uploaded objects dekhne ke liye:

```powershell
python -c "import boto3; c=boto3.client('s3', region_name='ap-south-1'); p=c.get_paginator('list_objects_v2'); print('\n'.join(o['Key'] for page in p.paginate(Bucket='churnguard-data-bilawal', Prefix='raw/') for o in page.get('Contents', [])))"
```

## Tests
- `tests/test_ingest_s3_bronze.py`: master gzip upload aur CLI, topic/date grouping, corrupt payload DLQ, upload ke baad commit, aur upload failure par commit na hona.
- Bronze tests: **5 pass**.
- `python -m pytest tests -q`: **288 total tests pass**.
