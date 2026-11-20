"""Post-hook dirty data processor: nulls, exact duplicates, aur late events."""
from simulator.common import make_rng
from simulator.core.clock import BAND_HOURS
from simulator.dirty import model as m


def dirty_settings(cfg):
    """Config ke dirty_data settings ko defaults ke saath merge karna."""
    merged = dict(m.DEFAULT_DIRTY_CONFIG)
    merged.update(cfg.get("dirty_data") or {})
    return merged


def make_dirty_processor(cfg):
    """Return post_hook(ctx, events) jo hooks ke baad aur JSONL likhne se pehle chalta hai."""
    settings = dirty_settings(cfg)
    seed = cfg["seed"]
    null_rate = float(settings["null_rate"])
    dup_rate = float(settings["duplicate_rate"])
    late_rate = float(settings["late_rate"])
    max_delay_bands = max(1, int(settings["late_max_hours"]) // BAND_HOURS)

    def process(ctx, events):
        if not settings["enabled"]:
            return events

        band_idx = ctx.clock.index
        due_delayed = ctx.store.pop_delayed_events(band_idx)
        emitted = []

        for topic, event in events:
            ev = dict(event)
            rng = make_rng(seed, "dirty", topic, ev["event_id"])

            # 1. Null injection (non-envelope, non-primary-key fields)
            if null_rate > 0 and rng.random() < null_rate:
                candidates = [
                    f for f in m.NULLABLE_FIELDS_BY_TOPIC.get(topic, ())
                    if f in ev and ev[f] is not None
                ]
                if candidates:
                    chosen_field = rng.choice(candidates)
                    ev[chosen_field] = None

            # 2. Late arrival (future band ke liye SQLite mein hold karna)
            if late_rate > 0 and rng.random() < late_rate:
                delay_bands = int(rng.integers(1, max_delay_bands + 1))
                ctx.store.add_delayed_event(band_idx + delay_bands, topic, ev)
                continue

            emitted.append((topic, ev))

            # 3. Exact duplicate (same event_id ke saath dobara emit karna)
            if dup_rate > 0 and rng.random() < dup_rate:
                emitted.append((topic, dict(ev)))

        return due_delayed + emitted

    return process