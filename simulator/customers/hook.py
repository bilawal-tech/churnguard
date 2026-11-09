"""Customer hook: how many new customers sign up in each band."""
from simulator.core.clock import BANDS_PER_DAY
from simulator.core.clock import BANDS_PER_DAY
from simulator.core.state_store import CUSTOMER_COLS
from simulator.customers.events import build_customer_event, build_profile_event
from simulator.customers.generator import build_customer, towers_by_city


def _burst_weights(cfg):
    c = cfg["customers"]
    decay = c["burst_decay"]
    if decay <= 0:
        raise ValueError("customers.burst_decay 0 se bara hona chahiye")
    return [decay ** k for k in range(c["initial_burst_days"])]


def day_total(cfg, day):
    """New customers for one simulated day (burst days, then steady)."""
    c = cfg["customers"]
    if day < c["initial_burst_days"]:
        weights = _burst_weights(cfg)
        whole = sum(weights)
        before = sum(weights[:day])
        upto = before + weights[day]
        return round(c["initial"] * upto / whole) - round(c["initial"] * before / whole)
    return c["new_per_day"]


def new_customers_in_band(cfg, index):
    """New customers in one band, split equally across the day's 4 bands."""
    day = index // BANDS_PER_DAY
    band = index % BANDS_PER_DAY
    total = day_total(cfg, day)
    return (round(total * (band + 1) / BANDS_PER_DAY)
            - round(total * band / BANDS_PER_DAY))
def make_customer_hook(cfg, towers):
    """Return a hook(ctx) for the engine that signs up this band's customers."""
    by_city = towers_by_city(towers, cfg)

    def hook(ctx):
        index = ctx.clock.index
        count = new_customers_in_band(cfg, index)
        rows = []
        events = []
        for _ in range(count):
            n = ctx.next_customer_no
            customer = build_customer(cfg, by_city, n, index)
            rows.append({c: customer[c] for c in CUSTOMER_COLS})
            events.append(
                ("customer_events", build_customer_event(cfg, customer, n, index))
            )
            events.append(
                ("profile_events", build_profile_event(cfg, customer, n, index))
            )
            ctx.next_customer_no = n + 1
        if rows:
            ctx.store.upsert_customers(rows)
        return events

    return hook