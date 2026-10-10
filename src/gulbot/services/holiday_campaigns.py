"""Holiday campaigns (CP20): which holidays a shop runs, who wants to hear about
them, and the specs the materializer plans with.

THREE CONDITIONS, ALL REQUIRED, for a customer to get a holiday reminder:
  1. the SHOP runs that holiday (`shop_holidays`, chosen by its owner in /shop);
  2. the CUSTOMER opted in: their latest `consent_events` row of type
     holiday_greetings says granted. No row = never asked = OFF;
  3. for a lunar holiday, the platform admin entered that year's date.

Everything else -- the send window, the merge window, the weekly cap, the
bouquet suggestion, the outbox and its exactly-once send -- is the personal
reminders' own machinery: a holiday enters the planner as one more date
(gulbot.holidays), so none of those rules has a second copy.

STOPPING IS IMMEDIATE. Opting out, or a shop switching a holiday off, deletes
the pending holiday rows it covers in the same transaction, so nothing already
planned goes out afterwards -- the materializer's own reconciliation would
otherwise only catch it at night.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

from sqlalchemy import delete, insert, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.holidays import BY_KEY, HOLIDAYS, Holiday
from gulbot.models.consent import (
    HOLIDAY_GREETINGS_TEXT_VERSION,
    ConsentEvent,
    ConsentSource,
    ConsentType,
)
from gulbot.models.holiday import HolidayDate, ShopHoliday
from gulbot.models.notification import RECONCILABLE_STATES, ScheduledNotification
from gulbot.scheduling.occurrences import OccasionSpec


class UnknownHoliday(ValueError):
    pass


def _known(holiday: str) -> Holiday:
    found = BY_KEY.get(holiday)
    if found is None:
        raise UnknownHoliday(holiday)
    return found


# --- the customer's consent ---------------------------------------------------

_LATEST_CONSENT = """
    SELECT DISTINCT ON (customer_id) customer_id, granted
      FROM consent_events
     WHERE shop_id = :shop AND type = 'holiday_greetings'
     ORDER BY customer_id, at DESC, id DESC
"""


async def opted_in(session: AsyncSession, *, shop_id: int, customer_id: int) -> bool:
    granted = await session.scalar(
        select(ConsentEvent.granted)
        .where(
            ConsentEvent.shop_id == shop_id,
            ConsentEvent.customer_id == customer_id,
            ConsentEvent.type == ConsentType.HOLIDAY_GREETINGS.value,
        )
        .order_by(ConsentEvent.at.desc(), ConsentEvent.id.desc())
        .limit(1)
    )
    return bool(granted)


async def opted_in_customers(session: AsyncSession, *, shop_id: int) -> set[int]:
    rows = await session.execute(text(_LATEST_CONSENT), {"shop": shop_id})
    return {int(row.customer_id) for row in rows if row.granted}


async def set_opt_in(
    session: AsyncSession, *, shop_id: int, customer_id: int, granted: bool
) -> int:
    """Record the customer's answer -- a NEW row, the ledger is append-only.
    On a no, drop their pending holiday reminders now. Returns rows dropped."""
    await session.execute(
        insert(ConsentEvent).values(
            shop_id=shop_id,
            customer_id=customer_id,
            type=ConsentType.HOLIDAY_GREETINGS.value,
            granted=granted,
            source=ConsentSource.SETTINGS.value,
            text_version=HOLIDAY_GREETINGS_TEXT_VERSION,
        )
    )
    if granted:
        return 0
    return await _drop_pending(
        session,
        ScheduledNotification.shop_id == shop_id,
        ScheduledNotification.customer_id == customer_id,
    )


# --- the shop's choice --------------------------------------------------------


async def enabled_holidays(session: AsyncSession, *, shop_id: int) -> set[str]:
    rows = await session.scalars(select(ShopHoliday.holiday).where(ShopHoliday.shop_id == shop_id))
    return set(rows)


async def set_shop_holiday(
    session: AsyncSession, *, shop_id: int, holiday: str, on: bool, owner_id: int
) -> bool:
    """Switch one holiday on or off for one shop. True when that changed
    anything. Off drops the shop's pending reminders for it at once."""
    _known(holiday)
    if on:
        added = await session.execute(
            pg_insert(ShopHoliday)
            .values(shop_id=shop_id, holiday=holiday, enabled_by=owner_id)
            .on_conflict_do_nothing()
            .returning(ShopHoliday.holiday)
        )
        return added.first() is not None
    removed = await session.execute(
        delete(ShopHoliday)
        .where(ShopHoliday.shop_id == shop_id, ShopHoliday.holiday == holiday)
        .returning(ShopHoliday.holiday)
    )
    if removed.first() is None:
        return False
    await _drop_pending(
        session,
        ScheduledNotification.shop_id == shop_id,
        ScheduledNotification.holiday == holiday,
    )
    return True


