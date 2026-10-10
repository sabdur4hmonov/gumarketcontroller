"""The nightly materializer: write the next ~45 days of the outbox.

It does three things and no more:

1. RESOLVE each customer's offsets and send time through the fallback chain.
2. PLAN with the pure engine (CP4) and INSERT with ON CONFLICT DO NOTHING, so
   running it twice is indistinguishable from running it once.
3. RECONCILE: delete PENDING rows that no longer belong -- offsets the customer
   has since dropped, occasions or recipients that have been deactivated, and
   anything belonging to a customer who is no longer active (CP6 marks a
   customer blocked when Telegram returns 403).

CP20: a shop's HOLIDAY CAMPAIGNS are planned in the same pass, for the
customers who opted in, as more dates in the same per-customer plan -- so the
merge window and the weekly cap cover personal dates and holidays together.
Their rows name the holiday instead of an occasion
(gulbot.services.holiday_campaigns has the three conditions).

It sends nothing. No Telegram, no beat tick, no message_log: that is CP6.

RECONCILIATION ONLY EVER TOUCHES state='pending'. A sent or expired row is
HISTORY, not a schedule. Deleting one would make the bot forget it had already
reminded someone, and the next run would remind them again -- exactly the
duplicate the unique constraint exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, delete, or_, select, text, true
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.holidays import BY_SPEC_ID, is_holiday_spec
from gulbot.models.customer import Customer, CustomerStatus
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
from gulbot.services.holiday_campaigns import (
    enabled_holidays,
    holiday_specs,
    lunar_dates,
    opted_in_customers,
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
    #: CP20: pending holiday rows no longer wanted (holiday off, opted out).
    pruned_holidays: int = 0

    @property
    def pruned(self) -> int:
        return self.pruned_offsets + self.pruned_inactive + self.pruned_holidays


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
        .join(Customer, Customer.id == Occasion.customer_id)
        .where(
            Occasion.shop_id == shop_id,
            Occasion.active.is_(True),
            Recipient.active.is_(True),
            # A customer who blocked the bot, or opted out, stops generating
            # rows entirely. Without this the outbox refills every night with
            # sends that can only ever come back 403.
            Customer.status == CustomerStatus.ACTIVE.value,
        )
        .order_by(Occasion.customer_id, Occasion.id)
    )
    grouped: dict[int, list[Occasion]] = {}
    for occasion in rows:
        grouped.setdefault(occasion.customer_id, []).append(occasion)
    return grouped


def _row(shop_id: int, customer_id: int, row: PlannedNotification) -> dict[str, object]:
    holiday = is_holiday_spec(row.occasion_id)
    return {
        "shop_id": shop_id,
        "customer_id": customer_id,
        "occasion_id": None if holiday else row.occasion_id,
        "holiday": BY_SPEC_ID[row.occasion_id].key if holiday else None,
        "occurrence_year": row.occurrence_year,
        "offset_days": row.offset_days,
        "due_at_utc": row.due_at_utc,
        "channel": row.channel,
        "merge_key": row.merge_key,
    }


async def _insert_planned(
    session: AsyncSession,
    *,
    shop_id: int,
    customer_id: int,
    planned: list[PlannedNotification],
) -> int:
    """Insert, ignoring rows that already exist. Returns how many were new.

    A holiday's plan carries its negative spec id (gulbot.holidays): its row
    names the holiday instead of an occasion, and conflicts on its own unique
    index, since the occasion UNIQUE never compares a NULL occasion_id."""
    personal = [row for row in planned if not is_holiday_spec(row.occasion_id)]
    holidays = [row for row in planned if is_holiday_spec(row.occasion_id)]
    inserted = 0
    for rows, conflict, where in (
        (personal, ["occasion_id", "occurrence_year", "offset_days", "channel"], None),
        (
            holidays,
            ["customer_id", "holiday", "occurrence_year", "offset_days", "channel"],
            text("holiday IS NOT NULL"),
        ),
    ):
        for start in range(0, len(rows), INSERT_BATCH_SIZE):
            chunk = rows[start : start + INSERT_BATCH_SIZE]
            stmt = (
                insert(ScheduledNotification)
                .values([_row(shop_id, customer_id, row) for row in chunk])
                .on_conflict_do_nothing(index_elements=conflict, index_where=where)
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
    exactly where they are: the customer really did receive them. Holiday rows
    have no occasion and are reconciled by `_prune_holidays`.
    """
    still_scheduled = (
        select(Occasion.id)
        .join(Recipient, Recipient.id == Occasion.recipient_id)
        .join(Customer, Customer.id == Occasion.customer_id)
        .where(
            Occasion.shop_id == shop_id,
            Occasion.active.is_(True),
            Recipient.active.is_(True),
            Customer.status == CustomerStatus.ACTIVE.value,
        )
    )
    result = await session.execute(
        delete(ScheduledNotification)
        .where(
            ScheduledNotification.shop_id == shop_id,
            ScheduledNotification.occasion_id.is_not(None),
            ScheduledNotification.state.in_(RECONCILABLE_STATES),
            ScheduledNotification.occasion_id.notin_(still_scheduled),
        )
        .returning(ScheduledNotification.id)
    )
    return len(list(result))


