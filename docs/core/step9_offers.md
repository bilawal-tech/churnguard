# Step 9: Offers aur Promotions

## Overview
Offers rule-based hain aur sirf ACTIVE customers ko Evening band ke aakhir mein diye jate hain. 6 offer types: `RECHARGE_BONUS`, `DATA_BOOST`, `CALL_BUNDLE`, `WEEKEND_SPECIAL`, `EVENT_OFFER`, `CRICKET_PACK`. Customers treatment aur control (~10%) mein baante hain. Control ko offer nahi jata, sirf `HELD` record hota hai, taake baad mein offer ka asar naapa ja sake. Ek customer ko 7 din mein zyada se zyada 1 offer (30 din mein 3) aur ek waqt mein ek hi OPEN offer milta hai. Offer accept karne ka churn risk par koi asar nahi (churn label saaf rahe) aur `at_risk` chhupi state offers par asar nahi karti. `config/config.yaml` nahi badli, saare numbers `simulator/offers/model.py` ke constants mein hain.

## Files

| File | Kaam |
|---|---|
| `simulator/offers/model.py` | Saare constants (discount, accept chance, calendar, hadein; qeematein Step 13 mein tune hongi) |
| `simulator/offers/engine.py` | Pure functions: trigger, package chunao, discount, accept date, frequency cap, priority |
| `simulator/offers/events.py` | `offer_events` ka record aur `offer_id` |
| `simulator/offers/hooks.py` | Offer hook: usage/recharge jama karna, accept/expire, naye offers |
| `simulator/core/state_store.py` | `offer_state` aur `offer_daily` tables |
| `simulator/verify_core_pipeline.py` | Hooks ki list mein offer hook, check 15 |

## Hooks ki tartib
`customer, package, recharge, usage, tower, offer, lifecycle` (offer hook `tower_hook` ke baad aur `lifecycle_hook` se pehle).
- Har band: `usage_events` se `offer_daily` jama hota hai (`data_mb` = data_mb_* ka sum, `call_min` = off-net + intl minutes) aur `recharge_events` se OPEN `RECHARGE_BONUS` offers ka `recharge_total` badhta hai.
- Evening band ke aakhir mein: pehle OPEN offers accept ya expire hote hain, phir naye offers evaluate hote hain.

## Trigger rules

| Offer | trigger_rule | Shart | Window |
|---|---|---|---|
| `RECHARGE_BONUS` | balance | prepaid, balance < 100 PKR | 7 din |
| `DATA_BOOST` | usage_mix | smartphone, pichle 7 din ka data 28 din ke hafta-wari average se 1.3x zyada (kam az kam 14 din history) | 3 din |
| `CALL_BUNDLE` | usage_mix | off-net + intl minutes ka wahi 1.3x rise | 3 din |
| `WEEKEND_SPECIAL` | weekend | har Friday | Sunday tak |
| `EVENT_OFFER` | event | event se 3 din pehle | event ke agle din tak |
| `CRICKET_PACK` | event | android/ios, match se 1 din pehle | match ke agle din tak |

## Priority, cap aur control
- Ek din mein kai offers ke qabil hon to priority: `EVENT_OFFER` > `CRICKET_PACK` > `RECHARGE_BONUS` > `DATA_BOOST` > `CALL_BUNDLE` > `WEEKEND_SPECIAL`.
- Frequency cap: 7 din mein 1 offer, 30 din mein zyada se zyada 3 (`HELD` bhi ginte hain). Jis customer ka offer OPEN ho usay naya nahi jata.
- Control group: `customer_id` + seed se ek baar tay, hamesha same, ~10%.

## Discount aur accept chance (pehla andaza)

| Offer | Discount | Accept chance |
|---|---|---|
| `DATA_BOOST` | 30% | 12% |
| `CALL_BUNDLE` | 30% | 10% |
| `WEEKEND_SPECIAL` | 25% | 8% |
| `EVENT_OFFER` | 30% | 15% |
| `CRICKET_PACK` | 20% | 10% |

Accept chance window ke andar seed se tay hota hai, kharidne ka din random. Prepaid customer ka balance discounted price se kam ho to window khatam hone par `EXPIRED`.

## Package chunao
Sirf region `["all"]` ke packages, `night_only` nahi, customer ke paas pehle se active nahi, price arpu_band range mein (low < 300, mid 300 se 600, high >= 600). `DATA_BOOST` aur `CRICKET_PACK` ke liye data >= 2048 MB, `CALL_BUNDLE` ke liye off-net + any-net minutes >= 50, `WEEKEND_SPECIAL` aur `EVENT_OFFER` ke liye combo packages. Discount package ki copy par lagta hai (asli package nahi badalta).

## Event calendar 2026

| Tareekh | Offer | campaign_name |
|---|---|---|
| 3 May | `CRICKET_PACK` | `PSL11_Final` (ek source se, verify karna) |
| 27 May | `EVENT_OFFER` | `Eid_ul_Adha` |
| 14 August (Friday) | `EVENT_OFFER` | `Independence_Day` |
| 19 August | `CRICKET_PACK` | `England_Test1` |

14 August Friday hai, to us din priority ki wajah se `EVENT_OFFER` `WEEKEND_SPECIAL` se pehle jata hai. Ramadan aur Eid-ul-Fitr simulation ki date range se pehle hain, is liye shamil nahi.

## RECHARGE_BONUS
Accept customer ke apne recharges ke total se tay hota hai (recharge hook mein koi badlav nahi). 7 din mein total target tak pohnche (low 300, mid 600, high 1000 PKR) to `ACCEPTED`, warna `EXPIRED`. Inaam free asli package hai (price 0): feature phone ko minutes wala, baqi ko data wala, "all" region ka, band ke price cap (low 110, mid 220, high 220 PKR) ke andar.

## Package accept aur package_events
Package offer accept hone par package `auto_renew=0` ke sath `active_packages` mein jata hai (discount sirf ek baar), aur `package_events` mein `PURCHASE` emit hota hai (alag `seq`, taake `event_id` na takraye).

## Events
`offer_events`: `docs/schema/event_schemas.md` dekho. `offer_id` = `OFR-<customer_id>-<band_index>-<offer_type>`. Actions: `SENT`, `ACCEPTED`, `EXPIRED`, `HELD`. Group: `treatment` ya `control`.

## Tests
- `tests/test_offers_model.py`, `tests/test_offers_state.py`, `tests/test_offers_engine.py`, `tests/test_offers_events.py`, `tests/test_offers_hook.py`.
- `python -m pytest tests -q`: **208 passed**.
- `python -m simulator.verify_core_pipeline`: **15/15 checks pass**. Check 15: `offer_events` ke groups, actions, `trigger_rule` aur package link.

## Jo abhi baqi hai (Step 13 mein)
- Accept chance aur discount ki tuning, low band ka `RECHARGE_BONUS` accept rate.
- PSL final ki date (3 May) verify karna.
- Offer hook ka poori run mein loop waqt.
- Check 15 ka package link check tight karna (usi offer se kharida hua package).