async def _drop_pending(session: AsyncSession, *conditions: object) -> int:
    dropped = await session.execute(
        delete(ScheduledNotification)
        .where(
            ScheduledNotification.holiday.is_not(None),
            ScheduledNotification.state.in_(RECONCILABLE_STATES),
            *conditions,  # type: ignore[arg-type]
        )
        .returning(ScheduledNotification.id)
    )
    return len(list(dropped))


# --- the lunar calendar -------------------------------------------------------


async def lunar_dates(session: AsyncSession) -> dict[str, tuple[date, ...]]:
    found: dict[str, list[date]] = {}
    for row in await session.execute(
        select(HolidayDate.holiday, HolidayDate.falls_on).order_by(HolidayDate.falls_on)
    ):
        found.setdefault(str(row.holiday), []).append(row.falls_on)
    return {key: tuple(dates) for key, dates in found.items()}


async def set_lunar_date(
    session: AsyncSession, *, holiday: str, falls_on: date, admin: int
) -> date | None:
    """Enter (or correct) a lunar holiday's date for its year. Returns the
    date it replaced, if any. A non-lunar holiday is refused."""
    if _known(holiday).month is not None:
        raise UnknownHoliday(f"{holiday} has a fixed date")
    previous = await session.scalar(
        select(HolidayDate.falls_on).where(
            HolidayDate.holiday == holiday, HolidayDate.year == falls_on.year
        )
    )
    await session.execute(
        pg_insert(HolidayDate)
        .values(holiday=holiday, year=falls_on.year, falls_on=falls_on, set_by=admin)
        .on_conflict_do_update(
            index_elements=[HolidayDate.holiday, HolidayDate.year],
            set_={"falls_on": falls_on, "set_by": admin},
        )
    )
    if previous is not None and previous != falls_on:
        # Pending reminders planned around the old date are wrong now; the
        # next materialize plans the new one.
        await _drop_pending(
            session,
            ScheduledNotification.holiday == holiday,
            ScheduledNotification.occurrence_year == falls_on.year,
        )
    return previous


# --- what the planner sees ----------------------------------------------------


def holiday_specs(enabled: Iterable[str], lunar: dict[str, tuple[date, ...]]) -> list[OccasionSpec]:
    """One planner entry per holiday this shop runs. A lunar holiday with no
    entered dates is left out, rather than guessed."""
    specs: list[OccasionSpec] = []
    chosen = set(enabled)
    for holiday in HOLIDAYS:
        if holiday.key not in chosen:
            continue
        if holiday.month is not None and holiday.day is not None:
            specs.append(
                OccasionSpec(occasion_id=holiday.spec_id, month=holiday.month, day=holiday.day)
            )
        elif lunar.get(holiday.key):
            specs.append(
                OccasionSpec(occasion_id=holiday.spec_id, month=1, day=1, dates=lunar[holiday.key])
            )
    return specs
