"""What a platform admin can DO (CP18), each one audited.

Every action:
  * locks the row, reads its state BEFORE, changes it, and writes one audit
    entry with before -> after, the admin, the reason and the address -- in
    the SAME transaction, so an action and its record commit or roll back
    together;
  * is audited even when it changes nothing (pausing a paused shop), so the
    log shows the attempt;
  * returns the "after" state for the screen to show.

The pause itself is ENFORCED elsewhere -- the reminder tick, the shop's bot and
its public pages read `shops.status` (tests/test_shop_pause.py). This module
only records the decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.models.billing import PAYMENT_METHODS, SubscriptionPayment
from gulbot.models.notification import ScheduledNotification
from gulbot.models.shop import Shop, ShopStatus
from gulbot.scheduling.occurrences import DEFAULT_GRACE
from gulbot.services.admin_auth import Admin, audit

#: What a pause, a payment note or a hide may say, at most.
REASON_MAX = 300


class ActionRefused(Exception):
    """`reason`: "shop" (no such shop), "status", "payment"."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def clean_reason(raw: str | None) -> str | None:
    cleaned = " ".join((raw or "").split())[:REASON_MAX]
    return cleaned or None


async def shop_state(session: AsyncSession, shop_id: int) -> dict[str, Any]:
    """The audited fields of a shop, locked for this transaction."""
    row = (
        await session.execute(
            select(Shop.status, Shop.subscription_status, Shop.paid_until)
            .where(Shop.id == shop_id)
            .with_for_update()
        )
    ).one_or_none()
    if row is None:
        raise ActionRefused("shop")
    return {
        "status": row.status,
        "subscription_status": row.subscription_status,
        "paid_until": row.paid_until.isoformat() if row.paid_until else None,
    }


async def reminders_expiring_on_resume(
    session: AsyncSession, *, shop_id: int, now: datetime
) -> int:
    """The shop's waiting reminders already past the staleness bound: on resume
    the tick EXPIRES these at send time instead of sending them."""
    return int(
        await session.scalar(
            select(func.count())
            .select_from(ScheduledNotification)
            .where(
                ScheduledNotification.shop_id == shop_id,
                ScheduledNotification.state.in_(("pending", "failed")),
                ScheduledNotification.due_at_utc < now - DEFAULT_GRACE,
            )
        )
        or 0
    )


async def set_shop_status(
    session: AsyncSession,
    *,
    admin: Admin,
    shop_id: int,
    status: str,
    reason: str | None,
    ip: str | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if status not in tuple(ShopStatus):
        raise ActionRefused("status")
    now = now or datetime.now(UTC)
    before = await shop_state(session, shop_id)
    after: dict[str, Any] = dict(before, status=status)
    if before["status"] != status:
        await session.execute(
            update(Shop).where(Shop.id == shop_id).values(status=status, status_changed_at=now)
        )
    if status == ShopStatus.ACTIVE.value and before["status"] == ShopStatus.PAUSED.value:
        after["reminders_expiring_on_resume"] = await reminders_expiring_on_resume(
            session, shop_id=shop_id, now=now
        )
    action = {"paused": "shop_pause", "active": "shop_resume"}.get(status, "shop_status")
    await audit(
        session,
        action=action,
        admin=admin.telegram_id,
        shop_id=shop_id,
        target_type="shop",
        target_id=shop_id,
        before=before,
        after=after,
        reason=clean_reason(reason),
        ip=ip,
    )
    return after


@dataclass(frozen=True)
class Payment:
    paid_until: date
    amount_uzs: int
    method: str
    note: str | None = None


async def mark_paid(
    session: AsyncSession,
    *,
    admin: Admin,
    shop_id: int,
    payment: Payment,
    ip: str | None,
) -> dict[str, Any]:
    """Record a payment in the ledger and set the shop paid until a date."""
    if payment.amount_uzs <= 0 or payment.method not in PAYMENT_METHODS:
        raise ActionRefused("payment")
    before = await shop_state(session, shop_id)
    await session.execute(
        insert(SubscriptionPayment).values(
            shop_id=shop_id,
            amount_uzs=payment.amount_uzs,
            method=payment.method,
            note=clean_reason(payment.note),
            paid_until=payment.paid_until,
            admin_telegram_id=admin.telegram_id,
        )
    )
    await session.execute(
        update(Shop)
        .where(Shop.id == shop_id)
        .values(subscription_status="paid", paid_until=payment.paid_until)
    )
    after = dict(
        before,
        subscription_status="paid",
        paid_until=payment.paid_until.isoformat(),
        amount_uzs=payment.amount_uzs,
        method=payment.method,
    )
    await audit(
        session,
        action="subscription_paid",
        admin=admin.telegram_id,
        shop_id=shop_id,
        target_type="shop",
        target_id=shop_id,
        before=before,
        after=after,
        reason=clean_reason(payment.note),
        ip=ip,
    )
    return after
