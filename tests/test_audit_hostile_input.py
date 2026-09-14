# ruff: noqa: F811  -- fixtures are imported by name; pytest injects them into
# the same-named test parameters, which ruff reads as a redefinition.
"""PASS 4 of the pre-deployment audit: hostile and malformed input.

Every check here is adversarial rather than correctness-shaped: what a customer
or group member can make the bot do by sending something the UI would never
have produced. That includes callback data a modified client sends by hand --
Telegram does NOT verify that a callback's data matches a button it rendered.

Each docstring says whether a failure is a defect or a confirmation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from aiogram.methods import EditMessageCaption, EditMessageText, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from tests.test_admin_orders import (  # noqa: F401  -- `shop` is a fixture
    CUSTOMER_TG,
    Shop,
    shop,
    tap,
    typed,
)
from tests.test_audit_races import (  # noqa: F401  -- `committed` is a fixture
    _armed_dispatcher,
    committed,
)

from gulbot.bot.callbacks import OrderAdminCB, OrderDateCB, OrderHourCB
from gulbot.bot.states import AdminOrder, PlaceOrder
from gulbot.sending.order_card import ANNOUNCEMENT, OrderCard, render_card

pytestmark = pytest.mark.infra

HOSTILE = '<b>x</b> & <a href="tg://x">y</a>'
#: `utils.render.escape` uses quote=False on purpose: user text only ever
#: lands in element content, never inside an attribute, so `"` is inert.
ESCAPED = '&lt;b&gt;x&lt;/b&gt; &amp; &lt;a href="tg://x"&gt;y&lt;/a&gt;'


def private_tap(data: str, *, user_id: int, update_id: int) -> Update:
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
                text="picker",
            ),
        ),
    )


# --------------------------------------------------------------------------
# free text into an HTML-parsed message
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field", ["product_name", "landmark", "location_text", "recipient_name", "customer_phone"]
)
def test_every_free_text_field_on_the_group_card_is_escaped(field: str) -> None:
    """CONFIRMATION IF THIS PASSES. The card goes out with parse_mode=HTML, so an
    unescaped `<` either fails the send -- the shop never hears about the order
    -- or renders as markup. Every customer-typed field, not just the landmark
    CP10b's test covered."""
    fields: dict[str, object] = {
        "order_id": 1,
        "product_name": "Oq atirgul",
        "price_uzs": 450_000,
        "telegram_file_id": "f",
        "delivery_date": datetime(2027, 3, 8).date(),
        "delivery_hour": datetime(2027, 3, 8, 14).time(),
        "landmark": "eshik",
        "customer_telegram_id": 1,
        "recipient_name": "Dilnoza",
        "location_text": "Chilonzor",
        "customer_phone": "+998901234567",
        "phone_verified": False,
    }
    fields[field] = HOSTILE
    card = OrderCard(**fields)  # type: ignore[arg-type]
    body = render_card(card, ping_number=ANNOUNCEMENT)
    assert ESCAPED in body, f"{field} reached the card unescaped"
    assert HOSTILE not in body


async def test_a_hostile_rejection_reason_is_escaped_in_the_card_and_to_the_customer(
    shop: Shop,
) -> None:
    """CONFIRMATION IF THIS PASSES. The reason is free text an admin types into a
    group, and it lands in TWO HTML-parsed places: the stamped card, and the
    message the customer receives. Both must carry it escaped."""
    await shop.feed(tap("reject", shop.order, update_id=1))
    shop.recorder.calls.clear()
    await shop.dispatcher.feed_update(shop.bot, typed(HOSTILE, update_id=2))

    stamped = [
        getattr(c, "text", None) or getattr(c, "caption", None)
        for c in shop.recorder.calls
        if isinstance(c, EditMessageText | EditMessageCaption)
    ]
    told = [c.text for c in shop.recorder.calls if isinstance(c, SendMessage)]

    assert stamped, "precondition: the card was stamped"
    assert all(ESCAPED in s and HOSTILE not in s for s in stamped), stamped
    assert any(ESCAPED in m for m in told), f"the customer message was not escaped: {told}"
    assert not any(HOSTILE in m for m in told)


# --------------------------------------------------------------------------
# callback data a real client never sends
# --------------------------------------------------------------------------


