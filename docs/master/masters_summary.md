# ChurnGuard v2 - Masters Summary

Status: all three masters are built and tested (20 tests passing). They are reference tables, generated once from `config/config.yaml`, and go straight to S3 raw (not through Kafka).

## How to run

From the project root, in the VS Code terminal (venv on):

```
python -m simulator.run_masters --config config.yaml
python -m pytest tests -v
```

Use `--config config_test.yaml` for the small test run. Each record carries `schema_version` ("1.0") and `source` ("simulator").

## Overview

| Master | Records | Output file | Code |
|---|---|---|---|
| tower_master | 110 | `data/raw/tower_master/tower_master.jsonl` | `simulator/masters/towers.py` |
| packages_master | 29 | `data/raw/packages_master/packages_master.jsonl` | `simulator/masters/packages.py` |
| field_teams_master | 25 | `data/raw/field_teams_master/field_teams_master.jsonl` | `simulator/masters/field_teams.py` |

Shared helpers (config loading, ID format, per-entity seeds) are in `simulator/common.py`.

## 1. tower_master

Fields: `tower_id`, `region`, `city`, `zone`, `lat`, `lon`, `tower_type`, `capacity_users`, `neighbor_tower_ids`, `install_date`.

- Count per city comes from config: Karachi 30, Lahore 25, Islamabad_Rawalpindi 13, Faisalabad 9, Peshawar 9, Multan 8, Quetta 6, Other_cities 10.
- `tower_id` has a block per city (Karachi `T01001`, Lahore `T02001`, ...), so adding towers in one city does not change the others.
- Location: random point within 15 km of an approximate city centre (centres are approximate, not exact map data).
- `zone` comes from location: the city centre splits the city into NE, NW, SE, SW (for example `Karachi-NE`).
- `tower_type`: 3G 15%, 4G 65%, 5G 20%. Capacity depends on type.
- Neighbors: the 3 nearest towers of the same city (fewer if the city has fewer towers).
- `install_date` is a past date counted back from `start_date`.

## 2. packages_master

Built from `config/reference/operator_packages.csv`, a hand-cleaned snapshot of Jazz public prepaid packages (collected 2026-10-10, prices include tax, 1 GB = 1024 MB). Details of the scrape are in `jazz_packages_scraping.md`.

Fields: `package_id`, `name`, `package_type`, `price_pkr`, `validity_days`, `quota_onnet_min`, `quota_offnet_min`, `quota_anynet_min`, `quota_intl_min`, `quota_sms`, `quota_data_mb`, `quota_social_mb`, `night_only`, `region`, `auto_renew_allowed`, `min_balance_required`.

- Own names, no Jazz names: `<Validity> <Type> <Size>` (for example "Weekly Combo 30GB"). If two packages get the same name, a tier word is added by price: Lite, Standard, Plus, Pro, Max.
- `package_id` format `P_<TYPE>_<DAYS>D_<4 hex>` (for example `P_CMB_30D_6a95`). The 4 hex characters are a hash of the source name, so IDs do not change if the CSV order changes.
- `package_type` rules: social = only social data (SMS allowed); voice = only minutes (SMS allowed); data = only generic data; combo = everything else. Result: 21 combo, 5 social, 2 voice, 1 data.
- `min_balance_required` equals the price; `auto_renew_allowed` is True for all.
- `region` is a list (`["all"]` or city names). Package count comes from the CSV; `packages.count` in config is not used.

## 3. field_teams_master

Fields: `team_id`, `region`, `city`, `zone`, `base_lat`, `base_lon`.

- Count per city from config: Karachi 6, Lahore 5, Islamabad_Rawalpindi 3, Faisalabad 2, Peshawar 2, Multan 2, Quetta 2, Other_cities 3.
- `team_id` format `FT<city no><team no>` (for example `FT0101` to `FT0106` for Karachi).
- Base location: random point within 8 km of the city centre. Teams stay at a fixed base (no movement for now). `zone` follows the same rule as towers.
- The nearest team to a tower will be found later from lat/lon distance.

## Design rules that apply to all three

- Every entity has its own seed (global seed plus its ID), so the same config gives the same data, and adding towers or teams does not change existing ones.
- All counts come from config and can be increased later.

## Tests

| File | Tests |
|---|---|
| `tests/test_towers.py` | 6 |
| `tests/test_packages.py` | 8 |
| `tests/test_field_teams.py` | 6 |

They check counts, unique IDs, same output for the same seed, zone matches location, old records stay unchanged when more are added, and package IDs stay stable when the CSV is reordered.

## Known limits

- City centres and tower or team locations are approximate and simulated.
- Package SMS counts are an interpretation where Jazz wrote "Jazz Mins & SMS" (SMS taken equal to minutes).
- Package `region` is guessed from the package name; two packages marked `check` are treated as available everywhere.
- Prices are a dated snapshot and change often.
- Jazz sells mostly combo bundles, so there are few single-type packages.

## Next step

Simulator core: simulated clock, per-customer state, and state saving so a restart resumes where it stopped.





### How the tests work

Tests check our own code, so mistakes are caught early and nothing breaks silently later. Each test is a small function that runs the code and uses `assert` to check one condition. If the condition holds the test passes, otherwise it fails and pytest shows where.

Example:

    def test_ids_unique():
        ids = [t["team_id"] for t in make()]
        assert len(ids) == len(set(ids))

A set drops duplicates, so if any ID repeats the set is shorter and the test fails.

| What is checked | Why it matters |
|---|---|
| Count equals the config | 25 teams in config means exactly 25 are built |
| IDs are unique | Two records never share an ID, so data does not mix later |
| Same seed gives the same data | Every run is reproducible |
| Zone matches the location | A record never gets a wrong zone |
| Old records stay unchanged when more are added | Adding towers or teams does not change existing ones |
| Package IDs stay stable when the CSV is reordered | IDs depend on the package, not the row order |

Tests run on the small `config_test.yaml` (one team per city, a few towers), so they finish in under a second. They do not write any data files; the real data is written only by `run_masters.py` using `config.yaml`. After any code change, run `python -m pytest tests -v` to see if something old broke.