# ChurnGuard

ChurnGuard is a configurable telecom customer-churn simulation project. It
generates reproducible master data and provides a resumable, band-based
simulation runtime.

## Project structure

```text
config/                 Runtime and test configuration; reference inputs
data/
  raw/                  Generated master-data output
  reference/            Source snapshots used during development
docs/                   Project and data-flow documentation
simulator/
  core/                 Four-band clock, simulation engine, checkpoints, state store
  masters/              Tower, package, and field-team master builders
  common.py             Shared config, ID, and random-seed helpers
  run_masters.py        Master-data generation entry point
tests/                  Automated tests
tools/                  Source-checking and package-data scripts
```

The simulator clock advances through four six-hour bands per day: Night,
Morning, Afternoon, and Evening. Runtime components live in `simulator/core/`;
master-data generation stays separate in `simulator/masters/`.

## Setup

From the project root in PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Run

Generate master data using the main configuration:

```powershell
python -m simulator.run_masters --config config.yaml
```

Use the smaller configuration for a test-sized master-data run:

```powershell
python -m simulator.run_masters --config config_test.yaml
```

Run the test suite:

```powershell
python -m pytest tests -v
```

Master-data output is written under `data/raw/`. The runtime state store is
SQLite-backed; keep its state database separate from generated event output.
