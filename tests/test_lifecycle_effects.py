import pytest

from simulator.lifecycle import engine as e
from simulator.lifecycle import model as m


def _event():
    return {
        "calls_onnet_min": 10, "calls_offnet_min": 5, "calls_intl_min": 0,
        "sms_count": 4, "dropped_calls": 1,
        "data_mb_whatsapp": 50.0, "data_mb_social": 20.0, "data_mb_video": 100.0,
        "data_mb_browsing": 30.0, "data_mb_other": 10.0,
    }


def test_scale_usage_event_values():
    ev = e.scale_usage_event(_event(), 0.4)
    assert ev["calls_onnet_min"] == 4
    assert ev["calls_offnet_min"] == 2
    assert ev["sms_count"] == 2
    assert ev["data_mb_video"] == pytest.approx(40.0)
    assert ev["data_mb_whatsapp"] == pytest.approx(20.0)


def test_scale_usage_event_types():
    ev = e.scale_usage_event(_event(), 0.4)
    assert isinstance(ev["calls_onnet_min"], int)
    assert isinstance(ev["dropped_calls"], int)
    assert isinstance(ev["data_mb_social"], float)


def test_network_adder_needs_min_calls():
    assert e.network_adder(m.NETWORK_MIN_CALLS - 1, 10) == 0.0
    assert e.network_adder(m.NETWORK_MIN_CALLS, 10) == pytest.approx(m.NETWORK_MAX_ADDER)


def test_at_risk_constants():
    assert 0 < m.AT_RISK_USAGE_FACTOR < 1
    assert 0 < m.AT_RISK_RECHARGE_CHANCE < 1
    assert m.NETWORK_NORMAL_RATIO < m.NETWORK_FULL_RATIO