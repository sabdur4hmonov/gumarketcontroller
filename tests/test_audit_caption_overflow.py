# ruff: noqa: F811  -- fixtures are imported by name; pytest injects them into
# the same-named test parameters, which ruff reads as a redefinition.
"""PASS 4: stamping an outcome must not push a photo card past Telegram's limit.

The card goes out as a photo when its HTML is at most CAPTION_LIMIT (1024)
characters, and Confirm/Reject then EDIT that caption, appending the outcome --
a rejection appends the admin's reason, up to REJECTION_REASON_MAX_LENGTH more.

Telegram measures a caption AFTER parsing entities: the VISIBLE length.

Measured from the real field caps and the real renderer: a worst-case card is
sent as a photo at 822 visible characters, and a maximum rejection stamp takes
it to 1047. Telegram refuses that edit, and `_stamp_card` caught the refusal --
so the order was rejected and the customer told, while the card kept both live
buttons and showed no outcome.

The fix: when the stamped caption would not fit, drop the buttons on their own
and post the outcome as a REPLY to the card. These tests drive a real reject
through the dispatcher with a worst-case photo card and check which Telegram
calls were made. The recording session does not enforce Telegram's limit, so
the assertion is on the CALLS -- no over-limit caption edit is attempted --
rather than on a simulated refusal.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time

from aiogram.methods import EditMessageCaption, EditMessageReplyMarkup, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, PhotoSize, Update, User
from tests.test_admin_orders import (  # noqa: F401  -- `shop` is a fixture
    ADMIN_ID,
    GROUP_ID,
    Shop,
    shop,
    typed,
)

from gulbot.bot.callbacks import OrderAdminCB
from gulbot.catalog.naming import NAME_MAX_LENGTH
from gulbot.models.order import LANDMARK_MAX_LENGTH, RECIPIENT_NAME_MAX_LENGTH
from gulbot.sending.order_card import ANNOUNCEMENT, OrderCard, render_card
from gulbot.sending.transport import CAPTION_LIMIT
from gulbot.services.order_status import REJECTION_REASON_MAX_LENGTH
from gulbot.utils.render import visible_length

CARD_MESSAGE_ID = 777


def worst_case_card() -> str:
    """Every free-text field at its cap, in plain letters so the HTML source is
    as short as possible relative to what is visible -- the combination most
    likely to still be sent as a photo."""
    return render_card(
        OrderCard(
            order_id=999_999,
            product_name="a" * NAME_MAX_LENGTH,
            price_uzs=999_999_999,
            telegram_file_id="f",
            delivery_date=date(2027, 12, 31),
            delivery_hour=time(19, 0),
            landmark="b" * LANDMARK_MAX_LENGTH,
            customer_telegram_id=9_999_999_999,
            recipient_name="c" * RECIPIENT_NAME_MAX_LENGTH,
            location_text="d" * LANDMARK_MAX_LENGTH,
            customer_phone="+998901234567",
            phone_verified=False,
        ),
        ping_number=ANNOUNCEMENT,
    )


def photo_card_tap(action: str, order_id: int, *, caption: str, update_id: int) -> Update:
    """A tap on a PHOTO card whose visible caption is `caption`."""
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id=f"cb{update_id}",
            from_user=User(id=ADMIN_ID, is_bot=False, first_name="Admin"),
            chat_instance=f"chat{update_id}",
            data=OrderAdminCB(action=action, order_id=order_id).pack(),
            message=Message(
                message_id=CARD_MESSAGE_ID,
                date=datetime.now(tz=UTC),
                chat=Chat(id=GROUP_ID, type="supergroup", title="Shop admins"),
                from_user=User(id=1, is_bot=True, first_name="bot"),
                caption=caption,
                photo=[PhotoSize(file_id="f", file_unique_id="u", width=1, height=1)],
            ),
        ),
    )


def reply_target(call: SendMessage) -> int | None:
    """aiogram may carry the reply as either field, depending on version."""
    direct = getattr(call, "reply_to_message_id", None)
    if direct is not None:
        return int(direct)
    params = getattr(call, "reply_parameters", None)
    return int(params.message_id) if params is not None else None


def test_the_worst_case_arithmetic() -> None:
    """The measured fact the fix exists for: a photo card that fits, and a
    rejection stamp that does not. If this ever stops being true the overflow
    branch is dead code -- worth knowing, not a failure of the product."""
    card = worst_case_card()
    visible_card = visible_length(card)
    stamped = visible_card + len("\n\n❌ Rad etildi\nℹ️ Sabab: ") + REJECTION_REASON_MAX_LENGTH
    print(f"\n  card html={len(card)} visible={visible_card}; with max reason ~{stamped}")
    assert len(card) <= CAPTION_LIMIT, "precondition: the worst-case card is sent as a photo"
    assert stamped > CAPTION_LIMIT, "precondition: a maximum rejection overflows it"


async def test_a_rejection_that_would_overflow_the_caption_is_stamped_by_reply(
    shop: Shop,
) -> None:
    """DEFECT IF THIS FAILS. The outcome must reach the card's thread and the
    buttons must go, without attempting a caption edit Telegram would refuse."""
    visible_caption = visible_length(worst_case_card())
    caption = "x" * visible_caption
    reason = "r" * REJECTION_REASON_MAX_LENGTH

    await shop.feed(photo_card_tap("reject", shop.order, caption=caption, update_id=41))
    shop.recorder.calls.clear()
    await shop.dispatcher.feed_update(shop.bot, typed(reason, update_id=42))

    calls = shop.recorder.calls
    over_limit_edits = [
        c
        for c in calls
        if isinstance(c, EditMessageCaption) and visible_length(c.caption or "") > CAPTION_LIMIT
    ]
    buttons_removed = [
        c
        for c in calls
        if isinstance(c, EditMessageReplyMarkup)
        and c.message_id == CARD_MESSAGE_ID
        and c.reply_markup is None
    ]
    replies = [
        c
        for c in calls
        if isinstance(c, SendMessage) and reply_target(c) == CARD_MESSAGE_ID and reason in c.text
    ]

    assert await shop.status() == "rejected", "precondition: the rejection happened"
    assert not over_limit_edits, "an over-limit caption edit was attempted; Telegram refuses it"
    assert buttons_removed, "the card kept its buttons after the order was rejected"
    assert replies, "the outcome was not posted under the card"


async def test_a_short_card_is_still_stamped_in_place(shop: Shop) -> None:
    """CONFIRMATION IF THIS PASSES -- guards the guard. The ordinary card must
    keep the in-place caption edit; only an overflowing one takes the reply."""
    await shop.feed(photo_card_tap("reject", shop.order, caption="Yangi buyurtma", update_id=51))
    shop.recorder.calls.clear()
    await shop.dispatcher.feed_update(shop.bot, typed("gul tugadi", update_id=52))

    edits = [c for c in shop.recorder.calls if isinstance(c, EditMessageCaption)]
    replies = [
        c
        for c in shop.recorder.calls
        if isinstance(c, SendMessage) and reply_target(c) == CARD_MESSAGE_ID
    ]
    assert edits and "gul tugadi" in (edits[0].caption or ""), "the short card was not stamped"
    assert not replies, "a card that fits was stamped by reply instead"
