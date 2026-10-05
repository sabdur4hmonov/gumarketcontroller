"""Telling the shop about an order: once when it is placed, then before delivery.

Same two-phase shape as CP6's reminder tick, and for the same reason:

    Phase 1 (one transaction, then COMMIT)
        select due rows FOR UPDATE SKIP LOCKED
        claim them -- pending/failed -> sending, attempts + 1
        COMMIT   <- the claims are now durable

    Phase 2 (no locks held; one transaction per ping)
        send
        resolve the row, then COMMIT

The commit between the phases is the whole design. Claiming inside the same
transaction as the send would roll the claim back when a worker dies, and the
retry would find a pending row and send the shop a second copy.

WHAT IS DIFFERENT FROM CP6: there is no `message_log`. CP6 needed a separate
ledger because a GROUP of notification rows shares one message, so the claim had
to live somewhere that could name the group. Here one ping is one message, so
the row is its own ledger -- `state` IS the claim. That was the standing
decision, and it also avoids loosening `message_log.customer_id NOT NULL`, which
an admin-facing message has no honest value for.

WHERE IT GOES. `shops.group_chat_id` if set, else every id in
`shops.owner_telegram_ids`, else nowhere -- and nowhere is an ERROR, logged with
the shop and order id on every attempt, then parked like any other failure.
Leaving it pending forever would mean the tick re-reads a growing pile of
undeliverable rows once a minute for the life of the shop.

MANY OWNERS, ONE PING. When the fallback fans out to several owners the ping
counts as sent if ANY delivery succeeded. One owner who blocked the bot must not
make the whole shop's order look undelivered.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from aiogram.types import InlineKeyboardMarkup
from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.bot.keyboards import order_admin_keyboard
from gulbot.models.customer import Customer
from gulbot.models.order import SENDABLE_PING_STATES, Order, OrderReminder, PingState
from gulbot.models.shop import Shop
from gulbot.scheduling.occurrences import TASHKENT
from gulbot.sending.order_card import ANNOUNCEMENT, OrderCard, render_card
from gulbot.sending.transport import (
    CAPTION_LIMIT,
    SendResult,
    ShopBotUnavailable,
    ShopBreaker,
    ShopBreakers,
    Transport,
    TransportFor,
    per_shop,
)
from gulbot.services.shop_language import shop_language

log = logging.getLogger("gulbot.sending.orders")

#: Rows per tick. Pings are far rarer than reminders; this only bounds how long
#: one tick holds its locks.
BATCH_SIZE = 100

#: Attempts before a ping is parked. Five spreads retries over five minutes of
#: ticks, which outlasts a transient Telegram outage. Same number as CP6.
MAX_PING_ATTEMPTS = 5

#: A row left in SENDING for longer than this belonged to a worker that died.
#: Generous on purpose: retaking a claim from a worker that is merely slow is
#: how a duplicate gets sent.
CLAIM_TIMEOUT = timedelta(minutes=5)


@dataclass
class PingTickResult:
    claimed: int = 0
    sent: int = 0
    failed: int = 0
    dead_lettered: int = 0
    undeliverable: int = 0
    #: Claimed, never attempted, returned untouched because the breaker opened.
    handed_back: int = 0
    errors: list[str] = field(default_factory=list)


async def ping_targets(session: AsyncSession, *, shop_id: int) -> list[int]:
    """Where this shop's pings go, in the order the decision was made.

    The group is the destination. The owners are the fallback for a shop that
    has not been given one yet -- which is a setup that is not finished, not a
    supported mode, so it is logged every time it is used.
    """
    row = (
        await session.execute(
            select(Shop.group_chat_id, Shop.owner_telegram_ids).where(Shop.id == shop_id)
        )
    ).one_or_none()
    if row is None:  # pragma: no cover - the FK makes this unreachable
        return []
    if row.group_chat_id is not None:
        return [int(row.group_chat_id)]
    owners = [int(owner) for owner in (row.owner_telegram_ids or [])]
    if owners:
        log.warning(
            "shop %s has no group_chat_id; falling back to %d owner chat(s)", shop_id, len(owners)
        )
    return owners


async def load_card(session: AsyncSession, *, order_id: int) -> OrderCard | None:
    """Flatten one order into what the shop is shown.

    Reads the SNAPSHOT columns only. The product row is not consulted even if it
    still exists -- the shop must be told what the customer agreed to buy.
    """
    row = (
        await session.execute(
            select(
                Order.id,
                Order.product_name_snapshot,
                Order.price_uzs_snapshot,
                Order.telegram_file_id_snapshot,
                Order.delivery_date,
                Order.delivery_hour,
                Order.delivery_location_text,
                Order.delivery_location_lat,
                Order.delivery_location_lon,
                Order.landmark,
                Order.recipient_name,
                Customer.telegram_user_id,
                Customer.phone,
                Customer.phone_verified,
            )
            .join(Customer, Customer.id == Order.customer_id)
            .where(Order.id == order_id)
        )
    ).one_or_none()
    if row is None:  # pragma: no cover - ON DELETE CASCADE removes the pings too
        return None
    return OrderCard(
        order_id=row.id,
        product_name=row.product_name_snapshot,
        price_uzs=row.price_uzs_snapshot,
        telegram_file_id=row.telegram_file_id_snapshot,
        delivery_date=row.delivery_date,
        delivery_hour=row.delivery_hour,
        landmark=row.landmark,
        recipient_name=row.recipient_name,
        customer_telegram_id=row.telegram_user_id,
        location_text=row.delivery_location_text,
        location_lat=row.delivery_location_lat,
        location_lon=row.delivery_location_lon,
        customer_phone=row.phone,
        phone_verified=row.phone_verified,
    )


def hours_ahead(card: OrderCard, due_at_utc: datetime) -> int:
    """The interval this ping was SCHEDULED for, recovered from its own due time.

    Deliberately not `delivery - now`. A tick that runs late would then tell the
    shop a different number from the one the ping was created to say.
    """
    delivery = datetime.combine(card.delivery_date, card.delivery_hour, tzinfo=TASHKENT).astimezone(
        UTC
    )
    return max(round((delivery - due_at_utc).total_seconds() / 3600), 0)


async def claim_due_pings(
    session: AsyncSession,
    *,
    now_utc: datetime,
    limit: int = BATCH_SIZE,
    only_order_id: int | None = None,
) -> list[OrderReminder]:
    """Take ownership of every due ping. Does NOT commit -- the caller does.

    The commit belongs to `run_order_ping_tick`, which first parks any ping that
    has burned its attempts, so the claims and the dead-letters land together.
    Committing here would make that two transactions for no reason. What matters
    is only that the commit happens BEFORE Telegram is called, and it does.

    `only_order_id` narrows the claim to one order. That is how the bot process
    delivers a brand-new order immediately instead of waiting up to a minute for
    the next beat: it runs exactly this code against exactly one row. The claim
    is the same compare-and-swap either way, so the beat cannot send a second
    copy of something the request handler already sent -- and if the handler
    dies, the beat picks the row up once the claim goes stale.
    """
    due = (
        select(OrderReminder.id)
        .where(
            OrderReminder.due_at_utc <= now_utc,
            or_(
                OrderReminder.state.in_(SENDABLE_PING_STATES),
                # A claim whose worker never came back.
                and_(
                    OrderReminder.state == PingState.SENDING.value,
                    OrderReminder.claimed_at < now_utc - CLAIM_TIMEOUT,
                ),
            ),
        )
        .order_by(OrderReminder.due_at_utc, OrderReminder.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    if only_order_id is not None:
        due = due.where(OrderReminder.order_id == only_order_id)

    claimed = await session.scalars(
        update(OrderReminder)
        .where(OrderReminder.id.in_(due))
        .values(
            state=PingState.SENDING.value,
            claimed_at=now_utc,
            attempts=OrderReminder.attempts + 1,
        )
        .returning(OrderReminder)
    )
    return list(claimed)


async def _resolve(
    session: AsyncSession,
    ping: OrderReminder,
    *,
    state: PingState,
    now_utc: datetime,
    sent: bool = False,
) -> None:
    values: dict[str, object] = {"state": state.value, "claimed_at": None}
    if sent:
        values["sent_at"] = now_utc
    await session.execute(update(OrderReminder).where(OrderReminder.id == ping.id).values(**values))


async def _deliver(
    transport: Transport,
    *,
    targets: list[int],
    card: OrderCard,
    text: str,
    ping_number: int,
    reply_markup: InlineKeyboardMarkup | None = None,
    breaker: ShopBreaker | None = None,
) -> tuple[bool, list[str]]:
    """Send to every target. True if at least one accepted.

    The keyboard rides on BOTH paths. A card too long to be a caption falls
    back to text, and a fallback that quietly dropped the only way to act on
    the order would be a hole nobody notices until an order sits unanswered.
    """
    delivered = False
    errors: list[str] = []
    for chat_id in targets:
        if len(text) <= CAPTION_LIMIT:
            outcome = await transport.send_photo(
                chat_id=chat_id,
                file_id=card.telegram_file_id,
                caption=text,
                reply_markup=reply_markup,
            )
        else:
            # Too long to be a caption. Still ONE call, and the shop still gets
            # every field -- the photo is what is dropped, not the order.
            outcome = await transport.send_text(
                chat_id=chat_id, text=text, reply_markup=reply_markup
            )
        if outcome.ok:
            delivered = True
            # The message id is the only handle anyone has on what the shop
            # actually received. Without it "state = sent" is a claim with
            # nothing behind it, and a support question about a missing order
            # has no thread to pull.
            log.info(
                "order ping order=%s ping=%s -> chat %s as message %s",
                card.order_id,
                ping_number,
                chat_id,
                outcome.message_id,
            )
        else:
            errors.append(_error_of(outcome))
        if breaker is not None:
            breaker.record(outcome)
            if breaker.open:
                # The remaining owners would each wait out the same timeout.
                break
    return delivered, errors


def _error_of(outcome: SendResult) -> str:
    if outcome.retry_after is not None:
        return f"rate_limited:{outcome.retry_after}"
    return outcome.error_code or "unknown"


async def run_order_ping_tick(
    session: AsyncSession,
    *,
    now_utc: datetime,
    transport: Transport | None = None,
    transport_for: TransportFor | None = None,
    limit: int = BATCH_SIZE,
    only_order_id: int | None = None,
) -> PingTickResult:
    """One beat of the shop-facing outbox.

    Each ping goes out through ITS shop's bot -- `transport_for(ping.shop_id)`
    -- to that shop's own targets (C2 of AUDIT_MULTI_TENANT.md). The chat was
    always resolved per shop; the BOT was not, so a card carrying one shop's
    customer phone and address could be sent by another shop's bot. See
    `per_shop` for the two ways in; checked before anything is claimed.
    """
    transport_for = per_shop(transport, transport_for)
    result = PingTickResult()

    pings = await claim_due_pings(
        session, now_utc=now_utc, limit=limit, only_order_id=only_order_id
    )
    if not pings:
        await session.commit()
        return result
    result.claimed = len(pings)

    # A ping that has burned its attempts is parked BEFORE the claims commit, so
    # a worker that dies now does not resurrect it.
    live: list[OrderReminder] = []
    for ping in pings:
        if ping.attempts > MAX_PING_ATTEMPTS:
            await _resolve(session, ping, state=PingState.DEAD_LETTER, now_utc=now_utc)
            result.dead_lettered += 1
            log.error(
                "order ping order=%s ping=%s dead-lettered after %s attempts",
                ping.order_id,
                ping.ping_number,
                ping.attempts - 1,
            )
        else:
            live.append(ping)

    # Everything past this point may crash without causing a duplicate send.
    await session.commit()

    targets_by_shop: dict[int, list[int]] = {}
    # What each shop's own people read (L2): asked per shop, never once per
    # tick, because the batch spans every shop.
    lang_by_shop: dict[int, str] = {}
    breakers = ShopBreakers()
    for ping in live:
        if breakers.open_for(ping.shop_id):
            # This shop's bot -- or, on a fleet trip, Telegram -- has stopped
            # answering; see ShopBreakers. Its pings go back as they were, for
            # the next tick, and every other shop's still go out (H5).
            await _hand_back(session, ping)
            result.handed_back += 1
            await session.commit()
            continue

        if ping.shop_id not in targets_by_shop:
            targets_by_shop[ping.shop_id] = await ping_targets(session, shop_id=ping.shop_id)
        targets = targets_by_shop[ping.shop_id]
        if ping.shop_id not in lang_by_shop:
            lang_by_shop[ping.shop_id] = await shop_language(session, shop_id=ping.shop_id)
        lang = lang_by_shop[ping.shop_id]

        card = await load_card(session, order_id=ping.order_id)
        if card is None:  # pragma: no cover - CASCADE removes pings with orders
            await _resolve(session, ping, state=PingState.DEAD_LETTER, now_utc=now_utc)
            result.dead_lettered += 1
            await session.commit()
            continue

        if not targets:
            # The order is written and safe; nobody can be told about it. This is
            # a finished-order-in-an-unfinished-setup, and it is the loudest line
            # this module has.
            log.error(
                "ORDER %s CANNOT REACH SHOP %s: set shops.group_chat_id or "
                "shops.owner_telegram_ids. ping=%s attempt=%s",
                ping.order_id,
                ping.shop_id,
                ping.ping_number,
                ping.attempts,
            )
            await _resolve(session, ping, state=PingState.FAILED, now_utc=now_utc)
            result.undeliverable += 1
            result.failed += 1
            await session.commit()
            continue

        try:
            shop_transport = transport_for(ping.shop_id)
        except ShopBotUnavailable as missing:
            # The same finished-order-in-an-unfinished-setup as above, one layer
            # down: there is somewhere to send, and no bot to send it with. The
            # same treatment -- loud, failed, retried, parked at the cap -- and
            # every other shop's pings still go out. Not recorded to the
            # breaker: it says nothing about whether Telegram is answering.
            log.error(
                "ORDER %s CANNOT REACH SHOP %s: %s. ping=%s attempt=%s",
                ping.order_id,
                ping.shop_id,
                missing,
                ping.ping_number,
                ping.attempts,
            )
            await _resolve(session, ping, state=PingState.FAILED, now_utc=now_utc)
            result.undeliverable += 1
            result.failed += 1
            await session.commit()
            continue

        text = render_card(
            card,
            ping_number=ping.ping_number,
            hours_ahead=None
            if ping.ping_number == ANNOUNCEMENT
            else hours_ahead(card, ping.due_at_utc),
            lang=lang,
        )
        # ONLY THE ANNOUNCEMENT CARRIES THE BUTTONS. The delivery pings are
        # logistics for an order that has already been decided; putting
        # Confirm on them would offer a decision twice and leave two cards
        # disagreeing about which one is the record. A shop that never
        # answers still gets the pings, which say the delivery is coming --
        # that is the nudge, and it does not need a second button.
        breaker = breakers.for_shop(ping.shop_id)
        delivered, errors = await _deliver(
            shop_transport,
            targets=targets,
            card=card,
            text=text,
            ping_number=ping.ping_number,
            reply_markup=order_admin_keyboard(lang, card.order_id)
            if ping.ping_number == ANNOUNCEMENT
            else None,
            breaker=breaker,
        )

        if delivered:
            await _resolve(session, ping, state=PingState.SENT, now_utc=now_utc, sent=True)
            result.sent += 1
        else:
            await _resolve(session, ping, state=PingState.FAILED, now_utc=now_utc)
            result.failed += 1
            result.errors.extend(errors)
            log.warning(
                "order ping order=%s ping=%s failed: %s", ping.order_id, ping.ping_number, errors
            )
        await session.commit()
        if breaker.tripped == "shop":
            log.warning(
                "order pings: shop %s's bot got no answer %d times running; handing "
                "that shop's pings back to the next tick, every other shop keeps sending",
                ping.shop_id,
                breakers.threshold,
            )
        elif breaker.tripped == "fleet":
            log.warning(
                "order pings: %d different shops got no answer in a row; Telegram looks "
                "unreachable, handing the rest of the batch back to the next tick",
                breakers.fleet_shops,
            )

    return result


async def _hand_back(session: AsyncSession, ping: OrderReminder) -> None:
    """Undo the claim on a ping that was never attempted.

    The claim moved it to SENDING and counted an attempt; both are reversed.
    The state it goes back to is recovered from the attempt count rather than
    remembered: a ping claimed with no earlier attempt was PENDING, and one with
    earlier attempts can only have come from FAILED (or a dead worker's SENDING,
    which is the same thing -- a send whose outcome was never recorded). Both
    are in SENDABLE_PING_STATES and both are counted as overdue by the health
    check, so neither choice changes what anything filters or counts.
    """
    await session.execute(
        update(OrderReminder)
        .where(OrderReminder.id == ping.id)
        .values(
            state=PingState.PENDING.value if ping.attempts <= 1 else PingState.FAILED.value,
            attempts=OrderReminder.attempts - 1,
            claimed_at=None,
        )
    )
