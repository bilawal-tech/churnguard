# Step 8: Lifecycle aur churn

Is step mein customer ka status badalta hai (ACTIVE, SUSPENDED, CHURNED, REACTIVATED). Churn simulator khud banata hai, aur wajah (churn_reason) sirf ground truth hai, model features mein kabhi nahi jati.

## Files

| File | Kaam |
|---|---|
| `simulator/lifecycle/model.py` | Saare constants (qeematein Step 13 mein tune hongi) |
| `simulator/lifecycle/engine.py` | Pure functions: adders, churn chance, reason, status tabdili, usage scale |
| `simulator/lifecycle/events.py` | `lifecycle_events` ka record |
| `simulator/lifecycle/hooks.py` | `make_lifecycle_hook(cfg)`: SQLite se judta hai, roz ka faisla |
| `simulator/core/state_store.py` | `customer_daily` table, `customer_state` mein `zero_balance_since` aur `at_risk_since` |
| `simulator/usage/hook.py` | At-risk customer ka usage scale |
| `simulator/billing/hooks.py` | At-risk customer ka recharge skip |

## Hooks ki tartib

customer, package, recharge, usage, tower, **lifecycle** (sab se aakhir mein). Lifecycle hook har band us band ke usage events `customer_daily` mein jama karta hai. Faisla roz ek baar, Evening band ke aakhir mein hota hai. Naya status agle din ke Night band se lagu hota hai. Event ka `event_time` Evening band ki shuruat hai.

## Churn chance

Roz har ACTIVE customer ka:

    chance = BASE_DAILY_CHURN x (1 + risk_score) x noise
    postpaid ho to x POSTPAID_CHURN_FACTOR (0.5)
    at_risk ho to x AT_RISK_CHURN_MULTIPLIER (2.0)
    noise = 1 + NOISE_SD (0.25) x standard normal

`risk_score` chaar adders ka jama hai:

| Adder | Kaise banta hai | Hadd |
|---|---|---|
| price | `PRICE_WEIGHT` (0.6) x arpu_band hassasiyat (low 1.0, mid 0.5, high 0.2) | 0.6 tak |
| usage girawat | 7 din ka usage vs 28 din ka hafta-wari average; 50% se kam par adder, jitni girawat utna bara. Kam az kam 14 din ki history | 2.0 |
| network | 7 din ka dropped_calls / calls ratio; 0.03 se upar adder, 0.15 par poora. Kam az kam 20 calls | 2.0 |
| zero balance (sirf prepaid) | balance 0 ke din; 14 din mein poora | 1.5 |

Usage ek number mein: us din ke 4 bands ka `spend_from_package + spend_from_balance` ka jama. Calls = (onnet + offnet + intl minutes) / 3. Ye `customer_daily` table mein har din ek row per customer hai; 28 din se purani rows delete hoti hain.

## Prepaid inactivity

`last_active` usage se update hota hai (din ke aakhir mein, agar aaj ka usage 0 se zyada tha). Inactivity ke din = (abhi ka band index - last_active) / 4.

- 14 din inactive: ACTIVE se SUSPENDED
- 30 din inactive: SUSPENDED se CHURNED (churn_reason INACTIVITY)

SUSPENDED aur CHURNED customer ka usage, package kharidna aur auto-renew band hai. Postpaid mein balance hota hi nahi, is liye wahan inactivity ka raasta nahi: postpaid seedha ACTIVE se CHURNED hota hai, kabhi SUSPENDED nahi.

## REACTIVATED

Sirf SUSPENDED customer, 3% per din (`REACTIVATE_CHANCE_PER_DAY`). Ek recharge event banta hai (reactivation recharge mein balance_before 50 se upar bhi ho sakta hai) aur ek hi lifecycle event (SUSPENDED se REACTIVATED). Customer ka status seedha ACTIVE ho jata hai, at_risk saaf. CHURNED final hai.

## At-risk (chhupi state)

`risk_score` 1.0 (`AT_RISK_THRESHOLD`) se upar jaye to `at_risk` = 1. 14 din (`AT_RISK_RECOVER_DAYS`) tak score neeche rahe to wapas 0. Ye kabhi publish nahi hota aur model features mein nahi jata. At-risk customer disengage karta hai:

- usage `AT_RISK_USAGE_FACTOR` (0.4) par aa jata hai (usage hook mein, billing se pehle)
- balance 50 se kam ho to bhi recharge sirf `AT_RISK_RECHARGE_CHANCE` (0.15) per band

Is se "pehle signals, phir churn" wali kahani banti hai: usage girti hai (usage girawat adder), balance 0 hota hai, inactivity ka raasta chalta hai.

## churn_reason

Risk wale churn mein: jis adder ka naam sab se bara ho. price HIGH_PRICE, network POOR_NETWORK, usage USAGE_DECLINE, zero balance INACTIVITY. `COMPETITOR_OFFER` ~10% (`COMPETITOR_OFFER_SHARE`) random churners ko diya jata hai, aur tab bhi jab koi adder 0 se bara na ho. 30 din wale inactivity churn ka reason INACTIVITY. Risk wale churn mein `inactivity_days` null hai.

## Events

`lifecycle_events`: envelope + customer_id, event_date, from_status, to_status, churn_reason (nullable), inactivity_days (nullable). Schema: `docs/schema/event_schemas.md`. Reactivation par `recharge_events` ka bhi ek record banta hai.

## Tests

- `tests/test_lifecycle_state.py`, `test_lifecycle_engine.py`, `test_lifecycle_effects.py`, `test_lifecycle_hook.py`
- `python -m pytest tests -q`: 179 pass
- `python -m simulator.verify_core_pipeline`: 14/14 PASS (checks 13 lifecycle events sahi, 14 SUSPENDED/CHURNED ka usage band). Script mein churn aur inactivity ki hadein sirf us script ke liye chhoti ki jati hain (`BASE_DAILY_CHURN` 0.05, `INACTIVE_SUSPEND_DAYS` 2, `INACTIVE_CHURN_DAYS` 4, `REACTIVATE_CHANCE_PER_DAY` 0.3), asli constants nahi badalte.

## Jo abhi baqi hai (Step 13 mein)

- Churn rate ~26.5% par tune karna (`BASE_DAILY_CHURN` shuruati 0.001 hai).
- `NETWORK_NORMAL_RATIO` (0.03) sirf andaza hai, asli dropped_calls ratio dekh kar theek karna.
- At-risk ki hadein (threshold, usage x0.4) aur usage girawat ka asar tune hoga.
- Lifecycle hook roz Evening par har customer par Python loop chalata hai; 100,000 customers par waqt Step 13 mein naapna.
- `last_active` abhi sirf usage se update hota hai (recharge ya package kharidna alag nahi gina jata).
- Asli simulator runner abhi nahi bana, hooks ki list sirf `verify_core_pipeline.py` mein hai.
