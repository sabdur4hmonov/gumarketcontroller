"""The occurrence engine: when a reminder is due, and what it covers.

PURE. No database, no Telegram, no clock, no environment. `now` is always passed
in. Everything here is a deterministic function of its arguments, which is what
makes the year-boundary and clustering rules testable at all.

Three ideas carry the whole module:

**occurrence_year is the year of the OCCASION, never the year of the send.**
A 3 January birthday with a -7 offset is due on 27 December of the PREVIOUS
calendar year, and that row's occurrence_year is still the January one. The
uniqueness of scheduled_notifications rests on this: key on the send year and
the December row and the January row land in different years, so the nightly
materialiser happily creates both again forever.

**One row per occasion, one message per merge group.** Merging must not weaken
the unique key, so merged occasions still each get their own row. They share a
`merge_key`, and the sender emits ONE message for the group. Dropping rows for
the merged-away occasions would leave nothing to conflict against, and the
materialiser would recreate them on the next pass.

**Clamping happens here, not at send time.** A materialised due_at is already
inside the send window, so the sender's window check is a backstop assertion
rather than logic that can drift.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

# Uzbekistan is UTC+5 with no DST, but it is resolved through the IANA database
# rather than hardcoded: a fixed offset is an assumption that rots silently.
TASHKENT = ZoneInfo("Asia/Tashkent")

CHANNEL_TELEGRAM = "telegram"

DEFAULT_OFFSETS: tuple[int, ...] = (-7, -1, 0)
DEFAULT_HORIZON_DAYS = 45
DEFAULT_MERGE_WINDOW_DAYS = 2
DEFAULT_WEEKLY_CAP = 4
CAP_WINDOW = timedelta(days=7)
DEFAULT_GRACE = timedelta(hours=6)

# Reminders are only ever sent inside this local window. It governs OUTBOUND
# REMINDERS ONLY -- it has nothing to do with shop working hours, and must never
# be used to filter delivery slots.
WINDOW_START = time(10, 0)
WINDOW_END = time(20, 0)
DEFAULT_SEND_TIME = time(10, 0)


def is_leap_year(year: int) -> bool:
    """Gregorian rule: divisible by 4, except centuries, unless divisible by 400.

    1900 and 2100 are NOT leap years; 2000 and 2024 are.
    """
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def occurrence_date_for(month: int, day: int, year: int) -> date:
    """The calendar date an occasion falls on in `year`.

    A 29 February occasion fires on 28 February in a common year. It is not
    skipped, and it does not slide into March.
    """
    if month == 2 and day == 29 and not is_leap_year(year):
        return date(year, 2, 28)
    return date(year, month, day)


def clamp_to_window(
    day: date,
    *,
    preferred: time = DEFAULT_SEND_TIME,
    tz: ZoneInfo = TASHKENT,
    window_start: time = WINDOW_START,
    window_end: time = WINDOW_END,
) -> datetime:
    """Local send moment for `day`, pulled inside the allowed window."""
    chosen = min(max(preferred, window_start), window_end)
    return datetime.combine(day, chosen, tzinfo=tz)


def is_within_send_window(
    moment_utc: datetime,
    *,
    tz: ZoneInfo = TASHKENT,
    window_start: time = WINDOW_START,
    window_end: time = WINDOW_END,
) -> bool:
    """Backstop for the sender. Materialised rows should always satisfy this."""
    local = moment_utc.astimezone(tz).timetz().replace(tzinfo=None)
    return window_start <= local <= window_end


@dataclass(frozen=True)
class OccasionSpec:
    """The scheduling-relevant part of an occasion. Deliberately not the model."""

    occasion_id: int
    month: int
    day: int
    label: str = ""
    year: int | None = None


@dataclass(frozen=True)
class PlannedNotification:
    occasion_id: int
    occurrence_year: int
    occurrence_date: date
    offset_days: int
    channel: str
    due_at_utc: datetime
    merge_key: str
    merged_occasion_ids: tuple[int, ...]

    @property
    def unique_key(self) -> tuple[int, int, int, str]:
        """Exactly the scheduled_notifications unique constraint."""
        return (self.occasion_id, self.occurrence_year, self.offset_days, self.channel)

    @property
    def is_merged(self) -> bool:
        return len(self.merged_occasion_ids) > 1


@dataclass(frozen=True)
class _Occurrence:
    spec: OccasionSpec
    occurrence_year: int
    occurrence_date: date


def _candidate_years(start: date, end: date) -> tuple[int, ...]:
    """Years whose occurrences could produce a due date in [start, end].

    Includes the year before `start` and the year after `end` because negative
    offsets pull a due date backwards across 1 January, and because a December
    occurrence can be reached from a January window.
    """
    return tuple(range(start.year - 1, end.year + 2))


def _occurrences(occasions: Iterable[OccasionSpec], start: date, end: date) -> list[_Occurrence]:
    found = [
        _Occurrence(spec, year, occurrence_date_for(spec.month, spec.day, year))
        for spec in occasions
        for year in _candidate_years(start, end)
    ]
    # Canonical order. Sorting by (date, occasion_id) is what makes clustering
    # independent of the order the caller supplied the occasions in.
    found.sort(key=lambda o: (o.occurrence_date, o.spec.occasion_id, o.occurrence_year))
    return found


def cluster_occurrences(
    occurrences: Sequence[_Occurrence], *, merge_window_days: int = DEFAULT_MERGE_WINDOW_DAYS
) -> list[list[_Occurrence]]:
    """Group occurrences that fall within `merge_window_days` of EACH OTHER.

    Adjacency chains: 1, 3 and 5 March all land in one cluster with a 2-day
    window, because each is within two days of its neighbour, even though the
    first and last are four days apart. That is the literal reading of "within
    two days of each other", and it is order-independent because the input is
    sorted canonically first.

    A consequence worth knowing: a dense run of dates produces one long cluster
    and therefore one long message. The 4-per-7-days cap is what stops that
    turning into a flood.
    """
    clusters: list[list[_Occurrence]] = []
    for occurrence in occurrences:
        if clusters and (
            occurrence.occurrence_date - clusters[-1][-1].occurrence_date
        ) <= timedelta(days=merge_window_days):
            clusters[-1].append(occurrence)
        else:
            clusters.append([occurrence])
    return clusters


def _merge_key(anchor: date, offset_days: int, occasion_ids: tuple[int, ...]) -> str:
    joined = "-".join(str(i) for i in occasion_ids)
    return f"{anchor.isoformat()}:{offset_days:+d}:{joined}"


def _apply_weekly_cap(
    planned: Sequence[PlannedNotification],
    *,
    weekly_cap: int,
    cap_window: timedelta = CAP_WINDOW,
) -> list[PlannedNotification]:
    """Keep at most `weekly_cap` MESSAGES in any rolling window.

    The cap counts messages, not rows: a merged reminder covering three dates is
    one message and costs one slot.

    Messages are considered in order of URGENCY, not chronology: the day-of
    reminder first, then -1, then -7. Dropping purely by "whichever comes first"
    lets an early -7 consume the budget and starve the day-of reminder for a
    later occasion -- telling a customer "tomorrow is your father's birthday"
    and then saying nothing on the day, which is worse than not reminding at all.
    Ties are broken by due time and then merge_key, so the result is
    deterministic and independent of input order.

    Because urgency order is not chronological, the rolling-window invariant is
    checked in BOTH directions: a candidate is accepted only if, with it added,
    no message's preceding window holds more than `weekly_cap`.
    """
    by_message: dict[str, list[PlannedNotification]] = {}
    for item in planned:
        by_message.setdefault(item.merge_key, []).append(item)

    def urgency(rows: list[PlannedNotification]) -> tuple[int, datetime, str]:
        row = rows[0]
        return (abs(row.offset_days), row.due_at_utc, row.merge_key)

    candidates = sorted(by_message.items(), key=lambda kv: urgency(kv[1]))

    kept_due: list[datetime] = []
    kept_keys: list[str] = []
    for key, rows in candidates:
        due = rows[0].due_at_utc
        if _window_would_overflow(kept_due, due, cap=weekly_cap, window=cap_window):
            continue
        kept_due.append(due)
        kept_keys.append(key)

    return [row for key in kept_keys for row in by_message[key]]


def _window_would_overflow(
    kept_due: Sequence[datetime], candidate: datetime, *, cap: int, window: timedelta
) -> bool:
    """True if adding `candidate` puts more than `cap` messages in any window."""
    moments = sorted([*kept_due, candidate])
    return any(
        sum(1 for other in moments if moment - window < other <= moment) > cap for moment in moments
    )


def plan_notifications(
    occasions: Sequence[OccasionSpec],
    *,
    now_utc: datetime,
    offsets: Sequence[int] = DEFAULT_OFFSETS,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    tz: ZoneInfo = TASHKENT,
    send_time: time = DEFAULT_SEND_TIME,
    merge_window_days: int = DEFAULT_MERGE_WINDOW_DAYS,
    weekly_cap: int = DEFAULT_WEEKLY_CAP,
    channel: str = CHANNEL_TELEGRAM,
) -> list[PlannedNotification]:
    """Everything due for ONE customer within the horizon.

    Called per customer: the weekly cap is per customer, and so is clustering.

    Returns one row per (occasion, occurrence_year, offset). Rows that belong to
    the same message share a `merge_key`; the sender emits one message per key.
    Every returned row satisfies `is_within_send_window(due_at_utc)`.
    """
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")

    now_local = now_utc.astimezone(tz)
    horizon_end = now_local.date() + timedelta(days=horizon_days)

    occurrences = _occurrences(occasions, now_local.date(), horizon_end)
    clusters = cluster_occurrences(occurrences, merge_window_days=merge_window_days)

    planned: list[PlannedNotification] = []
    for cluster in clusters:
        # The anchor is the cluster's earliest date, so a merged reminder never
        # arrives after the first date it is meant to warn about.
        anchor = min(o.occurrence_date for o in cluster)
        ids = tuple(sorted({o.spec.occasion_id for o in cluster}))

        for offset in sorted(set(offsets)):
            due_local = clamp_to_window(anchor + timedelta(days=offset), preferred=send_time, tz=tz)
            due_utc = due_local.astimezone(UTC)
            if due_utc < now_utc or due_local.date() > horizon_end:
                continue

            key = _merge_key(anchor, offset, ids)
            planned.extend(
                PlannedNotification(
                    occasion_id=o.spec.occasion_id,
                    occurrence_year=o.occurrence_year,
                    occurrence_date=o.occurrence_date,
                    offset_days=offset,
                    channel=channel,
                    due_at_utc=due_utc,
                    merge_key=key,
                    merged_occasion_ids=ids,
                )
                for o in cluster
            )

    kept = _apply_weekly_cap(planned, weekly_cap=weekly_cap)
    kept.sort(key=lambda p: (p.due_at_utc, p.occasion_id, p.offset_days))
    return kept


def is_expired(
    planned: PlannedNotification,
    *,
    now_utc: datetime,
    grace: timedelta = DEFAULT_GRACE,
    tz: ZoneInfo = TASHKENT,
) -> bool:
    """Two independent conditions; either one expires the row.

    1. More than `grace` past due. A worker outage must not blast a backlog.
    2. The occurrence date has already passed, regardless of grace. "Your wife's
       birthday is today" arriving the day after is worse than silence, so this
       guard has no grace period at all.
    """
    if now_utc > planned.due_at_utc + grace:
        return True
    today_local = now_utc.astimezone(tz).date()
    return today_local > planned.occurrence_date