async def test_a_crafted_date_offset_cannot_book_a_day_in_the_past(committed: dict) -> None:
    """DEFECT IF THIS FAILS.

    The picker offers `available_dates` -- today onwards, inside the horizon,
    shop open, not full. `pick_date` re-checks only `available_hours`, and that
    returns every opening hour for any day that is not TODAY. So a callback
    carrying `offset=-5` -- which no rendered button has -- stores a delivery
    date five days ago and moves the customer on to choosing an hour.
    """
    settings, shop_id = committed["settings"], committed["shop"]
    engine, bot, recorder, dispatcher, context = await _armed_dispatcher(
        settings, shop_id, 880_000, day=datetime.now(UTC).date()
    )
    try:
        await context.set_state(PlaceOrder.choosing_date)
        await context.update_data(delivery_date=None)
        await dispatcher.feed_update(
            bot, private_tap(OrderDateCB(offset=-5).pack(), user_id=880_000, update_id=21)
        )
        state = await context.get_state()
        stored = (await context.get_data()).get("delivery_date")
    finally:
        await engine.dispose()

    assert state != PlaceOrder.choosing_hour.state, (
        f"a date in the past was accepted (stored {stored!r}); the flow moved on to hours"
    )


async def test_a_crafted_date_offset_cannot_book_beyond_the_horizon(committed: dict) -> None:
    """DEFECT IF THIS FAILS. The same gap in the other direction: the picker
    offers `horizon_days` of dates, and a callback with a far offset is not
    checked against it."""
    settings, shop_id = committed["settings"], committed["shop"]
    engine, bot, recorder, dispatcher, context = await _armed_dispatcher(
        settings, shop_id, 880_000, day=datetime.now(UTC).date()
    )
    try:
        await context.set_state(PlaceOrder.choosing_date)
        await dispatcher.feed_update(
            bot, private_tap(OrderDateCB(offset=400).pack(), user_id=880_000, update_id=22)
        )
        state = await context.get_state()
    finally:
        await engine.dispose()

    assert state != PlaceOrder.choosing_hour.state, "a date 400 days out was accepted"


@pytest.mark.parametrize("hour", [3, 23])
async def test_a_crafted_hour_outside_opening_hours_is_refused(committed: dict, hour: int) -> None:
    """DEFECT IF THIS FAILS.

    `pick_hour` stores whatever hour the callback carries and moves on. The
    keyboard only ever offers `available_hours`; a hand-made callback for 03:00
    reaches an order the shop cannot deliver, and the card tells the courier
    to arrive at three in the morning.
    """
    settings, shop_id = committed["settings"], committed["shop"]
    tomorrow = (datetime.now(UTC) + timedelta(days=1)).date()
    engine, bot, recorder, dispatcher, context = await _armed_dispatcher(
        settings, shop_id, 880_000, day=tomorrow
    )
    try:
        await context.set_state(PlaceOrder.choosing_hour)
        await context.update_data(delivery_date=tomorrow.isoformat(), resume_at_confirm=False)
        await dispatcher.feed_update(
            bot, private_tap(OrderHourCB(hour=hour).pack(), user_id=880_000, update_id=23)
        )
        state = await context.get_state()
        stored = (await context.get_data()).get("delivery_hour")
    finally:
        await engine.dispose()

    assert state == PlaceOrder.choosing_hour.state, (
        f"hour {hour}:00 was accepted (stored {stored!r}); the flow moved to {state}"
    )


# --------------------------------------------------------------------------
# the two gate exceptions, from outside the intended flow
# --------------------------------------------------------------------------


async def test_a_customer_crafting_an_admin_callback_in_a_private_chat_does_nothing(
    shop: Shop,
) -> None:
    """CONFIRMATION IF THIS PASSES.

    The gate lets `ordadm:` through from GROUPS; private chats pass the gate
    anyway, so the admin router does receive a hand-made reject tap from a
    customer's own DM. What must stop it is `_acting_in_the_shops_own_chat`,
    which checks the CHAT against `ping_targets`. A customer's DM is not one.

    Also proves the reason-entry state cannot be reached this way: that state
    is the second gate exception, and a customer who could enter it would have
    their next private message treated as a rejection reason.
    """
    reject = OrderAdminCB(action="reject", order_id=shop.order).pack()
    confirm = OrderAdminCB(action="confirm", order_id=shop.order).pack()

    replies = await shop.feed(private_tap(reject, user_id=CUSTOMER_TG, update_id=31))
    replies += await shop.feed(private_tap(confirm, user_id=CUSTOMER_TG, update_id=32))

    context = shop.dispatcher.fsm.get_context(shop.bot, CUSTOMER_TG, CUSTOMER_TG)
    assert await context.get_state() != AdminOrder.entering_reject_reason.state
    assert await shop.status() == "placed", "a customer moved their own order"
    assert not any("sababini" in r for r in replies), "a customer was prompted for a reason"
