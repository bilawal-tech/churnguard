from simulator.core.state_store import StateStore
from simulator.lifecycle import model


def _cols(store, table):
    return {r["name"] for r in store.conn.execute(f"PRAGMA table_info({table})")}


def test_customer_state_has_new_columns(tmp_path):
    s = StateStore(tmp_path / "s.db")
    cols = _cols(s, "customer_state")
    assert {"zero_balance_since", "at_risk_since", "at_risk"} <= cols


def test_customer_daily_one_row_per_day(tmp_path):
    s = StateStore(tmp_path / "s.db")
    sql = "INSERT OR REPLACE INTO customer_daily VALUES (?,?,?,?,?)"
    s.conn.execute(sql, ("C0000001", 5, 10.0, 4, 1))
    s.conn.execute(sql, ("C0000001", 5, 20.0, 8, 2))
    s.conn.execute(sql, ("C0000001", 6, 5.0, 2, 0))
    n = s.conn.execute("SELECT COUNT(*) FROM customer_daily").fetchone()[0]
    assert n == 2
    row = s.conn.execute(
        "SELECT usage FROM customer_daily WHERE customer_id='C0000001' AND day=5"
    ).fetchone()
    assert row["usage"] == 20.0


def test_model_constants_sane():
    assert model.INACTIVE_SUSPEND_DAYS < model.INACTIVE_CHURN_DAYS
    assert set(model.PRICE_SENSITIVITY) == {"low", "mid", "high"}
    assert len(model.CHURN_REASONS) == 5
    assert 0 < model.POSTPAID_CHURN_FACTOR < 1
    assert model.USAGE_WINDOW_DAYS < model.HISTORY_DAYS