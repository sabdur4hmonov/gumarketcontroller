"""The crafted-callback CLASS, not two instances.

Pass 4 found that `pick_date` and `pick_hour` trusted their callback data. That
is a structural property of Telegram -- nothing server-side proves a callback's
data matches a button the bot actually sent -- so every CallbackData factory in
the project was swept. Each consumer is safe for one of four stated reasons, or
it is a defect:

  RE-DERIVED   the handler rebuilds the valid set from the source that built the
               keyboard (pick_date, pick_hour after pass 4; pick_day via
               is_valid_month_day).
  SCOPED ID    the value is an opaque id, checked against the database with the
               customer's own shop_id AND customer_id, so a guessed id finds
               nothing regardless of what was "supposed" to be sent.
  SERVICE SET  the service validates against the same preset tuple the keyboard
               is built from, and a DB CHECK backs it up.
  NOT FROM THE CALLBACK
               the value that matters lives in FSM state or is re-read from the
               database; the callback only says "next", "known", "submit".

Every claim of "safe" below is a test, because "sound by construction" was not
sufficient evidence earlier in this same audit.
"""

from __future__ import annotations

import json
from contextlib import suppress
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import bound_session_factory, make_bot

from gulbot.bot.callbacks import MonthCB, OrderStartCB, RecipientCB
from gulbot.bot.factory import build_dispatcher
from gulbot.bot.states import AddOccasion
from gulbot.models.customer import Customer
from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.services.preferences import (
    set_preferred_hashtag,
    set_reminder_count,
    set_send_time,
)
from gulbot.services.recipients import create_recipient, deactivate_recipient

pytestmark = pytest.mark.infra

ALICE_TG = 770_001
BOB_TG = 770_002


def tap(data: str, *, user_id: int, update_id: int) -> Update:
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id=f"cb{update_id}",
            from_user=User(id=user_id, is_bot=False, first_name="Mijoz"),
            chat_instance=f"chat{update_id}",
            data=data,
            message=Message(
                message_id=update_id,
                date=datetime.now(tz=UTC),
                chat=Chat(id=user_id, type="private"),
                from_user=User(id=1, is_bot=True, first_name="bot"),
                text="card",
            ),
        ),
    )


class World:
    def __init__(self, db, shop, alice, bob, alices_person, bobs_person, product):  # type: ignore[no-untyped-def]
        self.db, self.shop = db, shop
        self.alice, self.bob = alice, bob
        self.alices_person, self.bobs_person = alices_person, bobs_person
        self.product = product
        self.bot, self.recorder = make_bot()
        self.dispatcher = build_dispatcher(
            session_factory=bound_session_factory(db),
            shop_id=shop,
            storage=MemoryStorage(),
            schedule_finalize=lambda **kwargs: None,
        )

    async def feed(self, update: Update) -> list[str]:
        self.recorder.calls.clear()
        # A crafted value may make a handler raise; what matters is the state
        # it leaves behind, not whether aiogram propagated.
        with suppress(Exception):
            await self.dispatcher.feed_update(self.bot, update)
        return self.recorder.sent_texts

    def context(self, user_id: int):  # type: ignore[no-untyped-def]
        return self.dispatcher.fsm.get_context(self.bot, user_id, user_id)


async def _id(db: AsyncConnection, sql: str, params: dict) -> int:
    return int((await db.execute(text(sql), params)).scalar_one())


