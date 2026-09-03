"""Storing reminder and flower preferences.

CP3.6 only STORES these. Nothing reads them until CP5 wires
(offsets, send_time) into the materializer -- see docs/CHECKPOINTS.md.
"""

from __future__ import annotations

from datetime import time

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.models.customer import SEND_TIME_CHOICES, Customer
from gulbot.models.recipient import FLOWER_PRESETS, Recipient


async def set_preferred_hashtag(
    session: AsyncSession,
    *,
    shop_id: int,
    customer_id: int,
    recipient_id: int,
    hashtag: str | None,
) -> bool:
    """Store a flower preset, or NULL for "Boshqa". False if not theirs."""
    if hashtag is not None and hashtag not in FLOWER_PRESETS:
        raise ValueError(f"unknown flower preset: {hashtag!r}")
    result = await session.execute(
        update(Recipient)
        .where(
            Recipient.id == recipient_id,
            Recipient.shop_id == shop_id,
            Recipient.customer_id == customer_id,
            Recipient.active.is_(True),
        )
        .values(preferred_hashtag=hashtag)
        .returning(Recipient.id)
    )
    return result.first() is not None


async def set_reminder_count(session: AsyncSession, *, customer: Customer, count: int) -> None:
    if count not in (1, 2, 3):
        raise ValueError(f"reminder_count must be 1, 2 or 3, got {count!r}")
    customer.reminder_count = count
    await session.flush()


async def set_send_time(session: AsyncSession, *, customer: Customer, slot: str) -> time:
    """Store a named slot as a real time. Raises on an unknown slot."""
    if slot not in SEND_TIME_CHOICES:
        raise ValueError(f"unknown send time slot: {slot!r}")
    chosen = SEND_TIME_CHOICES[slot]
    customer.preferred_send_time = chosen
    await session.flush()
    return chosen


async def has_answered_reminder_preferences(session: AsyncSession, *, customer_id: int) -> bool:
    """True once either question has been answered.

    Used to ask the pair ONCE. A customer who skipped both is asked again on a
    later visit, which is the friendlier reading of "skippable".
    """
    row = await session.execute(
        select(Customer.reminder_count, Customer.preferred_send_time).where(
            Customer.id == customer_id
        )
    )
    count, send_time = row.one()
    return count is not None or send_time is not None
