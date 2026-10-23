from simulator.core.clock import SimClock


def make(index=0):
    return SimClock("2026-04-01", history_days=5, live_speed=2.0, index=index)


def test_first_band():
    c = make()
    assert c.day == 0 and c.band_name == "Night"
    assert c.band_start.isoformat() == "2026-04-01T00:00:00+05:00"


def test_four_bands_make_one_day():
    c = make()
    for _ in range(4):
        c.advance()
    assert c.day == 1 and c.band == 0
    assert c.event_date == "2026-04-02"


def test_band_end_is_next_band_start():
    c = make(index=5)
    end = c.band_end
    c.advance()
    assert c.band_start == end


def test_backfill_then_live():
    assert make(19).is_backfill and make(19).seconds_to_wait() == 0
    assert not make(20).is_backfill
    assert make(20).seconds_to_wait() == 3.0


def test_resume_matches_advancing():
    a = make()
    for _ in range(7):
        a.advance()
    b = make(index=7)
    assert a.band_start == b.band_start and a.band_name == b.band_name