from ui.common import db, haversine_km, nearest_team, read_alerts, reset, set_status, sync_alerts

TEAMS = [
    {"team_id": "FT0101", "city": "Karachi", "base_lat": 24.87, "base_lon": 67.02},
    {"team_id": "FT0102", "city": "Karachi", "base_lat": 24.86, "base_lon": 67.08},
    {"team_id": "FT0201", "city": "Lahore", "base_lat": 31.5, "base_lon": 74.3},
]


def test_haversine():
    assert haversine_km(24.8, 67.0, 24.8, 67.0) == 0
    assert 1000 < haversine_km(24.86, 67.01, 31.52, 74.36) < 1200


def test_nearest_team_same_city_only():
    assert nearest_team("Karachi", 24.865, 67.075, TEAMS)[0] == "FT0102"
    assert nearest_team("Lahore", 31.0, 74.0, TEAMS)[0] == "FT0201"
    assert nearest_team("Quetta", 30.2, 67.0, TEAMS) == (None, None)


def test_alert_flow(tmp_path):
    conn = db(tmp_path / "a.db")
    rows = [("OUT-1", "T1", "FT0101", "2026-04-02 03:00:00")]
    sync_alerts(conn, rows)
    sync_alerts(conn, rows)
    al = read_alerts(conn)
    assert len(al) == 1 and al.status[0] == "OPEN"
    set_status(conn, "OUT-1", "ACKNOWLEDGED", "2026-04-02 03:20:00")
    assert read_alerts(conn).status[0] == "ACKNOWLEDGED"
    set_status(conn, "OUT-1", "RESOLVED", "2026-04-02 06:00:00", "fuse replaced")
    r = read_alerts(conn).iloc[0]
    assert r.status == "RESOLVED" and r.ack_sim == "2026-04-02 03:20:00" and r.note == "fuse replaced"
    reset(conn)
    assert read_alerts(conn).empty