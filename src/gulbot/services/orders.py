"""Placing an order, and scheduling the shop's pings for it.

Three things live here and nothing else: reading a shop's delivery policy,
writing one order exactly once, and materialising its admin pings. No Telegram,
no message wording -- the router composes what the customer sees.

SINGLE FLIGHT IS A UNIQUE INDEX, not a UI trick. Answering the callback and
editing the keyboard away are worth doing, and they are a race the customer can
win: two taps in flight before either handler has written anything. The
confirmation screen mints a `submit_token`, both taps carry the same one, and
`ON CONFLICT (shop_id, submit_token) DO NOTHING` decides. The loser is told the
same thing as the winner, because from the customer's side one order was placed
-- which is true.

THE SNAPSHOT IS THE RECORD. Name, price and file id are frozen onto the order,
because the catalogue is rebuilt from a channel where posts are edited and
deleted. `product_id` is kept as a convenience and may become NULL later; the
order does not depend on it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.models.order import Order, OrderReminder, OrderStatus
from gulbot.models.product import Product
from gulbot.models.shop import Shop
from gulbot.scheduling.delivery import SlotPolicy
from gulbot.sending.order_card import ANNOUNCEMENT


@dataclass(frozen=True)
class OrderDraft:
    """Everything the FSM collected, before anything is written.

    The snapshot fields are what the confirmation screen SHOWED. They are the
    fallback if the product row has disappeared by the time the customer taps
    submit -- the customer agreed to buy what they were shown.
    """

    product_id: int
    product_name: str
    price_uzs: int | None
    telegram_file_id: str
    delivery_date: date
    delivery_hour: time
    landmark: str
    submit_token: str
    recipient_id: int | None = None
    location_text: str | None = None
    location_lat: float | None = None
    location_lon: float | None = None


async def load_slot_policy(session: AsyncSession, *, shop_id: int) -> SlotPolicy:
    """The shop's delivery rules, read once per picker render."""
    row = (
        await session.execute(
            select(Shop.working_hours, Shop.same_day_cutoff, Shop.min_lead_time_minutes).where(
                Shop.id == shop_id
            )
        )
    ).one()
    return SlotPolicy(
        working_hours=row.working_hours,
        same_day_cutoff=row.same_day_cutoff,
        min_lead_minutes=row.min_lead_time_minutes,
    )


async def dates_at_capacity(
    session: AsyncSession, *, shop_id: int, horizon_start: date, horizon_end: date
) -> frozenset[date]:
    """Delivery dates already holding `daily_order_cap` orders.

    Enforced at DATE SELECTION -- the standing decision from the original
    design review. A full date is simply absent from the picker rather than
    offered and then refused at submit, which would waste the whole flow.

    Counted against `delivery_date`, never `created_at`, and cancelled and
    rejected orders do not count against it.
    """
    cap = await session.scalar(select(Shop.daily_order_cap).where(Shop.id == shop_id))
    if cap is None:
        return frozenset()

    rows = await session.execute(
        select(Order.delivery_date)
        .where(
            Order.shop_id == shop_id,
            Order.delivery_date.between(horizon_start, horizon_end),
            Order.status.notin_([OrderStatus.CANCELLED.value, OrderStatus.REJECTED.value]),
        )
        .group_by(Order.delivery_date)
        .having(func.count() >= cap)
    )
    return frozenset(rows.scalars())


