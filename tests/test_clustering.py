"""Merging and the weekly cap.

The two rules that decide how many messages a customer actually receives, and
the two most likely to be subtly wrong. Everything here is pure.
"""

from __future__ import annotations

import itertools
import random
from datetime import UTC, datetime, timedelta
from datetime import time as datetime_time

import pytest

from gulbot.scheduling.occurrences import (
    CAP_WINDOW,
    DEFAULT_WEEKLY_CAP,
    TASHKENT,
    OccasionSpec,
    PlannedNotification,
    is_within_send_window,
    plan_notifications,
)

NOW = datetime(2027, 2, 20, 3, 0, tzinfo=UTC)


def messages(rows: list[PlannedNotification]) -> dict[str, list[PlannedNotification]]:
    grouped: dict[str, list[PlannedNotification]] = {}
    for row in rows:
        grouped.setdefault(row.merge_key, []).append(row)
    return grouped


def plan(specs: list[OccasionSpec], **kwargs: object) -> list[PlannedNotification]:
    return plan_notifications(specs, now_utc=NOW, **kwargs)  # type: ignore[arg-type]


# --- merging ---------------------------------------------------------------


@pytest.mark.parametrize("gap", [0, 1, 2])
def test_occasions_within_the_window_merge(gap: int) -> None:
    rows = plan([OccasionSpec(1, month=3, day=8), OccasionSpec(2, month=3, day=8 + gap)])
    assert len(messages(rows)) == 3, "expected one message per offset, not per occasion"
    assert all(row.is_merged for row in rows)
    assert all(row.merged_occasion_ids == (1, 2) for row in rows)


@pytest.mark.parametrize("gap", [3, 4, 10])
def test_occasions_outside_the_window_do_not_merge(gap: int) -> None:
    rows = plan([OccasionSpec(1, month=3, day=8), OccasionSpec(2, month=3, day=8 + gap)])
    assert not any(row.is_merged for row in rows)


def test_three_occasions_in_one_week_become_three_messages_not_nine() -> None:
    """The case the rule exists for."""
    rows = plan(
        [
            OccasionSpec(1, month=3, day=8, label="Xotinim"),
            OccasionSpec(2, month=3, day=9, label="Onam"),
            OccasionSpec(3, month=3, day=10, label="Otam"),
        ]
    )
    assert len(rows) == 9, "one row per occasion per offset, so the unique key holds"
    assert len(messages(rows)) == 3, "but only three messages"


def test_merging_chains_through_adjacent_dates() -> None:
    """1, 3 and 5 March all merge: each is within two days of its neighbour.

    Documented behaviour, not an accident -- the literal reading of "within two
    days of each other".
    """
    rows = plan(
        [
            OccasionSpec(1, month=3, day=1),
            OccasionSpec(2, month=3, day=3),
            OccasionSpec(3, month=3, day=5),
        ]
    )
    assert all(row.merged_occasion_ids == (1, 2, 3) for row in rows)


def test_merge_window_is_configurable() -> None:
    specs = [OccasionSpec(1, month=3, day=8), OccasionSpec(2, month=3, day=11)]
    assert not any(row.is_merged for row in plan(specs))
    assert all(row.is_merged for row in plan(specs, merge_window_days=3))


def test_merged_reminder_is_anchored_on_the_earliest_date() -> None:
    """A merged reminder must never arrive after the first date it warns about."""
    rows = plan([OccasionSpec(1, month=3, day=10), OccasionSpec(2, month=3, day=8)])
    day_of = [r for r in rows if r.offset_days == 0]
    local_dates = {r.due_at_utc.astimezone(TASHKENT).date().day for r in day_of}
    assert local_dates == {8}


def test_merged_rows_keep_their_own_occurrence_dates() -> None:
    """The sender needs each date to render "Onam 08.03, Otam 10.03"."""
    rows = plan([OccasionSpec(1, month=3, day=8), OccasionSpec(2, month=3, day=10)])
    day_of = [r for r in rows if r.offset_days == 0]
    assert {r.occasion_id: r.occurrence_date.day for r in day_of} == {1: 8, 2: 10}


def test_merging_across_the_year_boundary_keeps_separate_occurrence_years() -> None:
    """31 December and 2 January merge, but their occurrence years differ."""
    rows = plan_notifications(
        [OccasionSpec(1, month=12, day=31), OccasionSpec(2, month=1, day=2)],
        now_utc=datetime(2026, 12, 15, 3, tzinfo=UTC),
    )
    day_of = [r for r in rows if r.offset_days == 0]
    assert all(r.is_merged for r in day_of)
    assert {r.occasion_id: r.occurrence_year for r in day_of} == {1: 2026, 2: 2027}


