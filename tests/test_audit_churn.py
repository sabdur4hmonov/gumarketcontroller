"""PASS 3 of the pre-deployment audit: data integrity under real-world churn.

Shops post, edit and delete; customers add, rename and remove the people they
care about; customers block the bot. Each chain below is walked end to end
against real rows, and each test says in its docstring which outcome is the
defect and which is the clean result -- so a reader can tell a finding from a
confirmation without the report open beside it.

Two deactivation tests deliberately bypass the services with raw SQL. They test
the nightly RECONCILIATION predicate in isolation, and going through the service
would let a fix to the service mask a defect in the predicate.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker
from tests.bot_harness import bound_session_factory

from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.sending.dispatcher import MAX_SEND_ATTEMPTS, RETRY_BACKOFF, run_tick
from gulbot.sending.health import read_health
from gulbot.sending.order_card import ANNOUNCEMENT
from gulbot.sending.order_pings import run_order_ping_tick
from gulbot.sending.render import render_reminder
from gulbot.sending.transport import SendResult
from gulbot.services.materializer import materialize_shop
from gulbot.services.occasions import deactivate_occasion
from gulbot.services.recipients import deactivate_recipient, rename_recipient

pytestmark = pytest.mark.infra

NOW = datetime(2027, 3, 8, 6, 0, tzinfo=UTC)  # 11:00 Tashkent, inside the send window
GROUP_ID = -1001234


class FakeTransport:
    """Records every send. Scripted outcomes are consumed one per call."""

    def __init__(self, *outcomes: SendResult) -> None:
        self.calls: list[dict] = []
        self._outcomes = list(outcomes)

    def _next(self) -> SendResult:
        return self._outcomes.pop(0) if self._outcomes else SendResult.sent(len(self.calls))

    async def send_text(
        self, *, chat_id: int, text: str, reply_markup: object = None
    ) -> SendResult:
        self.calls.append({"kind": "text", "chat_id": chat_id, "text": text})
        return self._next()

    async def send_photo(
        self, *, chat_id: int, file_id: str, caption: str, reply_markup: object = None
    ) -> SendResult:
        self.calls.append({"kind": "photo", "chat_id": chat_id, "text": caption})
        return self._next()

    async def copy_message(self, **kw: object) -> SendResult:  # pragma: no cover - unused
        raise AssertionError("no path under test copies a message")


@pytest_asyncio.fixture
async def sessions(db: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    return bound_session_factory(db)


@pytest_asyncio.fixture
async def world(db: AsyncConnection) -> dict:
    shop_id = (
        await db.execute(
            text(
                "INSERT INTO shops (name, working_hours, group_chat_id) "
                "VALUES ('S', CAST(:wh AS jsonb), :g) RETURNING id"
            ),
            {"wh": json.dumps(DEFAULT_WORKING_HOURS), "g": GROUP_ID},
        )
    ).scalar_one()
    customer_id = (
        await db.execute(
            text(
                "INSERT INTO customers (shop_id, telegram_user_id) VALUES (:s, 6101) RETURNING id"
            ),
            {"s": shop_id},
        )
    ).scalar_one()
    recipient_id = (
        await db.execute(
            text(
                "INSERT INTO recipients (shop_id, customer_id, label, type) "
                "VALUES (:s, :c, 'Onam', 'mother') RETURNING id"
            ),
            {"s": shop_id, "c": customer_id},
        )
    ).scalar_one()
    return {"shop_id": shop_id, "customer_id": customer_id, "recipient_id": recipient_id}


async def add_due_row(db: AsyncConnection, world: dict, *, merge_key: str) -> int:
    """One materialised reminder, due a minute ago. Returns the occasion id."""
    occasion_id = (
        await db.execute(
            text(
                "INSERT INTO occasions "
                "(shop_id, customer_id, recipient_id, label, type, kind, month, day) "
                "VALUES (:s, :c, :r, 'Onam', 'mother', 'birthday', 3, 8) RETURNING id"
            ),
            {"s": world["shop_id"], "c": world["customer_id"], "r": world["recipient_id"]},
        )
    ).scalar_one()
    await db.execute(
        text(
            "INSERT INTO scheduled_notifications "
            "(shop_id, customer_id, occasion_id, occurrence_year, offset_days, "
            " due_at_utc, channel, merge_key) "
            "VALUES (:s, :c, :o, 2027, 0, :due, 'telegram', :mk)"
        ),
        {
            "s": world["shop_id"],
            "c": world["customer_id"],
            "o": occasion_id,
            "due": NOW - timedelta(minutes=1),
            "mk": merge_key,
        },
    )
    return int(occasion_id)


async def reminder_states(db: AsyncConnection) -> list[str]:
    result = await db.execute(text("SELECT state FROM scheduled_notifications ORDER BY id"))
    return list(result.scalars())


async def tick(
    sessions: async_sessionmaker[AsyncSession], transport: FakeTransport, *, now: datetime = NOW
):  # type: ignore[no-untyped-def]
    async with sessions() as session:
        result = await run_tick(
            session,
            transport=transport,  # type: ignore[arg-type]
            render=render_reminder,
            now_utc=now,
        )
        await session.commit()
    return result


async def add_order(
    db: AsyncConnection, world: dict, *, product_id: int | None = None, name: str = "As sold"
) -> int:
    """A placed order with its announcement ping due. Returns the order id."""
    order_id = (
        await db.execute(
            text(
                "INSERT INTO orders (shop_id, customer_id, product_id, product_name_snapshot, "
                " price_uzs_snapshot, telegram_file_id_snapshot, delivery_date, delivery_hour, "
                " delivery_location_text, landmark, recipient_name, status, submit_token) "
                "VALUES (:s, :c, :p, :n, 450000, 'file-snap', :d, '14:00', 'Chilonzor 5', "
                " 'Kok eshik', 'Dilnoza', 'placed', 'churn-tok') RETURNING id"
            ),
            {
                "s": world["shop_id"],
                "c": world["customer_id"],
                "p": product_id,
                "n": name,
                "d": date(2027, 3, 9),
            },
        )
    ).scalar_one()
    await db.execute(
        text(
            "INSERT INTO order_reminders (shop_id, order_id, ping_number, due_at_utc) "
            "VALUES (:s, :o, :n, :due)"
        ),
        {
            "s": world["shop_id"],
            "o": order_id,
            "n": ANNOUNCEMENT,
            "due": NOW - timedelta(minutes=1),
        },
    )
    return int(order_id)


async def ping_tick(sessions: async_sessionmaker[AsyncSession], transport: FakeTransport) -> None:
    async with sessions() as session:
        await run_order_ping_tick(session, transport=transport, now_utc=NOW)  # type: ignore[arg-type]
        await session.commit()


# --------------------------------------------------------------------------
# CHAIN B -- a person or date deleted while a reminder for it is already due
# --------------------------------------------------------------------------


async def test_deleting_a_person_stops_a_reminder_already_due_today(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """DEFECT IF THIS FAILS.

    The customer removes someone from their list at 10:00. A reminder about
    that person was materialised last night and is due at 11:00. It must not
    arrive: the customer has just told the bot this person no longer matters to
    them, and the next message from the bot is about exactly that person.
    """
    await add_due_row(db, world, merge_key="churn-person")
    async with sessions() as session:
        label = await deactivate_recipient(
            session,
            shop_id=world["shop_id"],
            customer_id=world["customer_id"],
            recipient_id=world["recipient_id"],
        )
        await session.commit()
    assert label is not None, "precondition: the person was deactivated"

    transport = FakeTransport()
    await tick(sessions, transport)

    assert transport.calls == [], (
        "a reminder was sent about a person the customer had already deleted"
    )


async def test_deleting_one_date_stops_its_reminder_already_due_today(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """DEFECT IF THIS FAILS. The same chain for a single date rather than the
    whole person -- a separate service function, so a separate proof."""
    occasion_id = await add_due_row(db, world, merge_key="churn-date")
    async with sessions() as session:
        label = await deactivate_occasion(
            session,
            shop_id=world["shop_id"],
            customer_id=world["customer_id"],
            occasion_id=occasion_id,
        )
        await session.commit()
    assert label is not None, "precondition: the date was deactivated"

    transport = FakeTransport()
    await tick(sessions, transport)

    assert transport.calls == [], "a reminder was sent for a date the customer had already deleted"


async def test_the_nightly_reconcile_prunes_a_deleted_persons_pending_reminder(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """CLEAN IF THIS PASSES -- and it frames the two tests above.

    CP5's reconciliation is not missing; `_prune_inactive` does delete a pending
    reminder whose person was deactivated. The question the brief asked is
    whether it fires for THIS path, and the answer is: only when
    `materialize-nightly` runs at 03:00. Deactivation is raw SQL here so that
    this tests the predicate, not whatever the service does.
    """
    await add_due_row(db, world, merge_key="churn-prune")
    await db.execute(
        text("UPDATE recipients SET active = false WHERE id = :r"), {"r": world["recipient_id"]}
    )
    await db.execute(
        text("UPDATE occasions SET active = false WHERE recipient_id = :r"),
        {"r": world["recipient_id"]},
    )

    async with sessions() as session:
        result = await materialize_shop(session, shop_id=world["shop_id"], now_utc=NOW)
        await session.commit()

    assert result.pruned_inactive == 1
    assert await reminder_states(db) == []


async def test_deleting_a_person_also_stops_a_reminder_that_already_failed_once(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """DEFECT IF THIS FAILS. The fix's state filter, proven against FAILED.

    The two tests above use PENDING rows, so they would stay green if the
    deactivation helper filtered on PENDING alone. Since the reminder-loss fix a
    FAILED row is still a schedule -- it will be retried in a minute -- so
    deleting the person must remove it too, or the retry reaches them anyway.
    """
    await add_due_row(db, world, merge_key="churn-person-failed")
    await tick(sessions, FakeTransport(SendResult.failed("connection reset")))
    assert await reminder_states(db) == ["failed"], "precondition: the first attempt failed"

    async with sessions() as session:
        await deactivate_recipient(
            session,
            shop_id=world["shop_id"],
            customer_id=world["customer_id"],
            recipient_id=world["recipient_id"],
        )
        await session.commit()

    retry = FakeTransport()
    await tick(sessions, retry, now=NOW + RETRY_BACKOFF)
    assert retry.calls == [], "a failed reminder for a deleted person was retried"
    assert await reminder_states(db) == []


async def test_deleting_a_person_keeps_the_reminders_they_already_received(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """CLEAN IF THIS PASSES -- the guard on the fix going too far.

    A reminder the customer actually received is HISTORY, not a schedule.
    Deleting it when they later remove the person would erase a fact about what
    the bot sent, which is the ledger this project refuses to rewrite.
    """
    await add_due_row(db, world, merge_key="churn-history")
    await tick(sessions, FakeTransport())
    assert await reminder_states(db) == ["sent"], "precondition: the reminder was delivered"

    async with sessions() as session:
        await deactivate_recipient(
            session,
            shop_id=world["shop_id"],
            customer_id=world["customer_id"],
            recipient_id=world["recipient_id"],
        )
        await session.commit()

    assert await reminder_states(db) == ["sent"], "deleting a person erased a delivered reminder"


# --------------------------------------------------------------------------
# REGRESSIONS from the reminder-loss fix -- FAILED became sendable, and two
# filters written when "live" meant only PENDING were never told
# --------------------------------------------------------------------------


async def test_a_customer_who_blocks_after_a_failed_attempt_is_cancelled_not_parked(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """DEFECT IF THIS FAILS, and one introduced by this audit's own fix.

    Attempt one fails on the network, so the row is FAILED. Attempt two earns a
    403. `block_customer` cancels the customer's PENDING rows -- written when
    PENDING was the only live state -- so the FAILED row survives. Its claim is
    resolved CANCELLED and cannot be retaken, so every later tick skips it while
    `attempts` climbs, until it parks in dead_letter and the shop is told that
    sending FAILED, for a customer who simply blocked the bot.
    """
    await add_due_row(db, world, merge_key="churn-block")
    await tick(sessions, FakeTransport(SendResult.failed("connection reset")))
    assert await reminder_states(db) == ["failed"], "precondition: the first attempt failed"

    await tick(sessions, FakeTransport(SendResult.forbidden()), now=NOW + RETRY_BACKOFF)
    assert await reminder_states(db) == ["cancelled"], (
        "a blocked customer's failed reminder was not cancelled"
    )

    now = NOW + RETRY_BACKOFF
    for _ in range(MAX_SEND_ATTEMPTS + 1):
        now += RETRY_BACKOFF
        later = FakeTransport()
        await tick(sessions, later, now=now)
        assert later.calls == [], "a blocked customer was messaged again"

    async with sessions() as session:
        health = await read_health(session, shop_id=world["shop_id"], now_utc=now)
    assert health.parked_reminders == 0, "a block was reported to the shop as a sending failure"
    assert health.overdue_reminders == 0


async def test_the_nightly_reconcile_prunes_a_failed_reminder_for_a_deleted_person(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """DEFECT IF THIS FAILS, also introduced by the reminder-loss fix.

    `RECONCILABLE_STATES` is documented as "anything else is HISTORY, not a
    schedule". Since the fix a FAILED row is a schedule -- it will be retried --
    but the tuple still says PENDING only, so the nightly prune walks past it and
    the reminder about a deleted person is retried anyway.
    """
    await add_due_row(db, world, merge_key="churn-failed-prune")
    await tick(sessions, FakeTransport(SendResult.failed("connection reset")))
    assert await reminder_states(db) == ["failed"], "precondition: the first attempt failed"

    await db.execute(
        text("UPDATE recipients SET active = false WHERE id = :r"), {"r": world["recipient_id"]}
    )
    await db.execute(
        text("UPDATE occasions SET active = false WHERE recipient_id = :r"),
        {"r": world["recipient_id"]},
    )
    async with sessions() as session:
        await materialize_shop(session, shop_id=world["shop_id"], now_utc=NOW)
        await session.commit()

    assert await reminder_states(db) == [], (
        "a failed reminder for a deleted person survived reconciliation and will be retried"
    )


# --------------------------------------------------------------------------
# CHAIN C -- a customer blocks the bot while the shop has pings for their order
# --------------------------------------------------------------------------


async def test_a_customer_blocking_the_bot_does_not_silence_the_shops_order_pings(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """CLEAN IF THIS PASSES.

    A 403 is the customer refusing messages from the bot. The pings about their
    order go to the SHOP's group, and the shop still has flowers to deliver, so
    the block must not reach them. `block_customer` touches `customers` and
    `scheduled_notifications`; this proves it touches nothing else.
    """
    await add_due_row(db, world, merge_key="churn-order-block")
    order_id = await add_order(db, world)

    await tick(sessions, FakeTransport(SendResult.forbidden()))
    status = (
        await db.execute(
            text("SELECT status FROM customers WHERE id = :c"), {"c": world["customer_id"]}
        )
    ).scalar_one()
    assert status == "blocked", "precondition: the customer is blocked"

    pings = FakeTransport()
    await ping_tick(sessions, pings)

    assert [c["chat_id"] for c in pings.calls] == [GROUP_ID], (
        "the shop was not told about the order"
    )
    state = (
        await db.execute(
            text("SELECT state FROM order_reminders WHERE order_id = :o"), {"o": order_id}
        )
    ).scalar_one()
    assert state == "sent"


# --------------------------------------------------------------------------
# CHAIN D -- a person renamed between materialisation and send
# --------------------------------------------------------------------------


async def test_a_rename_after_materialising_is_what_the_reminder_says(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """CLEAN IF THIS PASSES.

    The row was materialised last night under the old name. The customer
    renamed the person this morning. The reminder must use today's name, which
    it can only do if the label is read at SEND time rather than frozen into the
    row -- `_load_group_context` loads recipients fresh on every tick and
    `render.py` prefers the recipient's label over the occasion's copy.
    """
    await add_due_row(db, world, merge_key="churn-rename")
    async with sessions() as session:
        renamed = await rename_recipient(
            session,
            shop_id=world["shop_id"],
            customer_id=world["customer_id"],
            recipient_id=world["recipient_id"],
            label="Zulfiya opa",
            type_="custom",
        )
        await session.commit()
    assert renamed == "Zulfiya opa", "precondition: the rename happened"

    transport = FakeTransport()
    await tick(sessions, transport)

    assert len(transport.calls) == 1
    assert "Zulfiya opa" in transport.calls[0]["text"], (
        f"the reminder used a stale name: {transport.calls[0]['text']!r}"
    )


# --------------------------------------------------------------------------
# CHAIN A -- the product under a pending order is withdrawn
# --------------------------------------------------------------------------


@pytest.mark.parametrize("withdrawal", ["soft", "hard"])
async def test_a_withdrawn_product_leaves_the_order_and_its_card_intact(
    db: AsyncConnection,
    world: dict,
    sessions: async_sessionmaker[AsyncSession],
    withdrawal: str,
) -> None:
    """CLEAN IF THIS PASSES, both ways a product can go.

    SOFT is the shop editing the hashtag off a live post: `deleted_at`, row
    kept. HARD is `_drop_untagged` on a row an album arrival re-opened by
    nulling `finalized_at` -- a real DELETE. The composite FK is
    `ON DELETE SET NULL (product_id)`, deliberately the column-list form so
    `shop_id` survives, and `load_card` reads only the snapshot columns. So the
    order must survive, keep its shop, and the shop's card must still say what
    the customer bought.
    """
    product_id = (
        await db.execute(
            text(
                "INSERT INTO products (shop_id, name, telegram_file_id, source, "
                " channel_chat_id, channel_message_id, price_uzs, price_confidence, "
                " caption_raw, indexed_at, finalized_at, active) "
                "VALUES (:s, 'Live name', 'live-file', 'channel', -100777, 9101, 999999, "
                " 'high', '#lola', now(), now(), true) RETURNING id"
            ),
            {"s": world["shop_id"]},
        )
    ).scalar_one()
    order_id = await add_order(db, world, product_id=product_id, name="As sold")

    if withdrawal == "hard":
        await db.execute(text("DELETE FROM products WHERE id = :p"), {"p": product_id})
    else:
        await db.execute(
            text("UPDATE products SET deleted_at = now(), active = false WHERE id = :p"),
            {"p": product_id},
        )

    row = (
        await db.execute(
            text("SELECT shop_id, product_id FROM orders WHERE id = :o"), {"o": order_id}
        )
    ).one()
    assert row.shop_id == world["shop_id"], "the order lost its shop"
    expected_link = None if withdrawal == "hard" else product_id
    assert row.product_id == expected_link

    pings = FakeTransport()
    await ping_tick(sessions, pings)

    assert len(pings.calls) == 1, "the shop's card was not sent"
    assert "As sold" in pings.calls[0]["text"], "the card lost the snapshot"
    assert "Live name" not in pings.calls[0]["text"], "the card read the live product"