@pytest_asyncio.fixture
async def world(db: AsyncConnection) -> World:
    shop = await _id(
        db,
        "INSERT INTO shops (name, working_hours) VALUES ('S', CAST(:wh AS jsonb)) RETURNING id",
        {"wh": json.dumps(DEFAULT_WORKING_HOURS)},
    )
    alice = await _id(
        db,
        "INSERT INTO customers (shop_id, telegram_user_id, lang) "
        "VALUES (:s, :t, 'uz') RETURNING id",
        {"s": shop, "t": ALICE_TG},
    )
    bob = await _id(
        db,
        "INSERT INTO customers (shop_id, telegram_user_id, lang) "
        "VALUES (:s, :t, 'uz') RETURNING id",
        {"s": shop, "t": BOB_TG},
    )
    person = (
        "INSERT INTO recipients (shop_id, customer_id, label, type) "
        "VALUES (:s, :c, :l, 'custom') RETURNING id"
    )
    alices_person = await _id(db, person, {"s": shop, "c": alice, "l": "Alisaning onasi"})
    bobs_person = await _id(db, person, {"s": shop, "c": bob, "l": "Bobning singlisi"})
    product = await _id(
        db,
        "INSERT INTO products (shop_id, name, telegram_file_id, source, channel_chat_id, "
        " channel_message_id, price_uzs, price_confidence, caption_raw, indexed_at, "
        " finalized_at, active) VALUES (:s, 'Oq atirgul', 'f', 'channel', -100777, 5151, "
        " 450000, 'high', 'cap', now(), now(), true) RETURNING id",
        {"s": shop},
    )
    return World(db, shop, alice, bob, alices_person, bobs_person, product)


# --------------------------------------------------------------------------
# the defect: an id that is NOT scoped to the customer
# --------------------------------------------------------------------------


async def test_a_crafted_order_button_cannot_attach_another_customers_person(
    world: World,
) -> None:
    """DEFECT IF THIS FAILS.

    `OrderStartCB.recipient_id` rides in the callback. `start_order` stored it
    raw and `submit_order` writes it to `orders.recipient_id`, whose foreign key
    is (recipient_id, shop_id) -- scoped to the SHOP, not the customer. So Alice
    can hand-craft an order button carrying Bob's person, and her order is linked
    to someone on Bob's private list.

    The label shown to her is already safe -- `_known_recipient_label` scopes by
    customer -- so this is an integrity defect rather than a disclosure one. The
    order row would still point at a stranger's family member.
    """
    crafted = OrderStartCB(product_id=world.product, recipient_id=world.bobs_person).pack()
    await world.feed(tap(crafted, user_id=ALICE_TG, update_id=1))

    stored = (await world.context(ALICE_TG).get_data()).get("recipient_id")
    assert stored != world.bobs_person, "another customer's person was attached to the order"


async def test_a_customers_own_person_still_rides_on_the_order_button(world: World) -> None:
    """CONFIRMATION IF THIS PASSES -- guards the guard. The legitimate path, a
    reminder card's button carrying the customer's OWN person, must keep it."""
    own = OrderStartCB(product_id=world.product, recipient_id=world.alices_person).pack()
    await world.feed(tap(own, user_id=ALICE_TG, update_id=2))

    stored = (await world.context(ALICE_TG).get_data()).get("recipient_id")
    assert stored == world.alices_person


# --------------------------------------------------------------------------
# SCOPED ID -- safe because the WHERE clause includes the customer
# --------------------------------------------------------------------------


async def test_a_guessed_person_id_belonging_to_someone_else_finds_nothing(
    world: World,
) -> None:
    """CONFIRMATION IF THIS PASSES. Alice crafts a Remove button for Bob's person.
    `deactivate_recipient` filters on shop_id AND customer_id, so it matches no
    row -- the id being real is irrelevant."""
    crafted = RecipientCB(action="deactivate", recipient_id=world.bobs_person).pack()
    replies = await world.feed(tap(crafted, user_id=ALICE_TG, update_id=3))

    active = (
        await world.db.execute(
            text("SELECT active FROM recipients WHERE id = :i"), {"i": world.bobs_person}
        )
    ).scalar_one()
    assert active is True, "Alice deactivated someone on Bob's list"
    assert any("topilmadi" in r for r in replies), f"expected not-found, got {replies}"


