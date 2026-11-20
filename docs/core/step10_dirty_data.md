# Step 10: Dirty Data (Nulls, Duplicates, Late Events)

## Overview
Dirty data post-hook ke zariye inject hota hai — yani saare simulation hooks (`customer, package, recharge, usage, tower, offer, lifecycle`) chalne ke **baad** aur JSONL file likhne se **pehle**. Is se inter-hook visibility (`BandContext.band_events`) par koi asar nahi padta, aur aage Silver layer (PySpark cleansing) ki data quality aur deduplication rules test hoti hain. `config/config.yaml` aur `config/config_test.yaml` mein `dirty_data` section se rates control hote hain.

## Files
| File | Kaam |
|---|---|
| `simulator/dirty/model.py` | Default dirty rates aur har topic ke nullable fields ki list (`NULLABLE_FIELDS_BY_TOPIC`) |
| `simulator/dirty/processor.py` | Post-hook `make_dirty_processor(cfg)`: null injection, late scheduling, aur exact duplicate emission |
| `simulator/core/state_store.py` | `delayed_events` table (`add_delayed_event`, `pop_delayed_events`) taake stop/resume deterministic rahe |
| `simulator/core/engine.py` | `Simulator` mein `post_hooks` support |
| `simulator/verify_core_pipeline.py` | Check 16: dirty run (nulls, duplicates, late arrivals, aur stop/resume determinism) |

## Config (`dirty_data`)
| Key | Value | Matlab |
|---|---|---|
| `null_rate` | `0.015` | ~1.5% events mein ek non-critical field `null` hota hai |
| `duplicate_rate` | `0.005` | ~0.5% non-late events exact same `event_id` ke saath dobara emit hote hain |
| `late_rate` | `0.015` | ~1.5% events apne band ke bajaye baad ke band mein aate hain |
| `late_max_hours` | `48` | Zyada se zyada 48 ghante (`8` bands, `1` se `8` bands delay) |

## Rules aur Safeguards
- **Common envelope aur primary keys mehfooz:** `event_id`, `event_time`, `schema_version`, `source`, aur primary IDs (`customer_id`, `offer_id`, `outage_id`, `subscription_id`, aur tower topics par `tower_id`) kabhi null nahi hote, taake Kafka keys aur Silver deduplication na tootein.
- **Deterministic RNG:** Har event ke liye `make_rng(seed, "dirty", topic, event_id)` istemal hota hai.
- **Late events persistence:** Delayed events SQLite `delayed_events` table mein `deliver_at_band` ke saath save hote hain aur due band par apne purane `event_time` ke saath emit hote hain.

## Tests aur Verification
- `tests/test_dirty_data.py`: `delayed_events` persistence, disabled mode, null injection, exact duplicates, late delivery, aur stop/resume determinism.
- `python -m pytest tests -q`: **214 passed**.
- `python -m simulator.verify_core_pipeline`: **16/16 checks pass** (Check 16: dirty data nulls, duplicates, late arrivals, aur dirty stop/resume match).