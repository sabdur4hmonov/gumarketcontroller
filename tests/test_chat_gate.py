"""The bot answers in private chats. Nowhere else.

Found in production reading, not by a test: the bot sits in the shop's admin
group so it can post order cards, and it was also ANSWERING there. `/start`
returned the language picker into the group, anything else it received got the
"choose a button" fallback with a customer keyboard attached, and the admin who
typed it was quietly registered as a customer of the shop.

Telegram's privacy mode hid most of it. While privacy mode is on, a bot in a
group receives only commands, replies to itself and mentions -- but `/start` is
a command, so that half was always visible, and PROMOTING THE BOT TO GROUP
ADMIN turns privacy mode off and exposes the rest. Being an admin of your own
group is an ordinary thing to do, so correctness here cannot rest on a Telegram
setting staying where it is.

The gate is an allow list, so these tests check both halves: what must be
ignored, and what must still get through. A gate that ignored everything would
pass the first half perfectly.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import (
    RecordingSession,
    bound_session_factory,
    channel_post_update,
    make_bot,
)

from gulbot.bot.callbacks import (
    BrowsePickCB,
    OrderAdminCB,
    OrderConfirmCB,
    OrderStartCB,
)
from gulbot.bot.factory import build_dispatcher
from gulbot.bot.middlewares import (
    ADMIN_CALLBACK_PREFIX,
    SERVED_CHAT_TYPES,
    ChatGateMiddleware,
)
from gulbot.bot.states import AdminOrder
from gulbot.i18n.catalog import CATALOG
from gulbot.models.shop import DEFAULT_WORKING_HOURS

pytestmark = pytest.mark.infra

GROUP_ID = -1003901602095
ADMIN_ID = 777_001


def message_from(chat_type: str, body: str, *, chat_id: int, update_id: int = 1) -> Update:
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=datetime.now(tz=UTC),
            chat=Chat(id=chat_id, type=chat_type, title="Shop admins"),
            from_user=User(id=ADMIN_ID, is_bot=False, first_name="Admin"),
            text=body,
        ),
    )


class Harness:
    def __init__(self, dispatcher, bot, recorder: RecordingSession, db, shop) -> None:  # type: ignore[no-untyped-def]
        self.dispatcher, self.bot, self.recorder = dispatcher, bot, recorder
        self.db, self.shop = db, shop

    async def feed(self, update: Update) -> list[str]:
        self.recorder.calls.clear()
        await self.dispatcher.feed_update(self.bot, update)
        return self.recorder.sent_texts

    async def customers(self) -> list[int]:
        rows = await self.db.execute(
            text("SELECT telegram_user_id FROM customers WHERE shop_id = :s"), {"s": self.shop}
        )
        return list(rows.scalars())


@pytest_asyncio.fixture
async def harness(db: AsyncConnection) -> Harness:
    shop = (
        await db.execute(
            text(
                "INSERT INTO shops (name, working_hours) "
                "VALUES ('S', CAST(:wh AS jsonb)) RETURNING id"
            ),
            {"wh": json.dumps(DEFAULT_WORKING_HOURS)},
        )
    ).scalar_one()
    bot, recorder = make_bot()
    dispatcher = build_dispatcher(
        session_factory=bound_session_factory(db),
        shop_id=shop,
        storage=MemoryStorage(),
        schedule_finalize=lambda **kwargs: None,
    )
    return Harness(dispatcher, bot, recorder, db, shop)


# --- what must be ignored --------------------------------------------------


@pytest.mark.parametrize("chat_type", ["group", "supergroup"])
async def test_start_in_a_group_is_ignored(harness: Harness, chat_type: str) -> None:
    """THE reported bug. The language picker was being posted into the shop's
    own admin group."""
    replies = await harness.feed(message_from(chat_type, "/start", chat_id=GROUP_ID))
    assert replies == []
    assert CATALOG["start.choose_language"]["uz"] not in replies


@pytest.mark.parametrize("chat_type", ["group", "supergroup"])
async def test_ordinary_group_chatter_gets_no_fallback(harness: Harness, chat_type: str) -> None:
    """The half privacy mode was hiding. Promote the bot to group admin and it
    receives every message; without the gate it answers every one of them."""
    replies = await harness.feed(
        message_from(chat_type, "Buyurtmani tayyorladim", chat_id=GROUP_ID)
    )
    assert replies == []
    assert CATALOG["common.unknown"]["uz"] not in replies


async def test_a_group_message_creates_no_customer(harness: Harness) -> None:
    """Quieter than the visible replies and arguably worse: the admin who typed
    it became a customer of the shop, and would go on to receive reminders."""
    await harness.feed(message_from("supergroup", "salom", chat_id=GROUP_ID))
    assert await harness.customers() == []


async def test_a_button_label_in_a_group_is_ignored(harness: Harness) -> None:
    """The reply keyboard the bot used to attach made these easy to tap by
    accident, so the labels themselves must be inert there too."""
    label = CATALOG["btn.menu.occasions"]["uz"]
    assert await harness.feed(message_from("supergroup", label, chat_id=GROUP_ID)) == []


# --- what must still get through -------------------------------------------


async def test_a_private_message_is_still_served(harness: Harness) -> None:
    """Guards the guard. A gate that dropped everything would pass every test
    above and ship a bot that does nothing at all."""
    replies = await harness.feed(message_from("private", "/start", chat_id=ADMIN_ID))
    assert CATALOG["start.choose_language"]["uz"] in replies


async def test_a_private_message_still_creates_the_customer(harness: Harness) -> None:
    await harness.feed(message_from("private", "/start", chat_id=ADMIN_ID))
    assert await harness.customers() == [ADMIN_ID]


async def test_the_catalogue_channel_is_still_indexed(harness: Harness) -> None:
    """The channel is not a private chat either, so it has to be allowed
    explicitly -- and it is the one thing whose breakage would be silent: the
    catalogue would simply stay empty, with no error anywhere."""
    await harness.feed(
        channel_post_update(message_id=9001, caption="#atirgul 450 000 so'm", file_id="gate-file-1")
    )
    count = (
        await harness.db.execute(
            text("SELECT count(*) FROM products WHERE shop_id = :s"), {"s": harness.shop}
        )
    ).scalar_one()
    assert count == 1, "the indexer stopped receiving channel posts"


# --- the rule itself --------------------------------------------------------


def test_the_gate_is_an_allow_list_not_a_block_list() -> None:
    """A block list silently starts answering in whatever chat type Telegram
    invents next. Written down because the difference is invisible until it
    matters."""
    assert set(SERVED_CHAT_TYPES) == {"private", "channel"}


# --- CP13: the one crack, and that it stays a crack ------------------------
#
# The shop acts on its own order cards FROM that group, so the gate can no
# longer drop everything. A crack is exactly where the original bug gets back
# in, so both halves are stated as equal claims: the exception works, and
# everything outside it is still dropped.


def group_tap(data: str, *, user_id: int = ADMIN_ID, update_id: int = 1) -> Update:
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id=f"cb{update_id}",
            from_user=User(id=user_id, is_bot=False, first_name="Admin"),
            chat_instance=f"chat{update_id}",
            data=data,
            message=Message(
                message_id=update_id,
                date=datetime.now(tz=UTC),
                chat=Chat(id=GROUP_ID, type="supergroup", title="Shop admins"),
                from_user=User(id=1, is_bot=True, first_name="bot"),
                text="card",
            ),
        ),
    )


async def test_an_order_card_tap_is_let_through(harness: Harness) -> None:
    """The exception, as its own claim, so a later change to the gate cannot
    quietly close it again."""
    gate = ChatGateMiddleware()
    tap = group_tap(OrderAdminCB(action="confirm", order_id=7).pack())
    assert await gate._is_shop_action(tap, {}) is True


async def test_a_customer_callback_from_a_group_is_still_dropped(harness: Harness) -> None:
    """NOT "any callback from a group". A customer-facing button forwarded into
    the group would otherwise be answered there -- the same class of bug the
    gate exists to close, arriving through the hole opened for the shop."""
    gate = ChatGateMiddleware()
    for payload in (
        OrderStartCB(product_id=1).pack(),
        BrowsePickCB(product_id=1).pack(),
        OrderConfirmCB(action="submit").pack(),
    ):
        assert await gate._is_shop_action(group_tap(payload), {}) is False, payload


def test_the_gate_and_the_callback_factory_agree_on_the_prefix() -> None:
    """The gate matches on a string constant. If the factory's prefix changed,
    the buttons would stop working SILENTLY rather than failing loudly, so the
    two are pinned together."""
    assert OrderAdminCB(action="confirm", order_id=1).pack().startswith(f"{ADMIN_CALLBACK_PREFIX}:")


async def test_a_rejection_reason_is_let_through(harness: Harness) -> None:
    """Gated on the TYPIST's own FSM state, not on the chat's."""
    gate = ChatGateMiddleware()
    context = harness.dispatcher.fsm.get_context(harness.bot, GROUP_ID, ADMIN_ID)
    await context.set_state(AdminOrder.entering_reject_reason)
    reason = message_from("supergroup", "gul tugadi", chat_id=GROUP_ID)
    assert await gate._is_shop_action(reason, {"state": context}) is True


async def test_a_group_message_with_no_reason_pending_is_refused(harness: Harness) -> None:
    """Guards the guard. Without the state check the exception would read "any
    message from a group", which is the original bug verbatim."""
    gate = ChatGateMiddleware()
    context = harness.dispatcher.fsm.get_context(harness.bot, GROUP_ID, ADMIN_ID)
    chatter = message_from("supergroup", "salom", chat_id=GROUP_ID)
    assert await gate._is_shop_action(chatter, {"state": context}) is False


