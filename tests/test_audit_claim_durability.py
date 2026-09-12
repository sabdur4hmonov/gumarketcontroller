"""PASS 1b: is every claim durable BEFORE its external call?

CP6 established the rule and `sending/dispatcher.py:453` states it:

    # The claims must outlive this worker. Everything after this point may
    # crash without causing a duplicate send.
    await session.commit()

The claim is worthless unless it is committed before Telegram is called. An
uncommitted claim plus a crash after Telegram accepted means the ledger forgets
a message the customer already has -- which is the exact window the ledger
exists to close.

THIS MODULE IS THE AUDIT'S EVIDENCE for the one path that did not follow the
rule: CP13's admin handlers. `DbSessionMiddleware` commits after the handler
returns, so the status change AND the notification claim are both still
uncommitted while the customer is being messaged.
"""

from __future__ import annotations

import json
from contextlib import suppress
from datetime import date
from typing import Any

import pytest
import pytest_asyncio
from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import EditMessageCaption, EditMessageText, TelegramMethod
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import TEST_TOKEN, RecordingSession, bound_session_factory
from tests.test_admin_orders import GROUP_ID, tap, typed

from gulbot.bot.factory import build_dispatcher
from gulbot.models.shop import DEFAULT_WORKING_HOURS

pytestmark = pytest.mark.infra

CUSTOMER_TG = 994_001


class BreakTheCardEdit(RecordingSession):
    """Everything works except stamping the card.

    The realistic trigger, not a contrived one: `_stamp_card` catches
    `TelegramBadRequest` (a message too old to edit) and nothing else, so a
    429 or a dropped connection on the edit call propagates. By then the
    customer has already been told.
    """

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,  # noqa: ASYNC109  aiogram's BaseSession contract
    ) -> Any:
        if isinstance(method, EditMessageCaption | EditMessageText):
            raise TelegramNetworkError(method=method, message="connection reset")
        return await super().make_request(bot, method, timeout)


class World:
    def __init__(self, dispatcher, bot, recorder, db, shop, order) -> None:  # type: ignore[no-untyped-def]
        self.dispatcher, self.bot, self.recorder = dispatcher, bot, recorder
        self.db, self.shop, self.order = db, shop, order

    async def feed(self, update) -> list[str]:  # type: ignore[no-untyped-def]
        self.recorder.calls.clear()
        # A real bot process logs and carries on; what matters here is the state
        # it is left in, not that aiogram propagated.
        with suppress(Exception):
            await self.dispatcher.feed_update(self.bot, update)
        return self.recorder.sent_texts

    async def status(self) -> str:
        return str(
            (
                await self.db.execute(
                    text("SELECT status FROM orders WHERE id = :o"), {"o": self.order}
                )
            ).scalar_one()
        )

    async def ledger(self) -> list[str]:
        rows = await self.db.execute(text("SELECT transition_key FROM message_log ORDER BY id"))
        return list(rows.scalars())


@pytest_asyncio.fixture
async def world(db: AsyncConnection) -> World:
    shop = (
        await db.execute(
            text(
                "INSERT INTO shops (name, working_hours, group_chat_id) "
                "VALUES ('S', CAST(:wh AS jsonb), :g) RETURNING id"
            ),
            {"wh": json.dumps(DEFAULT_WORKING_HOURS), "g": GROUP_ID},
        )
    ).scalar_one()
    customer = (
        await db.execute(
            text(
                "INSERT INTO customers (shop_id, telegram_user_id, lang) "
                "VALUES (:s, :t, 'uz') RETURNING id"
            ),
            {"s": shop, "t": CUSTOMER_TG},
        )
    ).scalar_one()
    order = (
        await db.execute(
            text(
                "INSERT INTO orders (shop_id, customer_id, product_name_snapshot, "
                " price_uzs_snapshot, telegram_file_id_snapshot, delivery_date, "
                " delivery_hour, delivery_location_text, landmark, status, submit_token) "
                "VALUES (:s, :c, 'Oq atirgul', 450000, 'f', :d, '14:00', 'Chilonzor', "
                " 'eshik', 'placed', 'audit-tok') RETURNING id"
            ),
            {"s": shop, "c": customer, "d": date(2027, 3, 8)},
        )
    ).scalar_one()

    recorder = BreakTheCardEdit()
    bot = Bot(token=TEST_TOKEN, session=recorder)
    dispatcher = build_dispatcher(
        session_factory=bound_session_factory(db),
        shop_id=shop,
        storage=MemoryStorage(),
        schedule_finalize=lambda **kwargs: None,
    )
    return World(dispatcher, bot, recorder, db, shop, order)


