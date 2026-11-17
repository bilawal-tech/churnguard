"""Tower hook: har band mein 6 ghante ka loop.

Is band ke usage_events se har tower ka total nikalta hai, phir har ghante ka
load, signal, health aur kharabi tay karta hai. Events: tower_metrics_events
(DOWN na ho tab) aur network_events (outage START/END). State SQLite mein
(sirf resume ke liye).
"""
from simulator.common import make_rng
from simulator.towers import model
from simulator.towers.events import build_metrics_event, build_network_event

HOURS_PER_BAND = 6
BAND_WEIGHTS = (
    (0.25, 0.18, 0.12, 0.10, 0.15, 0.20),  # Night
    (0.10, 0.14, 0.17, 0.19, 0.20, 0.20),  # Morning
    (0.18, 0.17, 0.16, 0.16, 0.16, 0.17),  # Afternoon
    (0.14, 0.18, 0.20, 0.20, 0.17, 0.11),  # Evening
)
LOAD_NOISE_SD = 0.05
_DATA_FIELDS = (
    "data_mb_whatsapp", "data_mb_social", "data_mb_video",
    "data_mb_browsing", "data_mb_other",
)


def _split_int(total, weights):
    """total ko weights ke hisaab se poore numbers mein baanto (jama total)."""
    raw = [total * w for w in weights]
    parts = [int(x) for x in raw]
    left = int(total) - sum(parts)
    order = sorted(range(len(raw)), key=lambda i: (-(raw[i] - parts[i]), i))
    for i in order[:left]:
        parts[i] += 1
    return parts


def _band_totals(usage_events, tower_ids):
    totals = {
        tid: {"users": 0, "minutes": 0.0, "data": 0.0, "dropped": 0}
        for tid in tower_ids
    }
    for e in usage_events:
        tid = e["tower_id"]
        if tid not in totals:
            raise ValueError(f"usage event has unknown tower_id: {tid!r}")
        t = totals[tid]
        t["users"] += 1
        t["minutes"] += (
            (e.get("calls_onnet_min") or 0)
            + (e.get("calls_offnet_min") or 0)
            + (e.get("calls_intl_min") or 0)
        )
        t["data"] += sum((e.get(f) or 0) for f in _DATA_FIELDS)
        t["dropped"] += e.get("dropped_calls") or 0
    return totals


def make_tower_hook(cfg, towers):
    """hook(ctx) banao. `towers` = tower master dicts (tower_id, region, city,
    tower_type, capacity_users). Ye hook usage hook ke BAAD chalna chahiye."""
    by_id = {t["tower_id"]: t for t in towers}
    order = sorted(by_id)
    baselines = {tid: model.baseline_signal(cfg, by_id[tid]) for tid in order}
    critical = cfg["towers"]["critical_load"]

    def hook(ctx):
        clock = ctx.clock
        band_index = clock.index
        weights = BAND_WEIGHTS[clock.band]
        stored = {r["tower_id"]: r for r in ctx.store.all_towers()}
        states = {
            tid: stored.get(tid) or model.initial_state(tid, baselines[tid])
            for tid in order
        }
        totals = _band_totals(ctx.band_events_for("usage_events"), order)
        drops = {tid: _split_int(totals[tid]["dropped"], weights) for tid in order}
        out = []

        for h in range(HOURS_PER_BAND):
            hour_index = band_index * HOURS_PER_BAND + h
            w = weights[h]

            users = {}
            for tid in order:
                rng = make_rng(cfg["seed"], "tower_load", tid, hour_index)
                noise = max(0.0, 1.0 + float(rng.normal(0.0, LOAD_NOISE_SD)))
                users[tid] = totals[tid]["users"] * HOURS_PER_BAND * w * noise
            city_total = {}
            for tid in order:
                city = by_id[tid]["city"]
                city_total[city] = city_total.get(city, 0.0) + users[tid]

            for tid in order:
                old = states[tid]
                load = users[tid] / by_id[tid]["capacity_users"]
                new, ev = model.next_hour(
                    cfg, tid, baselines[tid], old, hour_index, load
                )
                if load > critical:
                    new["last_over_load_hour"] = hour_index

                if ev["went_down"]:
                    last = new.get("last_over_load_hour")
                    recent = []
                    if (last is not None and
                            hour_index - last <= model.CONGESTION_LOOKBACK_HOURS):
                        recent = [critical + 1.0]
                    cause = model.outage_cause(
                        cfg, tid, hour_index, ev["kind"], recent
                    )
                    total = city_total[by_id[tid]["city"]]
                    pct = users[tid] / total * 100.0 if total > 0 else 0.0
                    new.update(
                        outage_id=model.outage_id(tid, hour_index),
                        outage_cause=cause,
                        outage_severity=model.severity_from_pct(pct),
                        outage_affected_pct=pct,
                    )
                    out.append((
                        "network_events",
                        build_network_event(
                            cfg, by_id[tid], band_index, h, "START",
                            new["outage_id"], new["outage_severity"],
                            new["outage_affected_pct"], new["outage_cause"],
                        ),
                    ))

                if ev["recovered"]:
                    out.append((
                        "network_events",
                        build_network_event(
                            cfg, by_id[tid], band_index, h, "END",
                            old["outage_id"], old["outage_severity"],
                            old["outage_affected_pct"], old["outage_cause"],
                        ),
                    ))

                if new["health"] != model.DOWN:
                    out.append((
                        "tower_metrics_events",
                        build_metrics_event(
                            cfg, tid, band_index, h,
                            health=new["health"],
                            signal_dbm=new["signal_dbm"],
                            load=load,
                            active_users=round(users[tid]),
                            total_minutes=totals[tid]["minutes"] * w,
                            total_data_mb=totals[tid]["data"] * w,
                            dropped_calls=drops[tid][h],
                        ),
                    ))
                states[tid] = new

        ctx.store.upsert_towers([states[tid] for tid in order])
        return out

    return hook