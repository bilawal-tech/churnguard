"""Usage hook: one usage_events record per ACTIVE customer in every band."""
from simulator.usage.generator import build_usage_event, neighbor_map


def make_usage_hook(cfg, towers):
    """Return a hook(ctx) for the engine.

    `towers` must come from add_neighbors(build_towers(cfg)), so that every
    tower has neighbor_tower_ids. Tower health comes from tower_state (the
    previous band's end state), so the tower hook must run AFTER this hook.
    """
    if any("neighbor_tower_ids" not in t for t in towers):
        raise ValueError(
            "towers mein neighbor_tower_ids nahi hain; add_neighbors(...) wali list do"
        )
    neighbors = neighbor_map(towers)

    def hook(ctx):
        health = {r["tower_id"]: r["health"] for r in ctx.store.all_towers()}
        rows = ctx.store.conn.execute(
            "SELECT customer_id, home_tower_id FROM customer_state "
            "WHERE status='ACTIVE' ORDER BY customer_id"
        ).fetchall()
        return [
            (
                "usage_events",
                build_usage_event(
                    cfg, r["customer_id"], r["home_tower_id"], neighbors,
                    ctx.clock, tower_health=health,
                ),
            )
            for r in rows
        ]

    return hook