# Step 4: Customers, Profiles and First Usage Stream

Step 4 adds the first three hooks' worth of data to the simulator core: new customers (with their profiles) and a per-band usage summary for every active customer. The usage stream here is the first, simple version. Spend, packages and the effect of tower health are added in Steps 5 to 7.

## 1. What Step 4 produces

| Topic | Key | One record is |
|---|---|---|
| `customer_events` | customer_id | One signup, written once per customer |
| `profile_events` | customer_id | The customer's profile, version 1, written once per customer |
| `usage_events` | customer_id | One ACTIVE customer's summary of one time band |

All records carry the common envelope: `event_id`, `event_time` (+05:00), `schema_version` ("1.0"), `source` ("simulator"). Field lists are in `docs/schema/event_schemas.md`.

## 2. Files

| File | Role |
|---|---|
| `simulator/customers/generator.py` | `towers_by_city`, `build_customer`: one customer's starting state (no events) |
| `simulator/customers/events.py` | `build_customer_event`, `build_profile_event`, `device_type_for`, and the share tables |
| `simulator/customers/hook.py` | `day_total`, `new_customers_in_band`, `make_customer_hook(cfg, towers)` |
| `simulator/usage/generator.py` | `persona_for`, `customer_factor`, `neighbor_map`, `build_usage_event` |
| `simulator/usage/hook.py` | `make_usage_hook(cfg, towers)` |
| `simulator/verify_core_pipeline.py` | End-to-end check on `config_test.yaml` |

`engine.py`, `state_store.py`, `checkpoint.py` and `clock.py` were not changed in this step. The only config change is the new key `customers.burst_decay`.

## 3. How a band runs

Hooks run inside the engine's band transaction, in this order:

1. **Customer hook.** Counts how many customers sign up in this band, builds each one, writes the SQLite row (`customer_state`) and returns a `customer_events` and a `profile_events` record per customer. It advances `ctx.next_customer_no`, which the engine saves in the checkpoint.
2. **Usage hook.** Reads every ACTIVE customer (sorted by `customer_id`) with its `home_tower_id` and returns one `usage_events` record each.

The usage hook runs second, in the same transaction, so a customer who signs up in a band already produces usage in that same band.

## 4. Customer signups

The number of new customers depends only on the band index and the config, never on SQLite. After a crash, the band is replayed and gives the same count and the same customer numbers.

- **Burst days** (`initial_burst_days`): day weights are `burst_decay ** k` for day k. A day gets `initial` times its share of the total weight. Rounding is cumulative, so the burst adds up to exactly `initial`.
- **Steady days:** `new_per_day` customers.
- **Split into bands:** a day's total is divided equally across its four bands, also with cumulative rounding (bands differ by at most one customer).

| Config | Burst days | Total over `history_days` |
|---|---|---|
| `config.yaml` (initial 20000, 7 days, decay 0.8, 55 per day) | 5061, 4050, 3239, 2591, 2074, 1658, 1327 | 29,515 |
| `config_test.yaml` (initial 100, 1 day, decay 0.8, 5 per day, 5 days) | 100 | 120 |

Customers are numbered from 1 (`C0000001`).

### Customer starting state (`build_customer`)

City from the geography shares; home tower picked uniformly among that city's towers; prepaid with probability `prepaid_share` (balance 50 to 500 PKR, skewed to small values) or postpaid (balance 0). Status is ACTIVE; `status_since` and `last_active` are the signup band index; `at_risk` is 0.

### What goes to SQLite

Only the existing `customer_state` columns (`customer_id`, `plan_type`, `status`, `status_since`, `balance`, `home_tower_id`, `last_active`, `at_risk`). There is no `city` column: city is fixed and follows from `home_tower_id`. `device_type`, persona and the usage factor are not stored either; they are recomputed from the seed.

## 5. Customer and profile events

