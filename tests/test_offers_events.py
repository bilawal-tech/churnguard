from simulator.common import load_config
from simulator.core.clock import SimClock
from simulator.offers.events import build_offer_event, make_offer_id


def test_make_offer_id():
    assert make_offer_id("C0000001", 3, "DATA_BOOST") == "OFR-C0000001-3-DATA_BOOST"


def test_build_offer_event_envelope_and_determinism():
    cfg = load_config("config_test.yaml")
    clock = SimClock.from_config(cfg, index=3)
    oid = make_offer_id("C0000001", clock.index, "DATA_BOOST")

    ev_sent = build_offer_event(
        cfg, "C0000001", clock, oid, "DATA_BOOST", "SENT",
        "treatment", "usage_mix", package_id="PKG001", discount_pct=0.30,
    )
    ev_sent_again = build_offer_event(
        cfg, "C0000001", clock, oid, "DATA_BOOST", "SENT",
        "treatment", "usage_mix", package_id="PKG001", discount_pct=0.30,
    )
    ev_acc = build_offer_event(
        cfg, "C0000001", clock, oid, "DATA_BOOST", "ACCEPTED",
        "treatment", "usage_mix", package_id="PKG001", discount_pct=0.30,
    )

    assert len(ev_sent["event_id"]) == 20
    assert ev_sent["event_id"] == ev_sent_again["event_id"]
    assert ev_sent["event_id"] != ev_acc["event_id"]
    assert "+05:00" in ev_sent["event_time"]
    assert ev_sent["schema_version"] == "1.0"
    assert ev_sent["source"] == "simulator"
    assert ev_sent["group"] == "treatment"
    assert ev_sent["campaign_name"] is None
    assert ev_sent["package_id"] == "PKG001"
    assert ev_sent["discount_pct"] == 0.3
