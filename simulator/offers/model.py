"""Step 9 (offers): saare constants. config/config.yaml nahi badli."""
from datetime import date

OFFER_TYPES = (
    "RECHARGE_BONUS", "DATA_BOOST", "CALL_BUNDLE",
    "WEEKEND_SPECIAL", "EVENT_OFFER", "CRICKET_PACK",
)
TRIGGER_RULE = {
    "RECHARGE_BONUS": "balance",
    "DATA_BOOST": "usage_mix",
    "CALL_BUNDLE": "usage_mix",
    "WEEKEND_SPECIAL": "weekend",
    "EVENT_OFFER": "event",
    "CRICKET_PACK": "event",
}
# Ek din mein kai offers ke qabil hon to pehla jeetta hai.
PRIORITY = (
    "EVENT_OFFER", "CRICKET_PACK", "RECHARGE_BONUS",
    "DATA_BOOST", "CALL_BUNDLE", "WEEKEND_SPECIAL",
)
ACTIONS = ("SENT", "ACCEPTED", "EXPIRED", "HELD")
STATUSES = ("OPEN", "ACCEPTED", "EXPIRED", "HELD")

# Control group (customer_id + seed se ek baar tay) aur frequency cap
CONTROL_GROUP_PCT = 0.10
OFFER_GAP_DAYS = 7
MAX_OFFERS_30D = 3

# Discount aur accept chance (pehla andaza, Step 13 mein tune hoga)
DISCOUNT_PCT_BY_OFFER = {
    "DATA_BOOST": 0.30, "CALL_BUNDLE": 0.30, "WEEKEND_SPECIAL": 0.25,
    "EVENT_OFFER": 0.30, "CRICKET_PACK": 0.20,
}
ACCEPT_CHANCE_BY_OFFER = {
    "DATA_BOOST": 0.12, "CALL_BUNDLE": 0.10, "WEEKEND_SPECIAL": 0.08,
    "EVENT_OFFER": 0.15, "CRICKET_PACK": 0.10,
}
# Fixed window (din). Event wale offers ka window calendar se nikalta hai.
WINDOW_DAYS_BY_OFFER = {
    "RECHARGE_BONUS": 7, "DATA_BOOST": 3, "CALL_BUNDLE": 3,
    "WEEKEND_SPECIAL": 3,
}

# Package chunao: sirf region "all", price band ke hisaab se (min, max); max None = koi hadd nahi
PRICE_RANGE_BY_BAND = {"low": (0, 300), "mid": (300, 600), "high": (600, None)}
DATA_BOOST_MIN_DATA_MB = 2048
CALL_BUNDLE_MIN_MINUTES = 50          # off-net + any-net minutes
OFFER_PACKAGE_AUTO_RENEW = 0          # discount sirf ek baar

# Usage trigger (7 din vs 28 din ka hafta-wari average)
DATA_BOOST_RISE_RATIO = 1.3
CALL_BUNDLE_RISE_RATIO = 1.3
OFFER_MIN_HISTORY_DAYS = 14           # Step 8 jaisa, pehla andaza

# RECHARGE_BONUS (sirf prepaid)
LOW_BALANCE_OFFER_PKR = 100
RECHARGE_TARGET_BY_BAND = {"low": 300, "mid": 600, "high": 1000}
# Inaam: free asli package, "all" region, price is cap se kam
REWARD_MAX_PRICE_BY_BAND = {"low": 110, "mid": 220, "high": 220}

# Weekend (Python weekday: Monday 0, Friday 4)
WEEKEND_OFFER_DAY = 4

# Events: (date, offer_type, campaign_name)
EVENT_CALENDAR = (
    (date(2026, 5, 3), "CRICKET_PACK", "PSL11_Final"),          # ek source se, verify
    (date(2026, 5, 27), "EVENT_OFFER", "Eid_ul_Adha"),
    (date(2026, 8, 14), "EVENT_OFFER", "Independence_Day"),
    (date(2026, 8, 19), "CRICKET_PACK", "England_Test1"),
)
LEAD_DAYS_BY_OFFER = {"EVENT_OFFER": 3, "CRICKET_PACK": 1}
AFTER_DAYS_BY_OFFER = {"EVENT_OFFER": 1, "CRICKET_PACK": 1}