async def create_order(session: AsyncSession, *, shop_id: int, customer_id: int, draft: OrderDraft):  # type: ignore[no-untyped-def]
    """Write the order, exactly once. Returns (order, created).

    `created` is False when this call lost a double-tap race; the order in that
    case is the one the winner wrote, so the caller can confirm it either way.
    """
    product = await session.scalar(
        select(Product).where(Product.id == draft.product_id, Product.shop_id == shop_id)
    )
    # Frozen at submit from the live row -- or from what the confirmation screen
    # showed, if the indexer deleted the post in between. Either way the order
    # records what the customer agreed to buy.
    name = product.name if product is not None else draft.product_name
    price = product.price_uzs if product is not None else draft.price_uzs
    file_id = product.telegram_file_id if product is not None else draft.telegram_file_id

    statement = (
        insert(Order)
        .values(
            shop_id=shop_id,
            customer_id=customer_id,
            recipient_id=draft.recipient_id,
            product_id=product.id if product is not None else None,
            product_name_snapshot=name,
            price_uzs_snapshot=price,
            telegram_file_id_snapshot=file_id,
            delivery_date=draft.delivery_date,
            delivery_hour=draft.delivery_hour,
            delivery_location_text=draft.location_text,
            delivery_location_lat=draft.location_lat,
            delivery_location_lon=draft.location_lon,
            landmark=draft.landmark,
            status=OrderStatus.PLACED.value,
            submit_token=draft.submit_token,
        )
        .on_conflict_do_nothing(index_elements=["shop_id", "submit_token"])
        .returning(Order.id)
    )
    order_id = (await session.execute(statement)).scalar_one_or_none()
    if order_id is None:
        # Lost the race. The winner's row is the order.
        existing = await session.scalar(
            select(Order).where(Order.shop_id == shop_id, Order.submit_token == draft.submit_token)
        )
        return existing, False

    await session.flush()
    return await session.get(Order, order_id), True


async def announce_order(
    session: AsyncSession, *, order: Order, now_utc: datetime | None = None
) -> bool:
    """Queue the "new order" message to the shop. Idempotent.

    Ping 0, due immediately. It goes through the SAME outbox as the delivery
    reminders rather than being sent inline from the request handler, and that
    is the point: an order the shop never learns about is the worst failure this
    system has, so it must survive a Telegram hiccup, a dropped connection and a
    process restart. Best-effort inline sending survives none of those.

    Immediacy is not sacrificed for it -- the handler flushes this row itself the
    moment the transaction commits (see the router), and the beat is the safety
    net rather than the normal path.

    Returns whether a row was created; False means it already existed, which is
    what makes calling this twice harmless.
    """
    statement = (
        insert(OrderReminder)
        .values(
            shop_id=order.shop_id,
            order_id=order.id,
            ping_number=ANNOUNCEMENT,
            due_at_utc=now_utc or datetime.now(UTC),
        )
        .on_conflict_do_nothing(index_elements=["order_id", "ping_number"])
        .returning(OrderReminder.id)
    )
    created = await session.scalar(statement)
    await session.flush()
    return created is not None


def ping_times(
    delivery_at_utc: datetime, offsets_hours: list[int], now_utc: datetime
) -> list[tuple[int, datetime]]:
    """(ping_number, due_at_utc) for every ping still in the future.

    A ping whose moment has already passed is NOT created. Backdating it would
    fire the moment the tick next runs, telling the shop a delivery is three
    hours away when it is one -- worse than staying quiet. An order placed
    inside the first offset simply gets fewer pings.
    """
    due: list[tuple[int, datetime]] = []
    for index, hours in enumerate(offsets_hours, start=1):
        moment = delivery_at_utc - timedelta(hours=hours)
        if moment > now_utc:
            due.append((index, moment))
    return due


async def materialize_order_pings(
    session: AsyncSession,
    *,
    order: Order,
    delivery_at_utc: datetime,
    now_utc: datetime | None = None,
) -> int:
    """Create this order's ping rows. Idempotent.

    ON CONFLICT DO NOTHING against UNIQUE(order_id, ping_number), so running it
    twice cannot double-ping the shop -- the same role the unique key plays in
    `scheduled_notifications`.
    """
    now = now_utc or datetime.now(UTC)
    offsets = await session.scalar(
        select(Shop.order_ping_offset_hours).where(Shop.id == order.shop_id)
    )
    planned = ping_times(delivery_at_utc, list(offsets or []), now)
    if not planned:
        return 0

    await session.execute(
        insert(OrderReminder)
        .values(
            [
                {
                    "shop_id": order.shop_id,
                    "order_id": order.id,
                    "ping_number": number,
                    "due_at_utc": moment,
                }
                for number, moment in planned
            ]
        )
        .on_conflict_do_nothing(index_elements=["order_id", "ping_number"])
    )
    await session.flush()
    return len(planned)