# --- order independence ----------------------------------------------------

ORDER_SPECS = [
    OccasionSpec(1, month=3, day=8),
    OccasionSpec(2, month=3, day=9),
    OccasionSpec(3, month=3, day=14),
    OccasionSpec(4, month=3, day=15),
]


def _fingerprint(rows: list[PlannedNotification]) -> list[tuple]:
    return sorted(
        (r.occasion_id, r.occurrence_year, r.offset_days, r.due_at_utc, r.merge_key) for r in rows
    )


def test_result_is_identical_for_every_input_permutation() -> None:
    baseline = _fingerprint(plan(list(ORDER_SPECS)))
    for permutation in itertools.permutations(ORDER_SPECS):
        assert _fingerprint(plan(list(permutation))) == baseline


def test_merge_keys_are_order_independent() -> None:
    baseline = {r.occasion_id: r.merge_key for r in plan(list(ORDER_SPECS))}
    for permutation in itertools.permutations(ORDER_SPECS):
        assert {r.occasion_id: r.merge_key for r in plan(list(permutation))} == baseline


def test_order_independence_holds_on_random_sets() -> None:
    rng = random.Random(20260903)
    for _ in range(40):
        specs = [
            OccasionSpec(i, month=rng.randint(1, 12), day=rng.randint(1, 28))
            for i in range(1, rng.randint(2, 7))
        ]
        baseline = _fingerprint(plan(specs))
        shuffled = list(specs)
        for _ in range(3):
            rng.shuffle(shuffled)
            assert _fingerprint(plan(shuffled)) == baseline


# --- the weekly cap --------------------------------------------------------


def test_cap_default_is_four() -> None:
    assert DEFAULT_WEEKLY_CAP == 4
    assert timedelta(days=7) == CAP_WINDOW


def _message_times(rows: list[PlannedNotification]) -> list[datetime]:
    return sorted({group[0].due_at_utc for group in messages(rows).values()})


def _max_in_any_window(times: list[datetime]) -> int:
    return max(
        (sum(1 for other in times if t - CAP_WINDOW < other <= t) for t in times),
        default=0,
    )


def test_no_rolling_week_exceeds_the_cap() -> None:
    specs = [OccasionSpec(i, month=3, day=i) for i in range(1, 20)]
    rows = plan(specs)
    assert _max_in_any_window(_message_times(rows)) <= DEFAULT_WEEKLY_CAP


def test_cap_holds_on_random_dense_sets() -> None:
    rng = random.Random(4242)
    for _ in range(40):
        specs = [
            OccasionSpec(i, month=3, day=rng.randint(1, 28)) for i in range(1, rng.randint(5, 15))
        ]
        rows = plan(specs)
        assert _max_in_any_window(_message_times(rows)) <= DEFAULT_WEEKLY_CAP


def test_cap_is_configurable() -> None:
    specs = [OccasionSpec(i, month=3, day=i) for i in range(1, 20)]
    tight = plan(specs, weekly_cap=2)
    assert _max_in_any_window(_message_times(tight)) <= 2


def test_cap_drops_the_least_urgent_message_first() -> None:
    """A day-of reminder must never be dropped while a -7 survives.

    Telling a customer "tomorrow is your father's birthday" and then going
    silent on the day is worse than not reminding at all.
    """
    specs = [OccasionSpec(i, month=3, day=1 + 4 * (i - 1)) for i in range(1, 6)]
    rows = plan(specs)
    kept = {(r.occasion_id, r.offset_days) for r in rows}

    for spec in specs:
        assert (spec.occasion_id, 0) in kept, f"occasion {spec.occasion_id} lost its day-of"

    dropped = {
        (spec.occasion_id, offset)
        for spec in specs
        for offset in (-7, -1, 0)
        if (spec.occasion_id, offset) not in kept
    }
    assert dropped, "this scenario is supposed to exercise the cap"
    assert all(offset == -7 for _, offset in dropped), dropped


def test_a_merged_message_costs_one_slot_not_three() -> None:
    """Merging is what makes the cap survivable for a busy customer."""
    clustered = [OccasionSpec(i, month=3, day=8 + i) for i in range(0, 3)]
    spread = [OccasionSpec(i, month=3, day=1 + 5 * i) for i in range(0, 3)]
    assert len(messages(plan(clustered))) < len(messages(plan(spread)))


