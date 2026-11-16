# Step 5: tower health

Step 5 adds a tower health model and two event streams: `tower_metrics_events`
(hourly) and `network_events` (outage START and END). It also lets tower health
change the usage stream.

## Hooks and order

Hooks run in this order in every time band: customers, usage, tower.

- The usage hook reads the previous band's tower health from `tower_state` (SQLite).
- The tower hook reads this band's `usage_events` (through `ctx.band_events_for`)
  to get each tower's traffic, then runs a loop of 6 hours.
- Because of this order, a tower failure shows up in usage one band (6 hours) late.
  Traffic in a band is real (counted from usage), not guessed.

## Hourly loop (towers/hook.py)

For each hour and each tower (sorted by tower_id):

1. Traffic: the band total is split over 6 hours with fixed weights per band
   (Night, Morning, Afternoon, Evening). Minutes, data and dropped calls are
   band total x weight (dropped calls in whole numbers). `active_users` and `load`
   are band value x 6 x weight with about 5% noise.
2. `load = active_users / capacity_users`.
3. `model.next_hour` gives the new state: signal, health, failure start or recovery.
4. Events are written. DOWN hours have no `tower_metrics_events`.

## Health

Health follows the signal: above -95 dBm HEALTHY, -95 to -105 DEGRADED, below -105
CRITICAL. DOWN comes from the failure model only. Healthy signal is
3G -78, 4G -75, 5G -72 dBm, plus a fixed per-tower offset (-5 to +5 dBm from the seed)
and about 2 dBm noise per hour.

## Three kinds of trouble (towers/model.py)

| Kind | Chance per HEALTHY tower per hour | What happens | Cause |
|---|---|---|---|
| Sudden failure | 0.01% | HEALTHY to DOWN, no warning | power_cut or fibre_cut |
| Precursor failure | about 0.023% (from failure_precursor_share 0.7) | signal falls in a straight line from the tower's baseline to -110 dBm over 1 to 7 days, then DOWN | hardware, or congestion if load was above 1.0 in the last 6 hours |
| Temporary dip | 0.016%, 5x when load is above critical_load (1.0) | signal goes to -96..-103 dBm for 2 to 8 hours, then recovers (a false alarm, never CRITICAL) | no outage |

DOWN lasts 3 to 12 hours. Only a HEALTHY tower that is not in a precursor or a dip can start
new trouble. Health can flicker near the thresholds because of noise (on purpose).
`degraded_load` (0.85) is not used in Step 5.

## Events

- `tower_metrics_events` (key tower_id): envelope, tower_id, event_date, health
  (HEALTHY, DEGRADED or CRITICAL only), signal_dbm, load, active_users,
  total_minutes, total_data_mb, dropped_calls.
- `network_events` (key region): envelope, outage_id (`OUT-<tower_id>-<start hour index>`,
  the same on START and END), region, tower_id, event_date, status (START or END),
  severity (1 to 3), affected_pct, cause. Tower-level only.
- `affected_pct` = tower active_users / city total active_users x 100 at the START hour.
  Severity: below 3% is 1, 3% to 6% is 2, above 6% is 3.
- `precursor_active` and `failure_at` are hidden simulator state. They are never
  written to events.

## Effect on usage (usage/generator.py)

- `dropped_calls`: base chance 1.5% per call, times 1 (HEALTHY), 3 (DEGRADED),
  8 (CRITICAL), 20 (DOWN).
- If the chosen tower is DOWN, the customer moves to the home tower or one of its
  neighbors that is not DOWN. In a city with one tower, or when every tower is DOWN,
  the customer stays on the DOWN tower.
- If no tower health is given, usage events are exactly as in Step 4.

## State for resume (SQLite tower_state)

Time here is an hour index (band_index x 6 + hour). Columns: health, load, signal_dbm,
precursor_active, failure_at, precursor_start_hour, dip_until_hour, down_until_hour,
outage_id, outage_cause, outage_severity, outage_affected_pct, last_over_load_hour.
Each hour uses its own seeded random generator, so a resumed run gives the same events.

## Known limits

- The sum of tower_metrics is not equal to the tower totals from usage events (DOWN
  hours are not counted). This is normal; Silver and Gold must not force them equal.
- Customers are spread equally over a city's towers, so small 3G towers often run above
  load 1.0 and 5G towers never do. At 100,000 customers load rises about 3.4 times, so
  capacity or the load link must be checked before scaling up.
- A 3-hour outage is seen by the "no readings for about 3 hours" rule (Module A) only
  near its end.
- Severity depends mostly on city size (many towers means a small share per tower).

## Check

`python -m simulator.verify_core_pipeline` runs 9 checks. It raises the failure rates
inside the script (not in `model.py`) so the 5-day test run has outages.