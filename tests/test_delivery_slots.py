"""Which delivery dates and hours are offered. Pure, so the boundaries are exact.

THREE RULES THAT ARE NOT THE SAME RULE, and the tests are organised that way:
working hours decide which hours exist, `same_day_cutoff` removes TODAY as a
choice, and `min_lead_time_minutes` removes individual hours that are too soon.
A test that only checked "today disappears eventually" would pass with any two
of the three implemented.

The boundary cases are tested AT the minute they turn over, not comfortably
inside and outside it, because off-by-one at a boundary is the entire failure
mode worth guarding here.
"""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.scheduling.delivery import (
    DEFAULT_HORIZON_DAYS,
    SlotPolicy,
    available_dates,
    available_hours,
    opening_hours,
)

TZ = ZoneInfo("Asia/Tashkent")

#: 2026-09-07 is a Monday (09:00-19:00 by default); 2026-09-13 a Sunday
#: (10:00-17:00), which is the whole reason working hours stayed per-day.
MONDAY = date(2026, 9, 7)
SUNDAY = date(2026, 9, 13)


def policy(**overrides: object) -> SlotPolicy:
    base = {
        "working_hours": DEFAULT_WORKING_HOURS,
        "same_day_cutoff": time(18, 0),
        "min_lead_minutes": 180,
    }
    base.update(overrides)
    return SlotPolicy(**base)  # type: ignore[arg-type]


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)


# --- working hours are per-day ---------------------------------------------


def test_sunday_keeps_its_own_hours() -> None:
    """The reason flat open/close columns were refused: Sunday differs."""
    assert opening_hours(policy(), MONDAY) == (time(9), time(19))
    assert opening_hours(policy(), SUNDAY) == (time(10), time(17))


def test_a_closed_day_offers_no_hours_and_is_not_a_date() -> None:
    shut = dict(DEFAULT_WORKING_HOURS, sun=None)
    p = policy(working_hours=shut)
    assert available_hours(p, SUNDAY, at(MONDAY, 9)) == []
    assert SUNDAY not in available_dates(p, at(MONDAY, 9))


def test_the_closing_hour_is_deliverable() -> None:
    """A shop open until 19:00 can deliver AT 19:00; the last hour is not
    silently dropped by an exclusive range."""
    # A future day, so the lead time does not interfere with this claim.
    assert available_hours(policy(), date(2026, 9, 14), at(MONDAY, 9))[-1] == time(19)
    assert available_hours(policy(), SUNDAY, at(MONDAY, 9))[-1] == time(17)


def test_an_opening_time_with_minutes_rounds_up() -> None:
    """Offering 09:00 when the shop opens 09:30 is a promise it cannot keep."""
    late = dict(DEFAULT_WORKING_HOURS, mon=["09:30", "19:00"])
    # 2026-09-14 is also a Monday, and being in the future keeps the lead
    # time out of the way of what this test is about.
    hours = available_hours(policy(working_hours=late), date(2026, 9, 14), at(MONDAY, 0))
    assert hours[0] == time(10)


# --- min_lead_time_minutes, at the boundary minute -------------------------


def test_the_lead_time_boundary_minute_is_included() -> None:
    """At exactly now + lead, the hour is still orderable. One minute later it
    is not. Testing only 08:00 and 14:00 would pass with any lead value."""
    p = policy(min_lead_minutes=180)
    # 09:00 + 3h == 12:00 exactly.
    assert time(12) in available_hours(p, MONDAY, at(MONDAY, 9, 0))
    # 09:01 + 3h == 12:01, so 12:00 has gone.
    assert time(12) not in available_hours(p, MONDAY, at(MONDAY, 9, 1))
    assert time(13) in available_hours(p, MONDAY, at(MONDAY, 9, 1))


def test_the_lead_time_does_not_touch_a_future_day() -> None:
    """It filters TODAY only. Tomorrow's 09:00 is not 'too soon'."""
    tomorrow = date(2026, 9, 8)
    hours = available_hours(policy(), tomorrow, at(MONDAY, 18, 55))
    assert hours[0] == time(9)


@pytest.mark.parametrize("lead", [0, 60, 600])
def test_a_longer_lead_never_offers_more_hours(lead: int) -> None:
    """Monotonicity, which a hand-written filter can easily get backwards."""
    generous = available_hours(policy(min_lead_minutes=0), MONDAY, at(MONDAY, 9))
    actual = available_hours(policy(min_lead_minutes=lead), MONDAY, at(MONDAY, 9))
    assert set(actual) <= set(generous)


# --- same_day_cutoff removes TODAY, at the DATE step -----------------------


def test_today_survives_at_the_cutoff_minute_and_goes_one_minute_later() -> None:
    p = policy(same_day_cutoff=time(18, 0), min_lead_minutes=0)
    assert available_dates(p, at(MONDAY, 18, 0))[0] == MONDAY
    assert available_dates(p, at(MONDAY, 18, 1))[0] == date(2026, 9, 8)


def test_today_is_dropped_when_the_lead_time_leaves_no_hour() -> None:
    """The cutoff has NOT passed, but nothing is orderable today anyway.

    This is why the filtering happens at the date step: offering today and then
    presenting an empty hour list is a dead end the customer has to back out of.
    """
    p = policy(same_day_cutoff=time(23, 59), min_lead_minutes=180)
    now = at(MONDAY, 17, 30)  # 17:30 + 3h = 20:30, past the 19:00 close
    assert available_hours(p, MONDAY, now) == []
    assert MONDAY not in available_dates(p, now)


def test_the_two_same_day_rules_are_independent() -> None:
    """Guards the guard: a generous cutoff with a strict lead still filters,
    and a strict cutoff with no lead still filters. Either alone must work."""
    lead_only = policy(same_day_cutoff=time(23, 59), min_lead_minutes=600)
    cutoff_only = policy(same_day_cutoff=time(10, 0), min_lead_minutes=0)
    assert MONDAY not in available_dates(lead_only, at(MONDAY, 17, 0))
    assert MONDAY not in available_dates(cutoff_only, at(MONDAY, 10, 1))


# --- daily_order_cap, applied here rather than at submit -------------------


def test_a_full_date_is_absent_from_the_picker() -> None:
    """The standing decision: a full date is never offered, rather than being
    offered and refused after the customer has filled in the whole flow."""
    full = frozenset({date(2026, 9, 8)})
    offered = available_dates(policy(), at(MONDAY, 9), full_dates=full)
    assert date(2026, 9, 8) not in offered
    assert date(2026, 9, 9) in offered, "the cap removed more than the full date"


# --- the horizon -----------------------------------------------------------


def test_the_horizon_is_two_weeks() -> None:
    offered = available_dates(policy(), at(MONDAY, 9))
    assert len(offered) == DEFAULT_HORIZON_DAYS
    assert offered[0] == MONDAY
    assert offered == sorted(offered), "dates must be offered soonest first"
