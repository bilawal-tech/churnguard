# Step 9: Personalized offers

Is step mein ACTIVE customers ko offer bheje jate hain aur `offer_events` ki ground-truth story banati hai. 6 offer types hain: DATA_BOOST, CALL_BUNDLE, RECHARGE_BONUS, WEEKEND_SPECIAL, EVENT_OFFER, CRICKET_PACK. Customer seed se ek treatment ya control group mein rehta hai; control holdout lagbhag 15% hai, usay offer nahi bhejta balki `HELD` record deta hai. Har treatment customer ko 7 din mein zyada se zyada 1 offer milta hai aur ek waqt mein ek hi OPEN offer hota hai.

## Files

| File | Kaam |
|---|---|
| `simulator/offers/model.py` | Offer types, trigger rules, priority, discounts, acceptance windows aur event calendar ke constants |
| `simulator/offers/engine.py` | Pure functions: control assignment, frequency cap, trigger due checks, package aur reward selection |
| `simulator/offers/events.py` | `offer_events` ka record aur deterministic `offer_id` |
| `simulator/offers/hooks.py` | Daily tracking, Evening-band open-offer resolution aur naya offer evaluation |
| `simulator/core/state_store.py` | `offer_state`, `offer_daily` aur active package state ko SQLite mein rakhna |

## Hooks ki tartib

customer, package, recharge, usage, tower, **offer**, lifecycle (sab se aakhir mein). Offer hook tower ke baad aur lifecycle se pehle chalta hai.

Har band offer hook pehle `usage_events` se data aur call totals ko `offer_daily` mein jama karta hai aur `recharge_events` se OPEN `RECHARGE_BONUS` offer ka recharge total barhata hai. Faisla roz Evening band ke aakhir mein hota hai: pehle OPEN offers accept ya expire ki jati hain, phir ACTIVE customers ke liye naye offers evaluate kiye jate hain.

## Trigger rules aur priority

Offer ki trigger rule offer type se tay hoti hai:

| Offer type | Trigger rule | Shart |
|---|---|---|
| RECHARGE_BONUS | low_balance | Sirf prepaid aur balance 100 PKR se kam |
| DATA_BOOST | usage_rise | 7 din ka data 28 din ke hafta-wari average ka 1.3x se zyada aur 14 din history |
| CALL_BUNDLE | usage_rise | 7 din ke offnet/intl minutes 28 din ke hafta-wari average ka 1.3x se zyada aur 14 din history |
| WEEKEND_SPECIAL | weekend | Friday |
| EVENT_OFFER | event | Eid ya Independence Day campaign window |
| CRICKET_PACK | event | PSL ya England Test campaign window, sirf smartphone |

Ek din mein kai types due hon to priority order sab se pehla offer leta hai:

    EVENT_OFFER > CRICKET_PACK > RECHARGE_BONUS > DATA_BOOST > CALL_BUNDLE > WEEKEND_SPECIAL

Frequency rules: 7 din mein 1 offer aur 30 din mein zyada se zyada 3 offer; HELD bhi sent history mein count hota hai. Ek customer ke liye pehle OPEN offer resolve hone ke baad hi naya evaluation hota hai.

## Discounts aur acceptance windows

Discounts pehle andaze ke taur par pehli delivery mein:

| Offer type | Discount |
|---|---|
| DATA_BOOST | 30% |
| CALL_BUNDLE | 30% |
| WEEKEND_SPECIAL | 25% |
| EVENT_OFFER | 30% |
| CRICKET_PACK | 20% |

DATA_BOOST aur CALL_BUNDLE ke liye 3 din; WEEKEND_SPECIAL ka Sunday tak 3 din; RECHARGE_BONUS ka 7 din; event offers ki acceptance window event date ke baad chhote lead/after window se nikalti hai. Package offers ki planned acceptance seed se deterministic hoti hai aur accepted date par prepaid balance sufficient ho to package milta hai.

## 2026 event calendar

| Date | Offer | Campaign |
|---|---|---|
| 2026-05-03 se pehle lead window | CRICKET_PACK | PSL |
| 2026-05-27 se pehle 3 din | EVENT_OFFER | Eid-ul-Adha |
| 2026-08-14 se pehle 3 din | EVENT_OFFER | 14 August |
| 2026-08-19 se pehle 1 din | CRICKET_PACK | England Test |

Offer ka exact `campaign_name` aur campaign date model calendar mein rakhe hain.

## Events

`offer_events`: envelope + customer_id, event_date, offer_id, offer_type, action (`SENT / ACCEPTED / EXPIRED / HELD`), group, trigger_rule, campaign_name, package_id, discount_pct. Control ka offer nahi bheja jata aur package_id null hota hai.

Package acceptance par `package_events` bhi banega:

- action `PURCHASE`
- package_id accepted/discounted package se link
- `auto_renew=0`

RECHARGE_BONUS acceptance par target recharge pura hone ke baad free reward package bhi PURCHASE aur `auto_renew=0` ke saath milta hai.

## Tests

- `tests/test_offers_engine.py`, `tests/test_offers_events.py`, `tests/test_offers_hook.py`, `tests/test_offers_model.py`, `tests/test_offers_state.py`
- `python -m pytest tests -q`: 208 pass
- `python -m simulator.verify_core_pipeline`: 15/15 PASS
