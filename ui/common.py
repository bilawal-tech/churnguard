"""Shared helpers for the ChurnGuard UI (no streamlit import, so it is easy to test)."""
from __future__ import annotations

import math
import sqlite3
from pathlib import Path

import pandas as pd

UI_DIR = Path("data/ui")
DB_PATH = UI_DIR / "alerts.db"


def to_pkt(s: pd.Series) -> pd.Series:
    """Spark timestamps are UTC instants; return naive PKT (Asia/Karachi) times."""
    s = pd.to_datetime(s)
    if s.dt.tz is None:
        s = s.dt.tz_localize("UTC")
    return s.dt.tz_convert("Asia/Karachi").dt.tz_localize(None)


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def nearest_team(city, lat, lon, teams):
    """Closest field team in the same city. Returns (team_id, km) or (None, None)."""
    best = None
    for t in teams:
        if t["city"] != city:
            continue
        km = haversine_km(lat, lon, t["base_lat"], t["base_lon"])
        if best is None or km < best[1]:
            best = (t["team_id"], km)
    return (best[0], round(best[1], 1)) if best else (None, None)


def db(path=DB_PATH):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS alerts (alert_id TEXT PRIMARY KEY, tower_id TEXT, "
        "team_id TEXT, status TEXT, created_sim TEXT, ack_sim TEXT, resolved_sim TEXT, note TEXT)"
    )
    return conn


def sync_alerts(conn, rows):
    """rows: (alert_id, tower_id, team_id, created_sim). Existing alerts are untouched."""
    conn.executemany(
        "INSERT OR IGNORE INTO alerts(alert_id, tower_id, team_id, status, created_sim) "
        "VALUES(?, ?, ?, 'OPEN', ?)", rows)
    conn.commit()


def set_status(conn, alert_id, status, sim_time, note=""):
    if status == "ACKNOWLEDGED":
        conn.execute("UPDATE alerts SET status=?, ack_sim=? WHERE alert_id=?",
                     (status, sim_time, alert_id))
    elif status == "RESOLVED":
        conn.execute("UPDATE alerts SET status=?, resolved_sim=?, ack_sim=COALESCE(ack_sim, ?), "
                     "note=? WHERE alert_id=?", (status, sim_time, sim_time, note, alert_id))
    conn.commit()


def read_alerts(conn) -> pd.DataFrame:
    return pd.read_sql_query("SELECT * FROM alerts ORDER BY created_sim DESC", conn)


def reset(conn):
    conn.execute("DELETE FROM alerts")
    conn.commit()