import pytest

from simulator.core.state_store import StateStore


@pytest.fixture
def store(tmp_path):
    state = StateStore(tmp_path / "state.db")
    yield state
    state.close()


def offer(offer_id, customer_id="C0000001", status="OPEN", sent_date="2026-04-01"):
    return {
        "offer_id": offer_id,
        "customer_id": customer_id,
        "offer_type": "DATA_BOOST",
        "grp": "low",
        "sent_date": sent_date,
        "window_end_date": "2026-04-07",
        "status": status,
    }


def test_insert_get_and_update_offer(store):
    row = offer("O1")
    store.insert_offer(row)

    stored = store.get_offer("O1")
    assert stored["offer_id"] == "O1"
    assert stored["customer_id"] == "C0000001"
    assert stored["status"] == "OPEN"
    assert stored["recharge_total"] == 0.0
    assert stored["package_id"] is None

    store.update_offer("O1", status="ACCEPTED", closed_date="2026-04-03")
    updated = store.get_offer("O1")
    assert updated["status"] == "ACCEPTED"
    assert updated["closed_date"] == "2026-04-03"


def test_open_offers_filter_by_status_and_customer(store):
    store.insert_offer(offer("O3", customer_id="C0000001", sent_date="2026-04-03"))
    store.insert_offer(offer("O1", customer_id="C0000001", sent_date="2026-04-01"))
    store.insert_offer(offer("O2", customer_id="C0000002", sent_date="2026-04-02"))
    store.insert_offer(offer("O4", customer_id="C0000001", status="ACCEPTED"))
    store.insert_offer(offer("O5", customer_id="C0000001", status="EXPIRED"))
    store.insert_offer(offer("O6", customer_id="C0000001", status="HELD"))

    assert [row["offer_id"] for row in store.open_offers()] == ["O1", "O2", "O3"]
    assert [row["offer_id"] for row in store.open_offers_for("C0000001")] == ["O1", "O3"]


def test_recent_offer_dates_filter_by_date_including_held(store):
    store.insert_offer(offer("O1", sent_date="2026-04-01"))
    store.insert_offer(offer("O2", status="HELD", sent_date="2026-04-05"))
    store.insert_offer(offer("O3", status="ACCEPTED", sent_date="2026-04-07"))
    store.insert_offer(offer("O4", customer_id="C0000002", status="HELD", sent_date="2026-04-08"))

    assert store.recent_offer_dates("C0000001", "2026-04-05") == [
        "2026-04-05",
        "2026-04-07",
    ]


def test_offer_daily_accumulates_reads_and_prunes(store):
    store.add_offer_daily("C0000001", "2026-04-01", 100, 12)
    store.add_offer_daily("C0000001", "2026-04-01", 25.5, 3.5)
    store.add_offer_daily("C0000001", "2026-04-02", 10, 2)
    store.add_offer_daily("C0000002", "2026-04-01", 99, 9)

    assert store.get_offer_daily("C0000001", "2026-04-01") == [
        {"day": "2026-04-01", "data_mb": 125.5, "call_min": 15.5},
        {"day": "2026-04-02", "data_mb": 10.0, "call_min": 2.0},
    ]
    assert store.get_offer_daily("C0000001", "2026-04-02") == [
        {"day": "2026-04-02", "data_mb": 10.0, "call_min": 2.0},
    ]

    store.prune_offer_daily("2026-04-02")
    assert store.get_offer_daily("C0000001", "2026-04-01") == [
        {"day": "2026-04-02", "data_mb": 10.0, "call_min": 2.0},
    ]
    assert store.get_offer_daily("C0000002", "2026-04-01") == []
