# Step 3: Simulator Core

Status: done, 39 tests pass (git commit d1ce28a)

## Kya hai
Engine jo simulated time chalata hai aur har customer ki state band-ba-band aage barhata hai. Baad ke steps (usage, recharge, churn, offers) isi par hooks ki tarah lagte hain.

## Files (simulator/core/)
| File | Kaam |
|---|---|
| clock.py | SimClock: ek number `index`, us se din, band, waqt (+05:00), backfill ya live |
| state_store.py | SQLite store (state/sim_state.db), 4 tables, crash-safe transaction |
| checkpoint.py | config_hash, naya run ya resume, har band ke baad index save |
| engine.py | Simulator: main loop, hooks, events JSONL mein likhna |

## SQLite tables
- customer_state: balance, status, home tower, last_active, at_risk
- active_packages: baqi quota, expiry, auto_renew
- tower_state: health, load, signal, precursor phase
- sim_meta: index, config_hash, next_customer_no

SQLite sirf abhi ki state rakhta hai (overwrite hoti hai), history nahi. Events (asli data) JSONL, phir Kafka, phir S3 mein jate hain.

## Faisle
- Time ka qadam: 4 bands per din (Night, Morning, Afternoon, Evening), har band 6 ghante.
- Backfill: history_days x 4 bands (180 din = 720 bands), bina wait. Poora hone par engine ruk jata hai; live ke liye run(live=True).
- config_hash mein 6 values: seed, start_date, ids (customer_prefix, customer_width, tower_prefix, tower_width). Badlein to simulator error de kar ruk jata hai. Customers, history_days, rates badal sakte hain.
- Har band ka order: hooks, events likho, state aur index ek transaction mein save, phir clock aage.
- Crash par band dobara chalti hai; duplicate events event_id se hat jate hain.
- Customers hamesha sorted order mein process hote hain (deterministic).

## Aage
Hooks: customers (Step 4), tower (5), usage (6), recharge (7), lifecycle (8), offers (9). offer_state table Step 9 mein add hogi.

## Tests
clock 5, state_store 4, checkpoint 5, engine 5.