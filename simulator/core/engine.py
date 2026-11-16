"""Main simulator loop: process one time band at a time."""
import json
import time
from pathlib import Path

from simulator.core.checkpoint import Checkpoint
from simulator.core.clock import BANDS_PER_DAY, SimClock


class BandContext:
    """What a hook sees for one band."""

    def __init__(self, clock, store, next_customer_no):
        self.clock = clock
        self.store = store
        self.next_customer_no = next_customer_no
        self.band_events = []

    def active_customer_ids(self):
        rows = self.store.conn.execute(
            "SELECT customer_id FROM customer_state "
            "WHERE status='ACTIVE' ORDER BY customer_id"
        ).fetchall()
        return [r["customer_id"] for r in rows]

    def band_events_for(self, topic):
        """Is band mein ab tak ke hooks ke events, sirf ek topic ke."""
        return [e for t, e in self.band_events if t == topic]


class Simulator:
    def __init__(self, cfg, store, out_dir, hooks=None, sleep=time.sleep):
        self.cfg = cfg
        self.store = store
        self.out_dir = Path(out_dir)
        self.hooks = hooks or []
        self.sleep = sleep
        self.checkpoint = Checkpoint(store, cfg)

    def _write(self, events):
        by_topic = {}
        for topic, event in events:
            by_topic.setdefault(topic, []).append(event)
        for topic, items in by_topic.items():
            self.out_dir.mkdir(parents=True, exist_ok=True)
            with open(self.out_dir / f"{topic}.jsonl", "a", encoding="utf-8") as f:
                for e in items:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")

    def run(self, live=False, stop_after=None):
        start = self.checkpoint.start()
        clock = SimClock.from_config(self.cfg, index=start)
        backfill_end = self.cfg["history_days"] * BANDS_PER_DAY
        next_no = self.checkpoint.next_customer_no()
        done = 0
        while True:
            if not live and clock.index >= backfill_end:
                break
            if stop_after is not None and done >= stop_after:
                break
            ctx = BandContext(clock, self.store, next_no)
            with self.store.transaction():
                events = []
                ctx.band_events = events
                for hook in self.hooks:
                    events.extend(hook(ctx))
                self._write(events)
                self.checkpoint.save(clock.index + 1, ctx.next_customer_no)
            next_no = ctx.next_customer_no
            wait = clock.seconds_to_wait() if live else 0
            clock.advance()
            done += 1
            if wait:
                self.sleep(wait)
        return clock.index