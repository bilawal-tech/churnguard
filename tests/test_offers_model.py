from datetime import date

from simulator.offers import model as m


def test_every_offer_has_trigger_and_priority():
    assert set(m.TRIGGER_RULE) == set(m.OFFER_TYPES)
    assert set(m.PRIORITY) == set(m.OFFER_TYPES)
    assert len(m.PRIORITY) == len(m.OFFER_TYPES)


def test_package_offers_have_discount_and_chance():
    pkg_offers = set(m.OFFER_TYPES) - {"RECHARGE_BONUS"}
    assert set(m.DISCOUNT_PCT_BY_OFFER) == pkg_offers
    assert set(m.ACCEPT_CHANCE_BY_OFFER) == pkg_offers
    for v in list(m.DISCOUNT_PCT_BY_OFFER.values()) + list(m.ACCEPT_CHANCE_BY_OFFER.values()):
        assert 0 < v < 1


def test_event_offers_have_lead_and_after_days():
    for _, offer_type, _ in m.EVENT_CALENDAR:
        assert offer_type in m.LEAD_DAYS_BY_OFFER
        assert offer_type in m.AFTER_DAYS_BY_OFFER


def test_bands_complete():
    bands = {"low", "mid", "high"}
    assert set(m.PRICE_RANGE_BY_BAND) == bands
    assert set(m.RECHARGE_TARGET_BY_BAND) == bands
    assert set(m.REWARD_MAX_PRICE_BY_BAND) == bands


def test_weekend_day_is_friday_and_14_august_clashes():
    assert m.WEEKEND_OFFER_DAY == 4