async def test_one_admin_typing_does_not_open_the_gate_for_another(harness: Harness) -> None:
    """WHY THE FSM STRATEGY CHANGED. aiogram's default keys state by CHAT, so in
    a group every admin would share one state: one of them tapping Reject would
    put the whole group into "waiting for a reason", and the next person's
    message would be swallowed as it.

    USER_IN_CHAT keys by (chat, user) instead. In a private chat the two are
    identical -- chat_id IS the user id -- so no customer conversation changed.
    """
    gate = ChatGateMiddleware()
    rejecting = harness.dispatcher.fsm.get_context(harness.bot, GROUP_ID, ADMIN_ID)
    await rejecting.set_state(AdminOrder.entering_reject_reason)

    bystander = harness.dispatcher.fsm.get_context(harness.bot, GROUP_ID, ADMIN_ID + 1)
    assert await bystander.get_state() is None, "state leaked between admins"

    chatter = message_from("supergroup", "boshqa gap", chat_id=GROUP_ID)
    assert await gate._is_shop_action(chatter, {"state": bystander}) is False


async def test_start_in_a_group_is_still_ignored_after_the_crack(harness: Harness) -> None:
    """The original bug, re-asserted AFTER the exception exists. This is the
    test that would catch a gate loosened one step too far."""
    assert await harness.feed(message_from("supergroup", "/start", chat_id=GROUP_ID)) == []
    assert await harness.customers() == []
