"""Which delivery dates and hours a customer may pick.

Pure, like CP4's occurrence engine next door -- no database, no Telegram, no
settings. Every input is a value, so the boundary cases can be tested at the
exact minute they turn over rather than approximately.

THREE RULES, and they are not the same rule:

  WORKING HOURS decide which hours exist on a given day at all. They are
  PER-DAY: `shops.working_hours` is a JSONB map with its own open/close for
  each weekday, and Sunday genuinely differs (10:00-17:00 by default). Flat
  open/close columns would have quietly flattened that away.

  SAME_DAY_CUTOFF removes TODAY as a choice once the shop stops accepting
  same-day work. It is applied at the DATE step, not the hour step -- offering
  today and then presenting an empty hour list is a dead end the customer has
  to back out of.

  MIN_LEAD_TIME_MINUTES removes individual hours that are too soon. It bites
  tighter than the cutoff and independently of it: at 09:00 with a three-hour
  lead, today is still offered but its first available hour is 12:00.

`daily_order_cap` is enforced here too, by excluding dates already at capacity.
That is the standing decision from the original design review -- a full date is
simply ABSENT from the picker, rather than accepted and rejected at submit.

Note the deliberate absence of the 09:00-20:00 reminder window. That governs
outbound reminders only and never filters delivery slots; they are different
rules that happen to involve times of day.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

#: JSONB keys, in `date.weekday()` order.
WEEKDAY_KEYS: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

#: How far ahead the date picker offers. Two weeks covers "next Saturday" and
#: every occasion a reminder fires for, without a picker nobody can scan.
DEFAULT_HORIZON_DAYS = 14


@dataclass(frozen=True)
class SlotPolicy:
    """One shop's delivery rules, as values."""

    working_hours: dict[str, list[str] | None]
    same_day_cutoff: time
    min_lead_minutes: int
    horizon_days: int = DEFAULT_HORIZON_DAYS


def _parse(clock: str) -> time:
    hour, minute = clock.split(":")[:2]
    return time(int(hour), int(minute))


def opening_hours(policy: SlotPolicy, day: date) -> tuple[time, time] | None:
    """(open, close) for this weekday, or None if the shop is shut."""
    entry = policy.working_hours.get(WEEKDAY_KEYS[day.weekday()])
    if not entry:
        return None
    return _parse(entry[0]), _parse(entry[1])


def available_hours(policy: SlotPolicy, day: date, now_local: datetime) -> list[time]:
    """Whole hours the shop can deliver in on `day`.

    Inclusive of the closing hour: a shop open 09:00-19:00 can deliver at 19:00.
    An opening time with minutes rounds UP to the next whole hour, because the
    picker only ever offers whole hours and offering one the shop is not open
    for would be a promise it cannot keep.
    """
    hours = opening_hours(policy, day)
    if hours is None:
        return []
    open_at, close_at = hours

    first = open_at.hour + (1 if open_at.minute else 0)
    candidates = [time(h) for h in range(first, close_at.hour + 1)]

    if day != now_local.date():
        return candidates

    # Today only: everything sooner than the lead time is not orderable.
    earliest = now_local + timedelta(minutes=policy.min_lead_minutes)
    return [h for h in candidates if datetime.combine(day, h, tzinfo=now_local.tzinfo) >= earliest]


def available_dates(
    policy: SlotPolicy,
    now_local: datetime,
    *,
    full_dates: frozenset[date] = frozenset(),
) -> list[date]:
    """Dates the picker should offer, soonest first.

    A date is dropped when the shop is closed that day, when it is already at
    `daily_order_cap`, or -- for today -- when the cutoff has passed or the lead
    time leaves no hour standing. That last check is why this calls
    `available_hours`: a date with no pickable hour must not be offered at all.
    """
    today = now_local.date()
    offered: list[date] = []
    for offset in range(policy.horizon_days):
        day = today + timedelta(days=offset)
        if day in full_dates:
            continue
        if opening_hours(policy, day) is None:
            continue
        if day == today:
            if now_local.time() > policy.same_day_cutoff:
                continue
            if not available_hours(policy, day, now_local):
                continue
        offered.append(day)
    return offered
