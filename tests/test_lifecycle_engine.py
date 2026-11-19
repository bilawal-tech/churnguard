import pytest

from simulator.lifecycle import engine as e
from simulator.lifecycle import model as m


def test_price_adder():
    assert e.price_adder("low") == pytest.approx(0.6)
    assert e.price_adder("high") == pytest.approx(0.12)


def test_usage_adder():
    assert e.usage_adder(30, 400, 28) == pytest.approx(0.8)   # ratio 0.3
    assert e.usage_adder(60, 400, 28) == 0.0                  # ratio 0.6
    assert e.usage_adder(0, 400, 28) == pytest.approx(2.0)
    assert e.usage_adder(0, 400, 10) == 0.0                   # history kam


def test_network_adder():
    assert e.network_adder(40, 10) == pytest.approx(2.0)      # 25%
    assert e.network_adder(40, 1) == 0.0                      # 2.5%
    assert e.network_adder(0, 0) == 0.0


def test_zero_balance_adder():
    assert e.zero_balance_adder(0) == 0.0
    assert e.zero_balance_adder(7) == pytest.approx(0.75)
    assert e.zero_balance_adder(99) == pytest.approx(1.5)


def test_risk_score_postpaid_ignores_zero_balance():
    a = e.risk_score("mid", 100, 400, 28, 40, 1, 20, False)
    assert a["zero_balance"] == 0.0
    assert a["total"] == pytest.approx(a["price"])


def test_churn_chance():
    base = m.BASE_DAILY_CHURN
    assert e.churn_chance(0.0, True, 0, 0.0) == pytest.approx(base)
    assert e.churn_chance(0.0, False, 0, 0.0) == pytest.approx(base * 0.5)
    assert e.churn_chance(0.0, True, 1, 0.0) == pytest.approx(base * 2.0)
    assert e.churn_chance(0.0, True, 0, -100.0) == 0.0
    assert e.churn_chance(1e9, True, 1, 0.0) == 1.0


def test_pick_churn_reason():
    net = {"price": 0.1, "network": 1.5, "usage": 0.5, "zero_balance": 0.0}
    assert e.pick_churn_reason(net, 0.5) == m.POOR_NETWORK
    assert e.pick_churn_reason(net, 0.05) == m.COMPETITOR_OFFER
    zb = {"price": 0.1, "network": 0.0, "usage": 0.0, "zero_balance": 1.0}
    assert e.pick_churn_reason(zb, 0.5) == m.INACTIVITY
    none = {"price": 0.0, "network": 0.0, "usage": 0.0, "zero_balance": 0.0}
    assert e.pick_churn_reason(none, 0.5) == m.COMPETITOR_OFFER


def test_inactivity_transition():
    assert e.inactivity_transition(True, m.ACTIVE, 14) == m.SUSPENDED
    assert e.inactivity_transition(True, m.ACTIVE, 13) is None
    assert e.inactivity_transition(True, m.SUSPENDED, 30) == m.CHURNED
    assert e.inactivity_transition(True, m.SUSPENDED, 20) is None
    assert e.inactivity_transition(False, m.ACTIVE, 100) is None
    assert e.inactivity_transition(True, m.CHURNED, 100) is None


def test_reactivates():
    assert e.reactivates(m.SUSPENDED, 0.01) is True
    assert e.reactivates(m.SUSPENDED, 0.5) is False
    assert e.reactivates(m.CHURNED, 0.0) is False
    assert e.reactivates(m.ACTIVE, 0.0) is False


def test_at_risk_next():
    assert e.at_risk_next(0, None, 1.5, 10) == (1, 10)
    assert e.at_risk_next(1, 10, 0.5, 20) == (1, 10)
    assert e.at_risk_next(1, 10, 0.5, 24) == (0, None)
    assert e.at_risk_next(1, 10, 1.2, 20) == (1, 20)
    assert e.at_risk_next(0, None, 0.5, 20) == (0, None)