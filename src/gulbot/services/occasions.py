"""Occasion creation, listing and deactivation."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.models.consent import (
    STORE_DATES_TEXT_VERSION,
    ConsentEvent,
    ConsentSource,
    ConsentType,
)
from gulbot.models.occasion import MAX_DAY_IN_MONTH, Occasion


def is_valid_month_day(month: int, day: int) -> bool:
    """Validate the PAIR, not the fields in isolation.

    Feb 30 and Apr 31 have valid months and valid days; only the combination is
    wrong. February allows 29: whether that year had one is a separate check.
    """
    if not 1 <= month <= 12:
        return False
    return 1 <= day <= MAX_DAY_IN_MONTH[month - 1]


def is_leap_year(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def is_valid_year(year: int, month: int, day: int) -> bool:
    if not 1900 <= year <= 2100:
        return False
    if month == 2 and day == 29:
        return is_leap_year(year)
    return True


async def list_active_occasions(
    session: AsyncSession, *, shop_id: int, customer_id: int
) -> Sequence[Occasion]:
    result = await session.scalars(
        select(Occasion)
        .where(
            Occasion.shop_id == shop_id,
            Occasion.customer_id == customer_id,
            Occasion.active.is_(True),
        )
        .order_by(Occasion.month, Occasion.day)
    )
    return list(result)


async def create_occasion(
    session: AsyncSession,
    *,
    shop_id: int,
    customer_id: int,
    recipient_id: int,
    type_: str,
    label: str,
    month: int,
    day: int,
    year: int | None,
) -> Occasion | None:
    """Insert an occasion. Returns None if the recipient already has that date.

    ON CONFLICT DO NOTHING rather than a prior SELECT: a double-tapped confirm
    button arrives as two updates, and check-then-act loses that race.

    `label` and `type` are written only to keep the deprecated columns in step
    with the recipient; nothing reads them.
    """
    stmt = (
        insert(Occasion)
        .values(
            shop_id=shop_id,
            customer_id=customer_id,
            recipient_id=recipient_id,
            type=type_,
            label=label,
            month=month,
            day=day,
            year=year,
        )
        .on_conflict_do_nothing(index_elements=["recipient_id", "month", "day"])
        .returning(Occasion.id)
    )
    new_id = await session.scalar(stmt)
    if new_id is None:
        return None
    return await session.get(Occasion, new_id)


async def deactivate_occasion(
    session: AsyncSession, *, shop_id: int, customer_id: int, occasion_id: int
) -> str | None:
    """Soft-delete. Returns the label, or None if it was not theirs.

    Scoped by shop_id AND customer_id so a guessed id cannot touch another
    customer's row.
    """
    result = await session.execute(
        update(Occasion)
        .where(
            Occasion.id == occasion_id,
            Occasion.shop_id == shop_id,
            Occasion.customer_id == customer_id,
            Occasion.active.is_(True),
        )
        .values(active=False)
        .returning(Occasion.label)
    )
    row = result.first()
    return row[0] if row else None


async def record_store_dates_consent(
    session: AsyncSession, *, shop_id: int, customer_id: int
) -> bool:
    """Append a consent row on first occasion creation. Returns True if written.

    Append-only: this never updates an existing row. Withdrawal would be a new
    row with granted=false.
    """
    already = await session.scalar(
        select(ConsentEvent.id).where(
            ConsentEvent.customer_id == customer_id,
            ConsentEvent.type == ConsentType.STORE_DATES.value,
        )
    )
    if already is not None:
        return False
    session.add(
        ConsentEvent(
            shop_id=shop_id,
            customer_id=customer_id,
            type=ConsentType.STORE_DATES.value,
            granted=True,
            source=ConsentSource.FIRST_OCCASION.value,
            text_version=STORE_DATES_TEXT_VERSION,
        )
    )
    await session.flush()
    return True


async def update_occasion_date(
    session: AsyncSession,
    *,
    shop_id: int,
    customer_id: int,
    occasion_id: int,
    month: int,
    day: int,
    year: int | None,
) -> bool:
    """Move an existing occasion to a new date. False if it was not theirs."""
    result = await session.execute(
        update(Occasion)
        .where(
            Occasion.id == occasion_id,
            Occasion.shop_id == shop_id,
            Occasion.customer_id == customer_id,
            Occasion.active.is_(True),
        )
        .values(month=month, day=day, year=year)
        .returning(Occasion.id)
    )
    return result.first() is not None


async def get_occasion(
    session: AsyncSession, *, shop_id: int, customer_id: int, occasion_id: int
) -> Occasion | None:
    occasion: Occasion | None = await session.scalar(
        select(Occasion).where(
            Occasion.id == occasion_id,
            Occasion.shop_id == shop_id,
            Occasion.customer_id == customer_id,
            Occasion.active.is_(True),
        )
    )
    return occasion
