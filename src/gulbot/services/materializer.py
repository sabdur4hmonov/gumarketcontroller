"""The nightly materializer: write the next ~45 days of the outbox.

It does three things and no more:

1. RESOLVE each customer's offsets and send time through the fallback chain.
2. PLAN with the pure engine (CP4) and INSERT with ON CONFLICT DO NOTHING, so
   running it twice is indistinguishable from running it once.
3. RECONCILE: delete PENDING rows that no longer belong -- offsets the customer
   has since dropped, and occasions or recipients that have been deactivated.

It sends nothing. No Telegram, no beat tick, no message_log: that is CP6.

RECONCILIATION ONLY EVER TOUCHES state='pending'. A sent or expired row is
HISTORY, not a schedule. Deleting one would make the bot forget it had already
reminded someone, and the next run would remind them again -- exactly the
duplicate the unique constraint exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.models.customer import Customer
from gulbot.models.notification import (
    RECONCILABLE_STATES,
    NotificationChannel,
    ScheduledNotification,
)
from gulbot.models.occasion import Occasion
from gulbot.models.recipient import Recipient
from gulbot.models.shop import Shop
from gulbot.scheduling.occurrences import (
    DEFAULT_HORIZON_DAYS,
    OccasionSpec,
    PlannedNotification,
    plan_notifications,
)
from gulbot.services.reminder_settings import resolve_reminder_settings

#: Rows per INSERT. Large enough that 10k occasions is a handful of round
#: trips, small enough that one statement stays well inside parameter limits.
INSERT_BATCH_SIZE = 500


@dataclass(frozen=True)
class MaterializeResult:
    customers: int
    occasions: int
    planned: int
    inserted: int
    pruned_offsets: int
    pruned_inactive: int

    @property
    def pruned(self) -> int:
        return self.pruned_offsets + self.pruned_inactive


async def _active_occasions_by_customer(
    session: AsyncSession, *, shop_id: int
) -> dict[int, list[Occasion]]:
    """Active occasions belonging to active recipients, grouped by customer.

    A deactivated recipient takes their dates out of scheduling even when the
    occasion rows themselves are still marked active.
    """
    rows = await session.scalars(
        select(Occasion)
        .join(Recipient, Recipient.id == Occasion.recipient_id)
        .where(
            Occasion.shop_id == shop_id,
            Occasion.active.is_(True),
            Recipient.active.is_(True),
        )
        .order_by(Occasion.customer_id, Occasion.id)
    )
    grouped: dict[int, list[Occasion]] = {}
    for occasion in rows:
        grouped.setdefault(occasion.customer_id, []).append(occasion)
    return grouped


async def _insert_planned(
    session: AsyncSession,
    *,
    shop_id: int,
    customer_id: int,
    planned: list[PlannedNotification],
) -> int:
    """Insert, ignoring rows that already exist. Returns how many were new."""
    inserted = 0
    for start in range(0, len(planned), INSERT_BATCH_SIZE):
        chunk = planned[start : start + INSERT_BATCH_SIZE]
        stmt = (
            insert(ScheduledNotification)
            .values(
                [
                    {
                        "shop_id": shop_id,
                        "customer_id": customer_id,
                        "occasion_id": row.occasion_id,
                        "occurrence_year": row.occurrence_year,
                        "offset_days": row.offset_days,
                        "due_at_utc": row.due_at_utc,
                        "channel": row.channel,
                        "merge_key": row.merge_key,
                    }
                    for row in chunk
                ]
            )
            .on_conflict_do_nothing(
                index_elements=[
                    "occasion_id",
                    "occurrence_year",
                    "offset_days",
                    "channel",
                ]
            )
            .returning(ScheduledNotification.id)
        )
        result = await session.scalars(stmt)
        inserted += len(list(result))
    return inserted


async def _prune_unwanted_offsets(
    session: AsyncSession, *, shop_id: int, customer_id: int, offsets: tuple[int, ...]
) -> int:
    """Drop PENDING rows for offsets this customer no longer wants.

    Offsets are per customer now, so they change whenever someone answers the
    preference question again. Without this, a customer who moved from three
    reminders to one would keep receiving the two they turned off.
    """
    result = await session.execute(
        delete(ScheduledNotification)
        .where(
            ScheduledNotification.shop_id == shop_id,
            ScheduledNotification.customer_id == customer_id,
            ScheduledNotification.state.in_(RECONCILABLE_STATES),
            ScheduledNotification.offset_days.notin_(offsets),
        )
        .returning(ScheduledNotification.id)
    )
    return len(list(result))


async def _prune_inactive(session: AsyncSession, *, shop_id: int) -> int:
    """Drop PENDING rows whose occasion or recipient has been deactivated.

    Scoped to pending. Already-sent reminders for a since-deleted date stay
    exactly where they are: the customer really did receive them.
    """
    still_scheduled = (
        select(Occasion.id)
        .join(Recipient, Recipient.id == Occasion.recipient_id)
        .where(
            Occasion.shop_id == shop_id,
            Occasion.active.is_(True),
            Recipient.active.is_(True),
        )
    )
    result = await session.execute(
        delete(ScheduledNotification)
        .where(
            ScheduledNotification.shop_id == shop_id,
            ScheduledNotification.state.in_(RECONCILABLE_STATES),
            ScheduledNotification.occasion_id.notin_(still_scheduled),
        )
        .returning(ScheduledNotification.id)
    )
    return len(list(result))


async def materialize_shop(
    session: AsyncSession,
    *,
    shop_id: int,
    now_utc: datetime,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    channel: str = NotificationChannel.TELEGRAM.value,
) -> MaterializeResult:
    """Bring the outbox up to date for one shop. Safe to run repeatedly."""
    shop = await session.get(Shop, shop_id)
    if shop is None:
        raise ValueError(f"no such shop: {shop_id}")

    grouped = await _active_occasions_by_customer(session, shop_id=shop_id)

    # Loaded in ONE query rather than per customer: at 10k occasions the
    # per-customer fetch was the difference between a handful of round trips
    # and several hundred.
    customers = {
        customer.id: customer
        for customer in await session.scalars(
            select(Customer).where(Customer.id.in_(grouped.keys()))
        )
    }

    total_planned = 0
    total_inserted = 0
    total_pruned_offsets = 0
    total_occasions = 0

    for customer_id, occasions in grouped.items():
        customer = customers.get(customer_id)
        if customer is None:  # pragma: no cover - FK makes this unreachable
            continue

        settings = resolve_reminder_settings(customer, shop)
        total_occasions += len(occasions)

        planned = plan_notifications(
            [
                OccasionSpec(
                    occasion_id=occasion.id,
                    month=occasion.month,
                    day=occasion.day,
                    year=occasion.year,
                )
                for occasion in occasions
            ],
            now_utc=now_utc,
            offsets=settings.offsets,
            send_time=settings.send_time,
            horizon_days=horizon_days,
            channel=channel,
        )
        total_planned += len(planned)
        total_inserted += await _insert_planned(
            session, shop_id=shop_id, customer_id=customer_id, planned=planned
        )
        total_pruned_offsets += await _prune_unwanted_offsets(
            session, shop_id=shop_id, customer_id=customer_id, offsets=settings.offsets
        )

    pruned_inactive = await _prune_inactive(session, shop_id=shop_id)

    return MaterializeResult(
        customers=len(grouped),
        occasions=total_occasions,
        planned=total_planned,
        inserted=total_inserted,
        pruned_offsets=total_pruned_offsets,
        pruned_inactive=pruned_inactive,
    )