- `customer_events` (signup): `customer_id`, `signup_date`, `region` (same value as `city`), `city`, `segment` (prepaid or postpaid), `acquisition_channel`, `device_type`, `initial_balance`, `home_tower_id`. There is **no `zone`**: a customer's connected tower changes, so zone is always joined from the tower master by `tower_id`.
- `profile_events` (version 1): `customer_id`, `profile_version`, `age_band`, `gender`, `phone_masked`, `cnic_masked`, `language_pref`, `arpu_band`.
- `event_time` is the start of the signup band; `signup_date` is that band's date.
- `initial_balance` is a float (for example 83.46), not an integer.

### Profile and customer value shares

| Field | Values (share) |
|---|---|
| age_band | 18-24 (25%), 25-34 (35%), 35-44 (22%), 45-54 (12%), 55+ (6%) |
| gender | male (60%), female (40%) |
| language_pref | Urdu (65%), English (25%), Regional (10%) |
| arpu_band | low (under 300 PKR a month), mid (300 to 800), high (over 800). Prepaid: 44/40/16. Postpaid: 10/40/50. Overall about 40/40/20 |
| acquisition_channel | retailer (55%), online (15%), campaign (15%), referral (10%), other (5%) |
| device_type | smartphone_android (62%), smartphone_ios (8%), feature_phone (30%) |

`arpu_band` is a guess made at signup. A measured value will be derived later from usage and recharges.

### Masking

Phone and CNIC are created masked and the real number never exists. Phone looks like `0302-xxxx61` (pattern `03dd-xxxxdd`). CNIC looks like `xxxxx-xxxxx98-5` (pattern `xxxxx-xxxxxdd-d`); its last digit is odd for male and even for female.

## 6. Usage events

One record per ACTIVE customer per band. Fields: `customer_id`, `event_date`, `time_band` (Night, Morning, Afternoon, Evening), `tower_id`, `calls_onnet_min`, `calls_offnet_min`, `calls_intl_min`, `sms_count`, `data_mb_whatsapp`, `data_mb_social`, `data_mb_video`, `data_mb_browsing`, `data_mb_other`, `dropped_calls`, `active_package_ids`, `spend_from_package`, `spend_from_balance`.

### How a record is built

1. **Persona** (fixed per customer, depends on the device):
   - feature_phone: call_heavy (65%) or sms_heavy (35%), with 5 to 20 MB of data a day, all counted as "other".
   - smartphone: call_heavy (15%), whatsapp_only (43%) or data_heavy (42%).
2. **Daily average by persona** (before noise):

| Persona | On-net min | Off-net min | Intl min | SMS | Data MB |
|---|---|---|---|---|---|
| call_heavy | 40 | 30 | 1 | 5 | 300 |
| sms_heavy | 8 | 6 | 0.1 | 40 | 150 |
| whatsapp_only | 6 | 4 | 0.2 | 3 | 500 |
| data_heavy | 10 | 8 | 0.3 | 3 | 1500 |

3. **Data split by app** (smartphones): call_heavy and sms_heavy: WhatsApp 40%, social 20%, browsing 25%, other 15%. whatsapp_only: WhatsApp 60%, social 15%, browsing 15%, other 10%. data_heavy: video 40%, social 20%, browsing 20%, WhatsApp 10%, other 10%.
4. **Band share of the day:** Night 10%, Morning 30%, Afternoon 25%, Evening 35%.
5. **Noise:** a fixed per-customer factor (log-normal, limited to 0.5 to 1.8) and a per-band change of about plus or minus 25%. Minutes and SMS are drawn as whole numbers (Poisson), so small averages give mostly zero and sometimes one.
6. **Tower:** 85% of bands on the home tower, 15% on one of its (up to three) neighbor towers in the same city. A tower with no neighbors always uses the home tower.
7. **Dropped calls:** calls are `(on-net + off-net + intl minutes) / 3`. Each call drops with a base chance of 1.5% (`BASE_DROP_RATE`, a code constant). Step 5 will multiply it by tower health.
8. **Empty for now:** `active_package_ids` is `[]`, `spend_from_package` and `spend_from_balance` are `null` until Step 7.

