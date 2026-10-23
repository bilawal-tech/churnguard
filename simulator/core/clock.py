"""Simulated clock: 4 time-bands per day, backfill first, then live."""
from datetime import datetime, timedelta, timezone

PKT = timezone(timedelta(hours=5))
BANDS = ("Night", "Morning", "Afternoon", "Evening")
BANDS_PER_DAY = 4
BAND_HOURS = 6


class SimClock:
    def __init__(self, start_date, history_days, live_speed=1.0, index=0):
        y, m, d = (int(x) for x in str(start_date).split("-"))
        self.start = datetime(y, m, d, tzinfo=PKT)
        self.history_days = history_days
        self.live_speed = live_speed
        self.index = index

    @classmethod
    def from_config(cls, cfg, index=0):
        return cls(
            cfg["start_date"],
            cfg["history_days"],
            cfg["live_speed_sim_hours_per_real_sec"],
            index,
        )

    @property
    def day(self):
        return self.index // BANDS_PER_DAY

    @property
    def band(self):
        return self.index % BANDS_PER_DAY

    @property
    def band_name(self):
        return BANDS[self.band]

    @property
    def band_start(self):
        return self.start + timedelta(hours=BAND_HOURS * self.index)

    @property
    def band_end(self):
        return self.band_start + timedelta(hours=BAND_HOURS)

    @property
    def event_date(self):
        return self.band_start.date().isoformat()

    @property
    def is_backfill(self):
        return self.index < self.history_days * BANDS_PER_DAY

    def advance(self):
        self.index += 1

    def seconds_to_wait(self):
        if self.is_backfill:
            return 0.0
        return BAND_HOURS / self.live_speed