def test_cap_never_splits_a_merge_group() -> None:
    """Half a merged message would render an incomplete list of dates."""
    rng = random.Random(999)
    for _ in range(30):
        specs = [
            OccasionSpec(i, month=3, day=rng.randint(1, 28)) for i in range(1, rng.randint(4, 12))
        ]
        rows = plan(specs)
        for group in messages(rows).values():
            expected = group[0].merged_occasion_ids
            assert tuple(sorted(r.occasion_id for r in group)) == expected


# --- the unique key --------------------------------------------------------


def test_no_two_rows_collide_on_the_unique_key() -> None:
    specs = [OccasionSpec(i, month=3, day=i) for i in range(1, 15)]
    keys = [row.unique_key for row in plan(specs)]
    assert len(keys) == len(set(keys))


def test_unique_key_holds_across_random_sets() -> None:
    """(occasion_id, occurrence_year, offset_days, channel) -- the constraint."""
    rng = random.Random(31337)
    for _ in range(200):
        specs = [
            OccasionSpec(
                occasion_id=i,
                month=rng.randint(1, 12),
                day=rng.randint(1, 28),
            )
            for i in range(1, rng.randint(2, 10))
        ]
        now = datetime(2027, rng.randint(1, 12), rng.randint(1, 28), 3, tzinfo=UTC)
        rows = plan_notifications(specs, now_utc=now, horizon_days=rng.choice([30, 45, 90]))
        keys = [row.unique_key for row in rows]
        assert len(keys) == len(set(keys)), f"collision with now={now} specs={specs}"


def test_unique_key_holds_when_merging_is_heavy() -> None:
    """Merging must never produce a colliding tuple."""
    rng = random.Random(5150)
    for _ in range(100):
        base = rng.randint(1, 25)
        specs = [
            OccasionSpec(i, month=3, day=min(28, base + rng.randint(0, 2))) for i in range(1, 8)
        ]
        rows = plan(specs)
        keys = [row.unique_key for row in rows]
        assert len(keys) == len(set(keys)), specs


def test_february_29_occasions_do_not_collide_across_years() -> None:
    rows = plan_notifications(
        [OccasionSpec(1, month=2, day=29)],
        now_utc=datetime(2027, 1, 1, 3, tzinfo=UTC),
        horizon_days=400,
    )
    keys = [row.unique_key for row in rows]
    assert len(keys) == len(set(keys))
    assert {r.occurrence_date.day for r in rows} <= {28, 29}


# --- independence from the send time ---------------------------------------


SEND_TIMES = [datetime_time(9, 0), datetime_time(10, 0), datetime_time(13, 0), datetime_time(20, 0)]


def _shape(rows: list[PlannedNotification]) -> list[tuple]:
    """What merging and the cap decided, with the clock time removed."""
    return sorted(
        (
            r.occasion_id,
            r.occurrence_year,
            r.offset_days,
            r.occurrence_date.isoformat(),
            r.merged_occasion_ids,
            r.due_at_utc.date().isoformat(),
        )
        for r in rows
    )


@pytest.mark.parametrize(
    "specs",
    [
        [OccasionSpec(1, month=3, day=8), OccasionSpec(2, month=3, day=9)],
        [OccasionSpec(i, month=3, day=1 + 4 * (i - 1)) for i in range(1, 6)],
        [OccasionSpec(i, month=3, day=i) for i in range(1, 16)],
    ],
    ids=["merging", "cap-bites", "cap-bites-hard"],
)
def test_merge_and_cap_do_not_depend_on_the_send_time(specs: list[OccasionSpec]) -> None:
    """Moving the window bound must not silently reshape anyone's reminders.

    Offsets are whole days and the cap is per customer, so every message in one
    plan shares a time-of-day; a uniform shift leaves every comparison equal.
    This pins that, so changing WINDOW_START stays a presentation decision
    rather than a scheduling one.
    """
    shapes = {send_time: _shape(plan(specs, send_time=send_time)) for send_time in SEND_TIMES}
    distinct = {tuple(shape) for shape in shapes.values()}
    assert len(distinct) == 1, "the send time changed which reminders survive"


@pytest.mark.parametrize("send_time", [datetime_time(9, 0), datetime_time(20, 0)])
def test_the_preset_bounds_survive_planning_intact(send_time: datetime_time) -> None:
    """09:00 and 20:00 are the outermost presets; neither is clamped or moved."""
    rows = plan([OccasionSpec(1, month=3, day=8)], send_time=send_time)
    assert rows
    assert {r.due_at_utc.astimezone(TASHKENT).hour for r in rows} == {send_time.hour}
    assert all(is_within_send_window(r.due_at_utc) for r in rows)