async def test_the_scoping_is_in_the_service_not_just_the_handler(world: World) -> None:
    """Same claim at the service boundary, so a future handler that forgets to
    check cannot reintroduce it."""
    async with bound_session_factory(world.db)() as session:
        label = await deactivate_recipient(
            session, shop_id=world.shop, customer_id=world.alice, recipient_id=world.bobs_person
        )
    assert label is None


# --------------------------------------------------------------------------
# SERVICE SET -- safe because the service checks the keyboard's own tuple
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "call",
    ["flower", "reminder_count", "send_time"],
)
async def test_a_crafted_preference_value_is_refused_by_the_service(
    world: World, call: str
) -> None:
    """CONFIRMATION IF THIS PASSES. The handler passes the callback's value
    straight through, but each service validates against the SAME preset tuple
    its keyboard is built from -- FLOWER_PRESETS, (1, 2, 3), SEND_TIME_CHOICES --
    and raises before writing. A DB CHECK backs each one up besides."""
    async with bound_session_factory(world.db)() as session:
        customer = await session.get(Customer, world.alice)
        with pytest.raises(ValueError):
            if call == "flower":
                await set_preferred_hashtag(
                    session,
                    shop_id=world.shop,
                    customer_id=world.alice,
                    recipient_id=world.alices_person,
                    hashtag="<script>",
                )
            elif call == "reminder_count":
                await set_reminder_count(session, customer=customer, count=999)
            else:
                await set_send_time(session, customer=customer, slot="03:00")

    row = (
        await world.db.execute(
            text(
                "SELECT c.reminder_count, c.preferred_send_time, r.preferred_hashtag "
                "FROM customers c JOIN recipients r ON r.customer_id = c.id "
                "WHERE c.id = :c AND r.id = :r"
            ),
            {"c": world.alice, "r": world.alices_person},
        )
    ).one()
    assert tuple(row) == (None, None, None), f"a crafted preference was written: {row}"


async def test_a_crafted_person_type_is_refused_by_the_database(world: World) -> None:
    """CONFIRMATION IF THIS PASSES. `pick_type` and `rename_with_preset` store
    the callback's type unvalidated, and it reaches the service -- but the
    `type_known` CHECK refuses anything outside RecipientType. Nothing unknown
    can be persisted; a crafted client breaks only its own flow."""
    async with bound_session_factory(world.db)() as session:
        with pytest.raises(IntegrityError):
            await create_recipient(
                session,
                shop_id=world.shop,
                customer_id=world.alice,
                label="x",
                type_="not-a-type",
            )
            await session.flush()


# --------------------------------------------------------------------------
# RE-DERIVED -- safe because the day step re-validates the month
# --------------------------------------------------------------------------


@pytest.mark.parametrize("month", [0, 13])
async def test_a_crafted_month_can_never_reach_a_saved_date(world: World, month: int) -> None:
    """CONFIRMATION IF THIS PASSES. `pick_month` stores any month, but the next
    step is `pick_day`, which calls `is_valid_month_day` -- and that rejects a
    month outside 1..12 before a day is ever stored. So the flow cannot advance
    past choosing a day, and the `month_range` CHECK would refuse it regardless."""
    context = world.context(ALICE_TG)
    await context.set_state(AddOccasion.choosing_month)
    await context.update_data(
        recipient_id=world.alices_person,
        pending_label="Alisaning onasi",
        pending_type="custom",
        pending_kind="birthday",
    )
    await world.feed(tap(MonthCB(month=month).pack(), user_id=ALICE_TG, update_id=10))
    from gulbot.bot.callbacks import DayCB

    await world.feed(tap(DayCB(day=1).pack(), user_id=ALICE_TG, update_id=11))

    state = await context.get_state()
    assert state != AddOccasion.entering_year.state, f"month {month} got past the day step"
    saved = (
        await world.db.execute(
            text("SELECT count(*) FROM occasions WHERE customer_id = :c"), {"c": world.alice}
        )
    ).scalar_one()
    assert saved == 0
