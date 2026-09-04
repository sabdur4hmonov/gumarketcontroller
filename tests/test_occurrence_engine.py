"""The occurrence engine. Pure functions, no fixtures, no database.

If any test in this module needed a database, the boundary would be in the
wrong place -- see tests/test_scheduling_purity.py, which enforces that.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest

from gulbot.scheduling.occurrences import (
    DEFAULT_GRACE,
    DEFAULT_OFFSETS,
    TASHKENT,
    WINDOW_END,
    WINDOW_START,
    OccasionSpec,
    PlannedNotification,
    clamp_to_window,
    is_expired,
    is_leap_year,
    is_within_send_window,
    occurrence_date_for,
    plan_notifications,
)


def local(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=TASHKENT)


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


# --- leap years ------------------------------------------------------------


@pytest.mark.parametrize(
    ("year", "expected"),
    [
        (1900, False),  # century, not divisible by 400
        (2000, True),  # century, divisible by 400
        (2024, True),
        (2023, False),
        (2100, False),  # century, not divisible by 400
        (2400, True),
        (1996, True),
    ],
)
def test_gregorian_leap_rule(year: int, expected: bool) -> None:
    assert is_leap_year(year) is expected


# --- occurrence dates ------------------------------------------------------


@pytest.mark.parametrize(
    ("month", "day", "year", "expected"),
    [
        (3, 8, 2027, date(2027, 3, 8)),
        (12, 31, 2026, date(2026, 12, 31)),
        (1, 1, 2027, date(2027, 1, 1)),
        # Feb 29 slides BACK to Feb 28 in a common year, never forward to Mar 1.
        (2, 29, 2024, date(2024, 2, 29)),
        (2, 29, 2023, date(2023, 2, 28)),
        (2, 29, 1900, date(1900, 2, 28)),
        (2, 29, 2000, date(2000, 2, 29)),
        (2, 29, 2100, date(2100, 2, 28)),
    ],
)
def test_occurrence_date_for(month: int, day: int, year: int, expected: date) -> None:
    assert occurrence_date_for(month, day, year) == expected


def test_february_29_never_lands_in_march() -> None:
    for year in range(2020, 2041):
        assert occurrence_date_for(2, 29, year).month == 2


# --- occurrence_year is the year of the OCCASION ---------------------------


def test_occurrence_year_is_the_occasion_year_not_the_send_year() -> None:
    """The definition the whole unique constraint rests on.

    A 3 January birthday at offset -7 is due on 27 December of the PREVIOUS
    calendar year. Its occurrence_year must still be the January year.
    """
    rows = plan_notifications(
        [OccasionSpec(occasion_id=1, month=1, day=3)],
        now_utc=utc(2026, 12, 20, 3),
    )
    by_offset = {row.offset_days: row for row in rows}

    early = by_offset[-7]
    assert early.due_at_utc.astimezone(TASHKENT).date() == date(2026, 12, 27)
    assert early.occurrence_year == 2027, "occurrence_year followed the send year"
    assert early.occurrence_date == date(2027, 1, 3)

    assert {row.occurrence_year for row in rows} == {2027}


def test_year_boundary_does_not_duplicate_across_planning_runs() -> None:
    """December run and January run must agree on the key for the same date."""
    december = plan_notifications(
        [OccasionSpec(occasion_id=1, month=1, day=3)], now_utc=utc(2026, 12, 20, 3)
    )
    january = plan_notifications(
        [OccasionSpec(occasion_id=1, month=1, day=3)], now_utc=utc(2027, 1, 1, 3)
    )
    shared = {r.unique_key for r in december} & {r.unique_key for r in january}
    # The 1 January run can still see the -1 and 0 rows; they must carry the
    # SAME key as December produced, so ON CONFLICT suppresses them.
    assert shared
    for key in shared:
        d = next(r for r in december if r.unique_key == key)
        j = next(r for r in january if r.unique_key == key)
        assert d.due_at_utc == j.due_at_utc
        assert d.occurrence_date == j.occurrence_date


# --- offsets ---------------------------------------------------------------


def test_default_offsets_are_minus7_minus1_and_zero() -> None:
    assert DEFAULT_OFFSETS == (-7, -1, 0)


def test_offsets_are_configurable() -> None:
    rows = plan_notifications(
        [OccasionSpec(occasion_id=1, month=6, day=15)],
        now_utc=utc(2027, 6, 1, 3),
        offsets=(-14, -2),
    )
    assert sorted({r.offset_days for r in rows}) == [-14, -2]


def test_each_offset_produces_exactly_one_row_per_occasion() -> None:
    rows = plan_notifications(
        [OccasionSpec(occasion_id=1, month=6, day=15)], now_utc=utc(2027, 6, 1, 3)
    )
    assert sorted(r.offset_days for r in rows) == [-7, -1, 0]


# --- window clamping -------------------------------------------------------


@pytest.mark.parametrize(
    ("preferred", "expected_hour"),
    [
        (time(9, 0), 9),  # exactly ON the opening bound: not clamped
        (time(10, 0), 10),
        (time(15, 30), 15),
        (time(20, 0), 20),  # exactly ON the closing bound: not clamped
        (time(3, 0), 9),  # before the window opens
        (time(8, 59), 9),  # one minute early
        (time(20, 1), 20),  # one minute late
        (time(23, 30), 20),  # after it closes
        (time(0, 0), 9),
    ],
)
def test_clamp_pulls_the_send_time_inside_the_window(preferred: time, expected_hour: int) -> None:
    moment = clamp_to_window(date(2027, 3, 8), preferred=preferred)
    assert moment.hour == expected_hour
    assert moment.tzinfo is TASHKENT


def test_every_planned_row_is_already_inside_the_window() -> None:
    """Clamping happens at materialisation, so the sender only has to assert."""
    rows = plan_notifications(
        [OccasionSpec(occasion_id=i, month=3, day=i) for i in range(1, 10)],
        now_utc=utc(2027, 1, 20, 3),
        send_time=time(23, 0),
    )
    assert rows
    for row in rows:
        assert is_within_send_window(row.due_at_utc), row


def test_send_window_check_rejects_out_of_window_moments() -> None:
    assert not is_within_send_window(local(2027, 3, 8, 3, 0).astimezone(UTC))
    assert not is_within_send_window(local(2027, 3, 8, 8, 59).astimezone(UTC))
    assert not is_within_send_window(local(2027, 3, 8, 20, 1).astimezone(UTC))
    assert not is_within_send_window(local(2027, 3, 8, 21, 0).astimezone(UTC))
    assert is_within_send_window(local(2027, 3, 8, 10, 0).astimezone(UTC))


def test_both_preset_bounds_are_inside_the_window() -> None:
    """09:00 and 20:00 are the outermost presets a customer can pick.

    Both sit exactly on a bound, so both must be accepted rather than clamped
    inwards or pushed out of the day.
    """
    for hour in (9, 20):
        moment = local(2027, 3, 8, hour, 0).astimezone(UTC)
        assert is_within_send_window(moment), hour
        clamped = clamp_to_window(date(2027, 3, 8), preferred=time(hour, 0))
        assert clamped.hour == hour
        assert clamped.date() == date(2027, 3, 8), "a bound preset changed day"


def test_window_bounds_are_9_to_20_local() -> None:
    assert (time(9, 0), time(20, 0)) == (WINDOW_START, WINDOW_END)


# --- timezone --------------------------------------------------------------


def test_due_times_are_utc_but_derived_from_tashkent_local() -> None:
    rows = plan_notifications(
        [OccasionSpec(occasion_id=1, month=3, day=8)], now_utc=utc(2027, 3, 1, 3)
    )
    for row in rows:
        assert row.due_at_utc.tzinfo is UTC
        assert row.due_at_utc.astimezone(TASHKENT).hour == 10


def test_offset_is_utc_plus_5_all_year() -> None:
    """No DST in Uzbekistan; a month that shows +6 means a bad tz database."""
    for month in range(1, 13):
        assert local(2027, month, 15, 12).utcoffset() == timedelta(hours=5)


def test_naive_now_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        plan_notifications(
            [OccasionSpec(occasion_id=1, month=3, day=8)],
            now_utc=datetime(2027, 3, 1, 3),  # noqa: DTZ001
        )


# --- horizon ---------------------------------------------------------------


def test_nothing_is_planned_in_the_past() -> None:
    rows = plan_notifications(
        [OccasionSpec(occasion_id=1, month=3, day=8)], now_utc=utc(2027, 3, 8, 12)
    )
    now = utc(2027, 3, 8, 12)
    assert all(row.due_at_utc >= now for row in rows)


def test_nothing_is_planned_beyond_the_horizon() -> None:
    now = utc(2027, 1, 1, 3)
    rows = plan_notifications(
        [OccasionSpec(occasion_id=1, month=m, day=15) for m in range(1, 13)],
        now_utc=now,
        horizon_days=45,
    )
    limit = now.astimezone(TASHKENT).date() + timedelta(days=45)
    assert rows
    for row in rows:
        assert row.due_at_utc.astimezone(TASHKENT).date() <= limit


def test_horizon_is_configurable() -> None:
    now = utc(2027, 1, 1, 3)
    short = plan_notifications(
        [OccasionSpec(occasion_id=1, month=m, day=15) for m in range(1, 13)],
        now_utc=now,
        horizon_days=10,
    )
    long = plan_notifications(
        [OccasionSpec(occasion_id=1, month=m, day=15) for m in range(1, 13)],
        now_utc=now,
        horizon_days=60,
    )
    assert len(short) < len(long)


# --- staleness -------------------------------------------------------------


def _planned(due: datetime, occurrence: date) -> PlannedNotification:
    return PlannedNotification(
        occasion_id=1,
        occurrence_year=occurrence.year,
        occurrence_date=occurrence,
        offset_days=0,
        channel="telegram",
        due_at_utc=due,
        merge_key="k",
        merged_occasion_ids=(1,),
    )


def test_fresh_row_is_not_expired() -> None:
    due = local(2027, 3, 8, 10).astimezone(UTC)
    row = _planned(due, date(2027, 3, 8))
    assert not is_expired(row, now_utc=due + timedelta(hours=1))


def test_row_within_grace_is_not_expired() -> None:
    due = local(2027, 3, 8, 10).astimezone(UTC)
    row = _planned(due, date(2027, 3, 8))
    assert not is_expired(row, now_utc=due + DEFAULT_GRACE - timedelta(minutes=1))


def test_row_past_grace_is_expired() -> None:
    """A six-hour outage must not blast a backlog on recovery."""
    due = local(2027, 3, 8, 10).astimezone(UTC)
    row = _planned(due, date(2027, 3, 8))
    assert is_expired(row, now_utc=due + DEFAULT_GRACE + timedelta(minutes=1))


def test_row_whose_occurrence_has_passed_is_expired_even_within_grace() -> None:
    """The hard guard, with no grace period of its own.

    A -1 reminder due at 20:00 is still inside its six-hour grace at 01:00 the
    next day -- but by then the occasion is TODAY, and at 01:00 on the day after
    it has passed. "Your wife's birthday is tomorrow" arriving late is worse
    than silence.
    """
    due = local(2027, 3, 7, 20).astimezone(UTC)
    row = PlannedNotification(
        occasion_id=1,
        occurrence_year=2027,
        occurrence_date=date(2027, 3, 8),
        offset_days=-1,
        channel="telegram",
        due_at_utc=due,
        merge_key="k",
        merged_occasion_ids=(1,),
    )
    just_after = local(2027, 3, 7, 23).astimezone(UTC)
    assert not is_expired(row, now_utc=just_after)

    next_day = local(2027, 3, 9, 0, 30).astimezone(UTC)
    assert is_expired(row, now_utc=next_day)


def test_either_condition_alone_expires_the_row() -> None:
    due = local(2027, 3, 8, 10).astimezone(UTC)

    # Past grace, occurrence still today.
    grace_only = _planned(due, date(2027, 3, 8))
    assert is_expired(grace_only, now_utc=local(2027, 3, 8, 18).astimezone(UTC))

    # Inside grace, but the occurrence was yesterday.
    passed_only = _planned(local(2027, 3, 9, 10).astimezone(UTC), date(2027, 3, 8))
    assert is_expired(passed_only, now_utc=local(2027, 3, 9, 11).astimezone(UTC))


def test_grace_is_configurable() -> None:
    due = local(2027, 3, 8, 10).astimezone(UTC)
    row = _planned(due, date(2027, 3, 8))
    later = due + timedelta(hours=3)
    assert is_expired(row, now_utc=later, grace=timedelta(hours=1))
    assert not is_expired(row, now_utc=later, grace=timedelta(hours=12))
