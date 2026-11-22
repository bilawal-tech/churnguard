# Step 11: Kafka Ingestion

## Overview
Is step mein `data/raw` ke event JSONL files Kafka topics mein replay hote hain. `ingestion/replay.py` har line parhta hai aur `ingestion/producer.py` event ko key ke saath WSL2 ke Kafka 3.9 KRaft broker (`localhost:9092`) par bhejta hai. Is se local simulator output aage stream processing ke liye Kafka mein aa jata hai. Broker ki connectivity user verify kar chuka hai; pehle se maujood topics ko dobara nahi banaya ya badla jata.

## Files
| File | Kaam |
|---|---|
| `ingestion/settings.py` | YAML se Kafka, S3 aur ingestion settings |
| `ingestion/topics.py` | 9 event topics, Kafka keys aur raw partition values |
| `ingestion/kafka_admin.py` | Sirf missing Kafka topics banata hai |
| `ingestion/replay.py` | JSONL files ko checkpoint ke saath Kafka mein replay karta hai |
| `ingestion/producer.py` | Kafka send, retries aur producer-side DLQ |
| `tests/test_ingest_topics.py` | Topic keys, partitions aur settings |
| `tests/test_ingest_replay.py` | Replay, resume, flush aur DLQ |

## Configuration aur Topic Registry
`config/config.yaml` mein Kafka bootstrap `localhost:9092`, default `6` partitions aur replication factor `1` hai. Retention default 30 din (`2592000000` ms) hai. `ingestion/settings.py` in values ko load karta hai; `ingestion/topics.py` yeh 9 topics rakhta hai:

| Topic | Kafka key |
|---|---|
| `customer_events` | `customer_id` |
| `profile_events` | `customer_id` |
| `usage_events` | `customer_id` |
| `tower_metrics_events` | `tower_id` |
| `network_events` | `region` |
| `recharge_events` | `customer_id` |
| `package_events` | `customer_id` |
| `offer_events` | `customer_id` |
| `lifecycle_events` | `customer_id` |

## Topic provisioning
`ingestion/kafka_admin.py` broker ke existing topic names dekhta hai. Existing topics ko bilkul nahi badalta; sirf missing topic ko 6 partitions, replication 1 aur 30 din retention ke saath banata hai. Is liye pehle se bane 9 topics par provisioning dobara chalana safe hai.

## Resumable replay
`ingestion/replay.py` `data/raw/<topic>.jsonl` ko chunks mein parhta hai. Har chunk ke baad pehle producer `flush()` hota hai; us ke kamyab hone par line offset `.tmp` file mein likh kar `os.replace` se checkpoint atomically update hota hai. `--checkpoint state/producer_ckpt.json` se yeh checkpoint path diya ja sakta hai. Config ka default path `state/ingest_producer_checkpoint.json` hai.

Corrupt JSON ya JSON object na hone wali line, aur send retries ke baad nakaam event, `data/dlq/producer_<topic>.jsonl` mein jata hai. `--limit` har topic par is invocation mein zyada se zyada process hone wali nayi lines ki tadaad hai; chhota smoke test ek topic tak mahdood rakha ja sakta hai.

## Commands
Missing topics banane ke liye:

```powershell
python -m ingestion.kafka_admin --config config/config.yaml
```

Ek topic ki pehli 10 lines ka bounded smoke test:

```powershell
python -m ingestion.replay --config config/config_test.yaml --raw-dir data/raw --checkpoint state/producer_ckpt.json --topics customer_events --limit 10
```

Tamam topics ka full replay:

```powershell
python -m ingestion.replay --config config/config.yaml --raw-dir data/raw --checkpoint state/producer_ckpt.json
```

## Tests
- `tests/test_ingest_topics.py`: settings, 9 topics ki keys aur partition dates.
- `tests/test_ingest_replay.py`: multi-topic send, checkpoint resume, flush failure aur DLQ.
- `python -m pytest tests -q`: ingestion ke tamam tests aur baqi project tests.
