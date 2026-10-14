"""Bounded sparse RAM observations, not a busy retry loop."""

from scripts.cp25_load import ram_watch


def test_two_consecutive_high_readings_and_five_minute_sleeps():
    now, readings, sleeps = [0.0], [], []
    values = iter([4000, 2500, 4000, 4000])

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds

    ready = ram_watch.wait_for_ram(
        lambda: next(values), lambda: now[0], sleep, readings.append, budget=1200
    )
    assert ready and sleeps == [300, 300, 300]
    assert [row["streak"] for row in readings] == [1, 0, 1, 2]


def test_budget_expiry_never_lowers_floor_or_sleeps_past_deadline():
    now, readings, sleeps = [0.0], [], []

    def sleep(seconds):
        assert now[0] + seconds <= 900, "Wait must be bounded"
        sleeps.append(seconds)
        now[0] += seconds

    ready = ram_watch.wait_for_ram(lambda: 3058, lambda: now[0], sleep, readings.append, budget=900)
    assert not ready and sleeps == [300, 300, 300]
    assert len(readings) == 4 and all(row["streak"] == 0 for row in readings)


def test_last_sleep_is_clipped_to_remaining_budget():
    now, sleeps = [1000.0], []

    def sleep(seconds):
        assert now[0] + seconds <= 1750, "Wait may never extend its deadline"
        sleeps.append(seconds)
        now[0] += seconds

    assert not ram_watch.wait_for_ram(
        lambda: 1000, lambda: now[0], sleep, lambda row: None, budget=750
    )
    assert sleeps == [300, 300, 150] and now[0] == 1750
