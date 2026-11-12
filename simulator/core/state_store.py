"""SQLite store for simulator runtime state (not events or master data)."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS customer_state (
    customer_id    TEXT PRIMARY KEY,
    plan_type      TEXT NOT NULL,
    status         TEXT NOT NULL,
    status_since   INTEGER NOT NULL,
    balance        REAL NOT NULL,
    home_tower_id  TEXT NOT NULL,
    last_active    INTEGER NOT NULL,
    at_risk        INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS active_packages (
    customer_id    TEXT NOT NULL,
    package_id     TEXT NOT NULL,
    rem_onnet_min  REAL NOT NULL DEFAULT 0,
    rem_offnet_min REAL NOT NULL DEFAULT 0,
    rem_anynet_min REAL NOT NULL DEFAULT 0,
    rem_intl_min   REAL NOT NULL DEFAULT 0,
    rem_sms        REAL NOT NULL DEFAULT 0,
    rem_data_mb    REAL NOT NULL DEFAULT 0,
    rem_social_mb  REAL NOT NULL DEFAULT 0,
    expires_at     INTEGER NOT NULL,
    auto_renew     INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (customer_id, package_id)
);
CREATE TABLE IF NOT EXISTS tower_state (
    tower_id            TEXT PRIMARY KEY,
    health              TEXT NOT NULL,
    load                REAL NOT NULL,
    signal_dbm          REAL NOT NULL,
    precursor_active    INTEGER NOT NULL DEFAULT 0,
    failure_at          INTEGER,
    precursor_start_hour INTEGER,
    dip_until_hour      INTEGER,
    down_until_hour     INTEGER,
    outage_id           TEXT,
    outage_cause        TEXT,
    outage_severity     INTEGER,
    outage_affected_pct REAL
);
CREATE TABLE IF NOT EXISTS sim_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

CUSTOMER_COLS = (
    "customer_id", "plan_type", "status", "status_since",
    "balance", "home_tower_id", "last_active", "at_risk",
)
TOWER_COLS = [
    "tower_id", "health", "load", "signal_dbm", "precursor_active",
    "failure_at", "precursor_start_hour", "dip_until_hour",
    "down_until_hour", "outage_id", "outage_cause",
    "outage_severity", "outage_affected_pct",
]

class StateStore:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)

    @contextmanager
    def transaction(self):
        self.conn.execute("BEGIN")
        try:
            yield
        except Exception:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    def get_meta(self, key, default=None):
        row = self.conn.execute(
            "SELECT value FROM sim_meta WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_meta(self, key, value):
        self.conn.execute(
            "INSERT INTO sim_meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )

    def upsert_customers(self, rows):
        cols = ", ".join(CUSTOMER_COLS)
        marks = ", ".join(":" + c for c in CUSTOMER_COLS)
        updates = ", ".join(
            f"{c}=excluded.{c}" for c in CUSTOMER_COLS if c != "customer_id"
        )
        self.conn.executemany(
            f"INSERT INTO customer_state({cols}) VALUES({marks}) "
            f"ON CONFLICT(customer_id) DO UPDATE SET {updates}",
            list(rows),
        )

    def get_customer(self, customer_id):
        row = self.conn.execute(
            "SELECT * FROM customer_state WHERE customer_id=?", (customer_id,)
        ).fetchone()
        return dict(row) if row else None

    def upsert_towers(self, rows):
         cols = ", ".join(TOWER_COLS)
         marks = ", ".join(":" + c for c in TOWER_COLS)
         updates = ", ".join(
            f"{c}=excluded.{c}" for c in TOWER_COLS if c != "tower_id"
        )
         full = []
         for row in rows:
            item = {c: None for c in TOWER_COLS}
            item["precursor_active"] = 0
            item.update(row)
            full.append(item)
         self.conn.executemany(
            f"INSERT INTO tower_state({cols}) VALUES({marks}) "
            f"ON CONFLICT(tower_id) DO UPDATE SET {updates}",
            full,
        )

    def get_tower(self, tower_id):
        row = self.conn.execute(
            "SELECT * FROM tower_state WHERE tower_id=?", (tower_id,)
        ).fetchone()
        return dict(row) if row else None

    def all_towers(self):
        rows = self.conn.execute(
            "SELECT * FROM tower_state ORDER BY tower_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def count_customers(self):
        return self.conn.execute(
            "SELECT COUNT(*) FROM customer_state"
        ).fetchone()[0]

    def close(self):
        self.conn.close()