The usage hook requires towers that already have `neighbor_tower_ids` (from `add_neighbors(build_towers(cfg))`); otherwise it raises `ValueError` instead of silently skipping roaming.

## 7. Reproducibility

Every random choice uses `make_rng(seed, ...)` with its own parts, so the same customer and band always give the same values:

| Value | RNG parts |
|---|---|
| city, home tower, prepaid, balance | `"customer", n` |
| customer event channel | `"customer_event", n` |
| device type | `"device", n` |
| profile fields | `"profile", n` |
| persona | `"persona", n` |
| usage factor | `"usage_factor", n` |
| one usage record | `"usage", n, band_index` |

`event_id` is the first 20 hex characters of a SHA-256 over seed, topic, customer_id and, where needed, an extra part (profile version, or band index for usage). Replaying a band therefore reproduces the same events, and duplicates can be removed by `event_id`.

## 8. Decisions made in this step

| Decision | Choice | Why |
|---|---|---|
| `zone` in `customer_events` | Not included | Connected tower changes; zone comes from the tower master |
| `city` in SQLite | No column | City follows from `home_tower_id`; SQLite keeps only state that changes |
| Burst shape | Decaying (`burst_decay` 0.8) | Looks like a launch and gives varied tenure; works for any burst length |
| Signups within a day | Equal across 4 bands | Signup band has little effect later |
| Persona and device | Persona depends on device | A feature phone cannot have video or heavy data |
| Scale | Config-driven; target 100,000 customers at the end | Run the pipeline at 30,000 first |

## 9. Tests and verification

| Test file | Tests | What it covers |
|---|---|---|
| `tests/test_customer_generator.py` | 6 | Starting state |
| `tests/test_customer_events.py` | 11 | Fields, envelope, masking, shares, `device_type_for` |
| `tests/test_customer_hook.py` | 9 | Burst and daily counts, engine run, same run twice, resume |
| `tests/test_usage_generator.py` | 15 | Fields, feature phones, factor range, tower choice, drop rate, band shape |
| `tests/test_usage_hook.py` | 8 | ACTIVE only, counts, signup band, same run twice, resume |

The whole suite (including the earlier steps) has 88 tests.

`python -m simulator.verify_core_pipeline` runs the engine on `config_test.yaml` three times and prints PASS or FAIL for six checks:

1. Same seed twice gives the same events.
2. Stopping after 7 bands and resuming gives the same output as a full run.
3. Counts: 120 customers and 2,018 usage events (100 customers do not stay fixed, so this is not 2,000).
4. Every event has `event_id`, `event_time` (+05:00), `schema_version` and `source`.
5. Phone and CNIC are masked.
6. No `zone` in `customer_events`, and usage points to known customers and towers.

It writes only `data/test_run*` and `state/test_sim*.db` and deletes them first.

## 10. Known limits and what comes next

- **Speed:** `build_usage_event` recomputes the persona and factor for every record. It is correct but slow; a full 180-day run (about 21.6 million usage events at 30,000 customers) needs a cache of per-customer values first (planned before Step 13).
- **Tower health:** usage does not yet react to tower health. Step 5 adds `tower_metrics_events`, multiplies the drop rate (about 3x for DEGRADED, 8x for CRITICAL), lowers data on bad towers and moves customers to a neighbor when their tower is DOWN.
- **Spend and packages:** Step 7. It also needs a mapping from the package region names to our eight cities.
- **Churn:** Step 8 adds SUSPENDED and CHURNED statuses; usage then stops for non-ACTIVE customers.
- **Dirty data:** nulls, duplicates and late events are added in Step 10; nothing in Step 4 is dirty on purpose.
- **Small cities in the test config:** a city with one tower has no neighbors, so roaming there is zero. The real config does not have this.