"""The shop acting on its own order card, in its own group.

CP13's moving parts are spread across three files that must agree with each
other, and each disagreement fails silently rather than loudly:

  * the callback PREFIX in `bot/callbacks.py` and the copy of it the chat gate
    compares against. If they drift, the buttons stop working -- the gate drops
    the tap before any handler sees it, so there is no error anywhere, just a
    button that does nothing.
  * the FSM state the gate lets a typed rejection reason through on. If that
    drifts, the admin types a reason into the group and the bot ignores it.

Neither is the kind of bug a test of the happy path would catch, because both
look exactly like "nothing happened".

The second half of this module drives the REAL dispatcher. That matters more
here than anywhere else in the project, because the two things most likely to
break this flow are both middlewares: the chat gate that has to let the tap
through, and the customer middleware that must not turn the admin who tapped
into a customer of the shop.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import RecordingSession, bound_session_factory, make_bot

from gulbot.bot.callbacks import OrderAdminCB
from gulbot.bot.factory import build_dispatcher
from gulbot.bot.middlewares import ADMIN_CALLBACK_PREFIX
from gulbot.bot.states import AdminOrder
from gulbot.i18n.catalog import CATALOG
from gulbot.models.shop import DEFAULT_WORKING_HOURS

GROUP_ID = -1003901602095
ADMIN_ID = 777_001
CUSTOMER_TG = 991_001


# --------------------------------------------------------------------------
# the pieces that must agree
# --------------------------------------------------------------------------


def test_the_gate_and_the_buttons_agree_on_the_prefix() -> None:
    """The one string a group is allowed to send.

    Compared against the factory's OWN prefix rather than a second literal,
    so renaming the factory fails the build instead of quietly disarming the
    buttons.
    """
    assert OrderAdminCB.__prefix__ == ADMIN_CALLBACK_PREFIX


def test_every_button_the_card_carries_passes_the_gate() -> None:
    """Not just the prefix in the abstract -- the actual packed payloads."""
    for payload in OrderAdminCB.samples():
        assert payload.startswith(f"{ADMIN_CALLBACK_PREFIX}:"), payload


def test_the_card_offers_exactly_confirm_and_reject() -> None:
    """Two on the CARD. A third decision there would be a status transition
    nobody reviewed."""
    on_card = {a.action for a in map(OrderAdminCB.unpack, OrderAdminCB.samples())} - {"abort"}
    assert on_card == {"confirm", "reject"}


def test_the_factory_also_carries_the_way_out_of_a_rejection() -> None:
    """`abort` is on the PROMPT, not the card: it withdraws a Reject that was
    never finalised.

    It exists as a button rather than a typed "Bekor qilish" because nav owns
    that label in every state and nav replies with a customer keyboard, which
    must never be posted into the shop's group.
    """
    actions = {OrderAdminCB.unpack(p).action for p in OrderAdminCB.samples()}
    assert actions == {"confirm", "reject", "abort"}


def test_the_reject_reason_state_exists_for_the_gate_to_name() -> None:
    """The gate imports this state to decide whether a group MESSAGE gets
    through. Renaming it there and not here would reopen the group bug for
    text, which is the half that privacy mode used to hide."""
    assert AdminOrder.entering_reject_reason.state == "AdminOrder:entering_reject_reason"


# --------------------------------------------------------------------------
# the flow, through the real dispatcher
# --------------------------------------------------------------------------


class Shop:
    def __init__(self, dispatcher, bot, recorder: RecordingSession, db, shop, order, customer):  # type: ignore[no-untyped-def]
        self.dispatcher, self.bot, self.recorder = dispatcher, bot, recorder
        self.db, self.shop, self.order, self.customer = db, shop, order, customer

    async def feed(self, update: Update) -> list[str]:
        self.recorder.calls.clear()
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

    async def customers(self) -> list[int]:
        rows = await self.db.execute(
            text("SELECT telegram_user_id FROM customers WHERE shop_id = :s"), {"s": self.shop}
        )
        return list(rows.scalars())


def tap(action: str, order_id: int, *, chat_id: int = GROUP_ID, update_id: int = 1) -> Update:
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id=f"cb{update_id}",
            from_user=User(id=ADMIN_ID, is_bot=False, first_name="Admin"),
            chat_instance=f"chat{update_id}",
            data=OrderAdminCB(action=action, order_id=order_id).pack(),
            message=Message(
                message_id=500 + update_id,
                date=datetime.now(tz=UTC),
                chat=Chat(id=chat_id, type="supergroup", title="Shop admins"),
                from_user=User(id=1, is_bot=True, first_name="bot"),
                text="Yangi buyurtma",
            ),
        ),
    )


def typed(body: str, *, chat_id: int = GROUP_ID, update_id: int = 2) -> Update:
    return Update(
        update_id=update_id,
        message=Message(
            message_id=600 + update_id,
            date=datetime.now(tz=UTC),
            chat=Chat(id=chat_id, type="supergroup", title="Shop admins"),
            from_user=User(id=ADMIN_ID, is_bot=False, first_name="Admin"),
            text=body,
        ),
    )


@pytest_asyncio.fixture
async def shop(db: AsyncConnection) -> Shop:
    shop_id = (
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
            {"s": shop_id, "t": CUSTOMER_TG},
        )
    ).scalar_one()
    order = (
        await db.execute(
            text(
                "INSERT INTO orders (shop_id, customer_id, product_name_snapshot, "
                " price_uzs_snapshot, telegram_file_id_snapshot, delivery_date, "
                " delivery_hour, delivery_location_text, landmark, status, submit_token) "
                "VALUES (:s, :c, 'Oq atirgul', 450000, 'f', :d, '14:00', 'Chilonzor', "
                " 'eshik', 'placed', 'admin-tok') RETURNING id"
            ),
            {"s": shop_id, "c": customer, "d": date(2027, 3, 8)},
        )
    ).scalar_one()
    bot, recorder = make_bot()
    dispatcher = build_dispatcher(
        session_factory=bound_session_factory(db),
        shop_id=shop_id,
        storage=MemoryStorage(),
        schedule_finalize=lambda **kwargs: None,
    )
    return Shop(dispatcher, bot, recorder, db, shop_id, order, customer)


@pytest.mark.infra
async def test_tapping_confirm_confirms_the_order(shop: Shop) -> None:
    await shop.feed(tap("confirm", shop.order))
    assert await shop.status() == "confirmed"


@pytest.mark.infra
async def test_tapping_confirm_tells_the_customer(shop: Shop) -> None:
    """The reason this checkpoint was pulled forward: without this the order
    sits unconfirmed and the customer assumes it was accepted."""
    replies = await shop.feed(tap("confirm", shop.order))
    assert CATALOG["order.status.confirmed"]["uz"].format(id=shop.order) in replies


@pytest.mark.infra
async def test_the_admin_who_taps_does_not_become_a_customer(shop: Shop) -> None:
    """THE regression this router could reintroduce. CP10c's gate stopped an
    admin being registered as a customer by dropping every group update before
    the customer middleware ran; CP13 punches a hole in that gate, and the tap
    goes straight back through the same middleware.

    Silent if it breaks: no error, just a shop slowly acquiring its own staff
    as customers and eventually reminding them.
    """
    await shop.feed(tap("confirm", shop.order))
    assert await shop.customers() == [CUSTOMER_TG]


@pytest.mark.infra
async def test_tapping_reject_writes_nothing_until_the_reason_arrives(shop: Shop) -> None:
    """An admin who taps Reject and changes their mind has changed nothing --
    and a customer is never told "rejected" with no explanation, which is the
    silence this checkpoint exists to remove."""
    await shop.feed(tap("reject", shop.order))
    assert await shop.status() == "placed"


@pytest.mark.infra
async def test_the_reason_prompt_names_the_order(shop: Shop) -> None:
    """Several admins can see the group. Two rejections in flight would
    otherwise be two identical prompts."""
    replies = await shop.feed(tap("reject", shop.order))
    assert CATALOG["group.reason_prompt"]["uz"].format(id=shop.order) in replies


@pytest.mark.infra
async def test_the_typed_reason_finalises_the_rejection(shop: Shop) -> None:
    await shop.feed(tap("reject", shop.order))
    await shop.feed(typed("gul tugadi"))

    row = (
        await shop.db.execute(
            text("SELECT status, rejection_reason FROM orders WHERE id = :o"), {"o": shop.order}
        )
    ).one()
    assert row.status == "rejected"
    assert row.rejection_reason == "gul tugadi"


@pytest.mark.infra
async def test_the_customer_is_told_why(shop: Shop) -> None:
    await shop.feed(tap("reject", shop.order))
    replies = await shop.feed(typed("gul tugadi"))
    assert any("gul tugadi" in reply for reply in replies)


@pytest.mark.infra
async def test_group_chatter_with_no_rejection_pending_is_still_ignored(shop: Shop) -> None:
    """The original CP10c bug, re-asserted against the router that opened the
    crack. Nothing is pending, so this is ordinary group conversation."""
    assert await shop.feed(typed("bugun kech qaytaman")) == []
    assert await shop.status() == "placed"


@pytest.mark.infra
async def test_a_tap_from_a_chat_that_is_not_the_shops_does_nothing(shop: Shop) -> None:
    """Defence in depth behind the gate. The card only ever goes to the chats
    `ping_targets` chose, and those are the only chats it may be acted on from
    -- so the bot sitting in some other group cannot drive this shop's orders.
    """
    await shop.feed(tap("confirm", shop.order, chat_id=-100_777_777))
    assert await shop.status() == "placed"


@pytest.mark.infra
async def test_a_second_tap_on_an_answered_card_changes_nothing(shop: Shop) -> None:
    """A card sits in the group indefinitely and its buttons stay live. The
    second admin is told it was already handled, not shown an error."""
    await shop.feed(tap("confirm", shop.order, update_id=1))
    await shop.feed(tap("reject", shop.order, update_id=2))
    assert await shop.status() == "confirmed"


@pytest.mark.infra
async def test_the_prompt_offers_a_way_out(shop: Shop) -> None:
    """A Reject tapped by accident has to be withdrawable, and Cancel cannot be
    the typed word -- nav owns that label and answers with a customer keyboard.
    So the prompt carries a button."""
    await shop.feed(tap("reject", shop.order))
    markups = [c.reply_markup for c in shop.recorder.calls if getattr(c, "reply_markup", None)]
    actions = [
        OrderAdminCB.unpack(b.callback_data).action
        for markup in markups
        for row in markup.inline_keyboard
        for b in row
    ]
    assert "abort" in actions


@pytest.mark.infra
async def test_aborting_a_rejection_leaves_the_order_untouched(shop: Shop) -> None:
    """Nothing was written when the prompt went up, so nothing has to be
    undone. The order is still placed and the card still has both buttons."""
    await shop.feed(tap("reject", shop.order))
    await shop.feed(tap("abort", shop.order, update_id=3))
    assert await shop.status() == "placed"


@pytest.mark.infra
async def test_after_aborting_the_next_message_is_group_chatter_again(shop: Shop) -> None:
    """THE point of the abort. While the prompt is open the gate lets this
    admin's messages through; if abort did not clear the state, the next thing
    they said in the group would silently become a rejection reason."""
    await shop.feed(tap("reject", shop.order))
    await shop.feed(tap("abort", shop.order, update_id=3))
    assert await shop.feed(typed("mayli, davom etamiz")) == []
    assert await shop.status() == "placed"


@pytest.mark.infra
async def test_a_reject_can_still_be_finished_after_a_different_order_was_aborted(
    shop: Shop,
) -> None:
    """Guards the guard: abort must not disarm the flow generally."""
    await shop.feed(tap("reject", shop.order))
    await shop.feed(tap("abort", shop.order, update_id=3))
    await shop.feed(tap("reject", shop.order, update_id=4))
    await shop.feed(typed("gul tugadi", update_id=5))
    assert await shop.status() == "rejected"
