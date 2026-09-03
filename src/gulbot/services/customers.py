"""Customer registration and language."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.i18n.catalog import DEFAULT_LANGUAGE
from gulbot.models.customer import Customer


async def get_or_create_customer(
    session: AsyncSession, *, shop_id: int, telegram_user_id: int
) -> tuple[Customer, bool]:
    """Return (customer, created).

    Uses ON CONFLICT DO NOTHING rather than SELECT-then-INSERT: two rapid /start
    taps arrive as two concurrent updates, and the check-then-act version loses
    that race. UNIQUE(shop_id, telegram_user_id) is what makes this safe.
    """
    stmt = (
        insert(Customer)
        .values(
            shop_id=shop_id,
            telegram_user_id=telegram_user_id,
            lang=DEFAULT_LANGUAGE,
        )
        .on_conflict_do_nothing(index_elements=["shop_id", "telegram_user_id"])
        .returning(Customer.id)
    )
    inserted_id = await session.scalar(stmt)

    customer = await session.scalar(
        select(Customer).where(
            Customer.shop_id == shop_id,
            Customer.telegram_user_id == telegram_user_id,
        )
    )
    assert customer is not None  # the row exists: we just inserted or it was there
    return customer, inserted_id is not None


async def set_language(session: AsyncSession, *, customer: Customer, lang: str) -> None:
    customer.lang = lang
    await session.flush()
