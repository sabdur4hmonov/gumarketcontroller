"""Recipients: the people a customer buys flowers for."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.models.occasion import Occasion
from gulbot.models.recipient import Recipient
from gulbot.services.occasions import discard_pending_reminders


async def create_recipient(
    session: AsyncSession,
    *,
    shop_id: int,
    customer_id: int,
    label: str,
    type_: str,
) -> Recipient:
    """Always inserts. Two recipients may deliberately share a label."""
    recipient = Recipient(shop_id=shop_id, customer_id=customer_id, label=label, type=type_)
    session.add(recipient)
    await session.flush()
    return recipient


async def get_recipient(
    session: AsyncSession, *, shop_id: int, customer_id: int, recipient_id: int
) -> Recipient | None:
    """Scoped by shop AND customer, so a guessed id reaches nothing."""
    recipient: Recipient | None = await session.scalar(
        select(Recipient).where(
            Recipient.id == recipient_id,
            Recipient.shop_id == shop_id,
            Recipient.customer_id == customer_id,
            Recipient.active.is_(True),
        )
    )
    return recipient


async def list_recipients(
    session: AsyncSession, *, shop_id: int, customer_id: int
) -> Sequence[Recipient]:
    result = await session.scalars(
        select(Recipient)
        .where(
            Recipient.shop_id == shop_id,
            Recipient.customer_id == customer_id,
            Recipient.active.is_(True),
        )
        .order_by(Recipient.created_at, Recipient.id)
    )
    return list(result)


async def list_recipient_occasions(
    session: AsyncSession, *, recipient_id: int
) -> Sequence[Occasion]:
    result = await session.scalars(
        select(Occasion)
        .where(Occasion.recipient_id == recipient_id, Occasion.active.is_(True))
        .order_by(Occasion.month, Occasion.day)
    )
    return list(result)


async def rename_recipient(
    session: AsyncSession,
    *,
    shop_id: int,
    customer_id: int,
    recipient_id: int,
    label: str,
    type_: str,
) -> str | None:
    """Rename, returning the new label, or None if it was not theirs.

    `occasions.label` is kept in step because it is still written for the
    deprecated column; nothing reads it, but leaving it stale would make the
    eventual drop migration harder to reason about.
    """
    result = await session.execute(
        update(Recipient)
        .where(
            Recipient.id == recipient_id,
            Recipient.shop_id == shop_id,
            Recipient.customer_id == customer_id,
            Recipient.active.is_(True),
        )
        .values(label=label, type=type_)
        .returning(Recipient.label)
    )
    row = result.first()
    if row is None:
        return None
    await session.execute(
        update(Occasion)
        .where(Occasion.recipient_id == recipient_id)
        .values(label=label, type=type_)
    )
    return str(row[0])


async def deactivate_recipient(
    session: AsyncSession, *, shop_id: int, customer_id: int, recipient_id: int
) -> str | None:
    """Soft-delete the person AND their dates. Returns the label."""
    result = await session.execute(
        update(Recipient)
        .where(
            Recipient.id == recipient_id,
            Recipient.shop_id == shop_id,
            Recipient.customer_id == customer_id,
            Recipient.active.is_(True),
        )
        .values(active=False)
        .returning(Recipient.label)
    )
    row = result.first()
    if row is None:
        return None
    deactivated = await session.scalars(
        update(Occasion)
        .where(Occasion.recipient_id == recipient_id)
        .values(active=False)
        .returning(Occasion.id)
    )
    # And what was already scheduled for them, now rather than at the nightly
    # prune. See `discard_pending_reminders`.
    await discard_pending_reminders(session, occasion_ids=list(deactivated))
    return str(row[0])


async def count_active_recipients(session: AsyncSession, *, shop_id: int, customer_id: int) -> int:
    rows = await session.scalars(
        select(Recipient.id).where(
            Recipient.shop_id == shop_id,
            Recipient.customer_id == customer_id,
            Recipient.active.is_(True),
        )
    )
    return len(list(rows))


__all__ = [
    "count_active_recipients",
    "create_recipient",
    "deactivate_recipient",
    "get_recipient",
    "list_recipient_occasions",
    "list_recipients",
    "rename_recipient",
]