async def _prune_holidays(
    session: AsyncSession, *, shop_id: int, holidays: set[str], customers: set[int]
) -> int:
    """Drop PENDING holiday rows this shop no longer wants: a holiday it has
    switched off (or a lunar one with no date any more), or a customer who has
    opted out or is no longer active. Opting out and switching off already do
    this at once; this is the nightly backstop."""
    unwanted: ColumnElement[bool] = or_(
        ScheduledNotification.holiday.notin_(holidays) if holidays else true(),
        ScheduledNotification.customer_id.notin_(customers) if customers else true(),
    )
    result = await session.execute(
        delete(ScheduledNotification)
        .where(
            ScheduledNotification.shop_id == shop_id,
            ScheduledNotification.holiday.is_not(None),
            ScheduledNotification.state.in_(RECONCILABLE_STATES),
            unwanted,
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
    shop = await session.scalar(select(Shop).where(Shop.id == shop_id))
    if shop is None:
        raise ValueError(f"no such shop: {shop_id}")

    grouped = await _active_occasions_by_customer(session, shop_id=shop_id)

    # CP20: the shop's campaigns, and who asked to hear about them.
    campaigns: list[OccasionSpec] = []
    listeners: set[int] = set()
    enabled = await enabled_holidays(session, shop_id=shop_id)
    if enabled:
        campaigns = holiday_specs(enabled, await lunar_dates(session))
        if campaigns:
            listeners = await opted_in_customers(session, shop_id=shop_id)

    # Loaded in ONE query rather than per customer: at 10k occasions the
    # per-customer fetch was the difference between a handful of round trips
    # and several hundred.
    customers = {
        customer.id: customer
        for customer in await session.scalars(
            select(Customer).where(
                Customer.shop_id == shop_id,
                Customer.id.in_(set(grouped) | listeners),
                Customer.status == CustomerStatus.ACTIVE.value,
            )
        )
    }
    listeners &= set(customers)

    total_planned = 0
    total_inserted = 0
    total_pruned_offsets = 0
    total_occasions = 0

    for customer_id in sorted(set(grouped) | listeners):
        customer = customers.get(customer_id)
        if customer is None:  # pragma: no cover - grouped is already active-only
            continue
        occasions = grouped.get(customer_id, [])

        settings = resolve_reminder_settings(customer, shop)
        total_occasions += len(occasions)

        specs = [
            OccasionSpec(
                occasion_id=occasion.id,
                month=occasion.month,
                day=occasion.day,
                year=occasion.year,
            )
            for occasion in occasions
        ]
        if customer_id in listeners:
            specs.extend(campaigns)

        planned = plan_notifications(
            specs,
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
    pruned_holidays = await _prune_holidays(
        session,
        shop_id=shop_id,
        holidays={BY_SPEC_ID[spec.occasion_id].key for spec in campaigns},
        customers=listeners,
    )

    return MaterializeResult(
        customers=len(set(grouped) | listeners),
        occasions=total_occasions,
        planned=total_planned,
        inserted=total_inserted,
        pruned_offsets=total_pruned_offsets,
        pruned_inactive=pruned_inactive,
        pruned_holidays=pruned_holidays,
    )