async def test_a_failed_card_edit_does_not_unsay_what_the_customer_was_told(
    world: World,
) -> None:
    """The customer has the message. The database must agree that they do.

    The COARSE test: the realistic end-to-end story, which any one of the three
    commits is enough to satisfy. The two tests below are the sharp ones, each
    targeting a window only its own commit covers -- written after a mutation
    sweep caught this test passing with all three commits removed one at a
    time.
    """
    replies = await world.feed(tap("confirm", world.order))
    assert any("qabul qilindi" in reply for reply in replies), (
        "precondition: the customer must have been messaged before the edit failed"
    )

    assert await world.status() == "confirmed", (
        "the customer was told the order is confirmed; the database says it is not"
    )
    assert await world.ledger() == [f"order:{world.order}:confirmed"], (
        "the ledger forgot a message the customer already has"
    )


async def test_a_retap_after_a_failed_edit_does_not_message_the_customer_twice(
    world: World,
) -> None:
    """The consequence, stated as its own claim.

    The card still carries its buttons -- the edit is what failed -- so the
    obvious thing for an admin to do is tap again. With a durable claim that
    is harmless. Without one it is a second "your order is confirmed".
    """
    await world.feed(tap("confirm", world.order, update_id=1))
    second = await world.feed(tap("confirm", world.order, update_id=2))

    told_again = [r for r in second if "qabul qilindi" in r]
    assert not told_again, f"the customer was told a second time: {told_again}"


async def test_a_crash_between_sending_and_resolving_keeps_the_ledger_row(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Telegram accepted; the resolution was never written. The RECORD must
    still say this customer was messaged.

    WHAT THIS DOES NOT CLAIM, because the mutation sweep proved it false: the
    claim is not what stops a duplicate here. The compare-and-swap is -- once
    the status is committed, a retap short-circuits on `already_handled` and
    never reaches the notifier. Asserting "no duplicate" passed with the claim
    commit removed, which is a test that proves someone else's work.

    What the claim commit uniquely delivers is the ROW: an entry saying the
    customer was told, surviving a rollback that erases everything else. That
    is the difference between "we do not know if they were messaged" and a
    ledger someone can read when a customer calls to ask.
    """
    from gulbot.services import order_notify

    async def explode(*a: object, **kw: object) -> None:
        raise RuntimeError("connection lost after Telegram accepted")

    monkeypatch.setattr(order_notify, "resolve_send", explode)

    sent = await world.feed(tap("confirm", world.order))
    assert any("qabul qilindi" in r for r in sent), "precondition: the send happened"

    assert await world.ledger() == [f"order:{world.order}:confirmed"], (
        "the crash erased the only record that this customer was messaged"
    )


async def test_a_rejection_survives_a_notifier_that_fails_before_committing(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reject path needs its own proof: it has its own commit.

    The sweep MISSED the reject commit when only the confirm path was covered,
    which is the ordinary way a second code path goes unguarded -- the first
    one's test looks like it covers both.

    A rejection lost this way is worse than a confirmation lost this way: the
    pings were cancelled in the same transaction, so a rollback re-arms
    delivery reminders for an order the shop has refused.
    """
    from gulbot.bot.routers import admin_orders

    async def explode(*a: object, **kw: object) -> None:
        raise RuntimeError("the notifier could not reach the database")

    monkeypatch.setattr(admin_orders, "notify_customer_of_outcome", explode)

    await world.feed(tap("reject", world.order, update_id=1))
    await world.feed(typed("gul tugadi", update_id=2))

    assert await world.status() == "rejected", (
        "the rejection was rolled back by an unrelated failure downstream"
    )


async def test_the_decision_survives_a_notifier_that_fails_before_committing(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shop decided. That is a fact about the world, not a side effect of
    the notification succeeding.

    `_tell_the_customer` swallows everything by design -- the group line is the
    fallback -- so a notifier that dies before its own commit leaves the
    handler to carry on to the card edit, which then fails. Without the commit
    after the compare-and-swap, the decision goes with it and the order is
    silently back to 'placed'.
    """
    from gulbot.bot.routers import admin_orders

    async def explode(*a: object, **kw: object) -> None:
        raise RuntimeError("the notifier could not reach the database")

    monkeypatch.setattr(admin_orders, "notify_customer_of_outcome", explode)

    await world.feed(tap("confirm", world.order))

    assert await world.status() == "confirmed", (
        "the shop's decision was rolled back by an unrelated failure downstream"
    )
