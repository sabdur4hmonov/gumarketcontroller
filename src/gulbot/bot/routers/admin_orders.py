"""The shop acting on its own order card, in its own group.

THE ONLY ROUTER THAT SERVES A GROUP. Every other router in this package talks
to one customer in a private chat; this one talks to whoever in the shop got to
the card first. `ChatGateMiddleware` drops all other group traffic before it
reaches here, and `CustomerMiddleware` declines to invent a customer for the
admin who tapped -- both are load-bearing, and both have tests that fail if
they stop being.

WHERE THE ORDER ID COMES FROM. The callback data, never anyone's state. A card
sits in the group for as long as the group exists, so an admin may act on
yesterday's card with no conversation behind it. The rejection reason is the
one exception -- it needs a conversation, and that conversation is keyed per
admin per chat by `FSMStrategy.USER_IN_CHAT`, so two admins rejecting two
different orders at the same time do not overwrite each other.

WHERE THE BUTTONS ARE ALLOWED TO WORK. Exactly the chats the card was sent to,
read back through `ping_targets` -- the same function that chose them. Not "any
group", so the bot sitting in some other group cannot be used to drive this
shop's orders.

WHAT THE DATABASE DECIDES. Both actions go through `services/order_status.py`,
whose compare-and-swap is the only thing standing between two admins tapping at
once and a customer being told twice. This router never inspects the status and
then acts on what it read; it asks for the transition and is told what happened.
"""

from __future__ import annotations

import logging
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.bot.callbacks import OrderAdminCB
from gulbot.bot.keyboards import reject_prompt_keyboard
from gulbot.bot.states import AdminOrder
from gulbot.i18n import t
from gulbot.models.order import OrderStatus
from gulbot.sending.order_pings import ping_targets
from gulbot.sending.telegram import TelegramTransport
from gulbot.services.order_notify import notify_customer_of_outcome
from gulbot.services.order_status import (
    REJECTION_REASON_MAX_LENGTH,
    Transition,
    confirm_order,
    reject_order,
)
from gulbot.utils.render import escape

log = logging.getLogger("gulbot.bot.admin_orders")

#: How long a Reject prompt stays open. While it is open, the chat gate lets
#: this admin's next group message through as the reason -- so an admin who
#: taps Reject and is then pulled away must not have an unrelated message an
#: hour later become a rejection reason. Ten minutes is long enough to type a
#: sentence and short enough that nobody comes back to a live prompt.
REASON_WINDOW = timedelta(minutes=10)


async def _acting_in_the_shops_own_chat(
    session: AsyncSession, *, shop_id: int, chat_id: int
) -> bool:
    """Is this one of the chats the card was actually sent to?

    Read back through `ping_targets`, the same function that chose where the
    card went, rather than a second list that could disagree with it.
    """
    return chat_id in await ping_targets(session, shop_id=shop_id)


async def _stamp_card(
    *,
    chat_id: int,
    message_id: int,
    body: str,
    is_photo: bool,
    bot: object,
) -> bool:
    """Rewrite the card to show the outcome and drop the buttons.

    The card IS the record. Appending the outcome to it -- rather than posting
    a new message underneath -- means a group holding a day of orders reads as
    a list of decisions instead of a list of questions with answers scattered
    between them.

    Editing can legitimately fail: Telegram refuses edits to messages older
    than 48 hours, and a card from three days ago is exactly the kind an admin
    scrolls back to. The transition has already happened by then, so a refused
    edit must not look like a failed action.
    """
    try:
        if is_photo:
            await bot.edit_message_caption(  # type: ignore[attr-defined]
                chat_id=chat_id, message_id=message_id, caption=body, reply_markup=None
            )
        else:
            await bot.edit_message_text(  # type: ignore[attr-defined]
                chat_id=chat_id, message_id=message_id, text=body, reply_markup=None
            )
        return True
    except TelegramBadRequest as exc:
        log.info("card edit refused (%s); the transition still stands", exc.message)
        return False


def _outcome_body(card_html: str, *, status: OrderStatus, lang: str, reason: str | None) -> str:
    """The original card, plus what was decided."""
    if status is OrderStatus.CONFIRMED:
        stamp = t("group.outcome.confirmed", lang)
    else:
        stamp = t("group.outcome.rejected", lang, reason=escape(reason or ""))
    return f"{card_html}\n\n{stamp}"


async def _report(callback: CallbackQuery, transition: Transition, lang: str) -> bool:
    """Answer the tap. True when the caller should carry on.

    A tap that changed nothing is the ORDINARY outcome of two admins reaching
    for the same card, so it is answered as information rather than an error.
    """
    if transition.missing:
        await callback.answer(t("group.order_missing", lang), show_alert=True)
        return False
    if transition.already_handled:
        await callback.answer(t("group.already_handled", lang), show_alert=True)
        return False
    await callback.answer()
    return True


async def _tell_the_customer(
    session: AsyncSession,
    *,
    bot: object,
    shop_id: int,
    order_id: int,
    status: OrderStatus,
    reason: str | None,
) -> bool:
    """Best effort, and the caller says so out loud when it fails."""
    try:
        outcome = await notify_customer_of_outcome(
            session,
            transport=TelegramTransport(bot),  # type: ignore[arg-type]
            shop_id=shop_id,
            order_id=order_id,
            status=status,
            now_utc=datetime.now(UTC),
            reason=reason,
        )
    except Exception:  # pragma: no cover - the group line is the fallback
        log.exception("notifying the customer of order %s failed", order_id)
        return False
    return outcome.notified


async def confirm(
    callback: CallbackQuery,
    callback_data: OrderAdminCB,
    session: AsyncSession,
    shop_id: int,
    lang: str,
) -> None:
    """Accept the order, stamp the card, tell the customer."""
    message = callback.message
    if not isinstance(message, Message) or callback.bot is None:  # pragma: no cover
        await callback.answer()
        return
    if not await _acting_in_the_shops_own_chat(session, shop_id=shop_id, chat_id=message.chat.id):
        log.warning("confirm from chat %s, which is not shop %s", message.chat.id, shop_id)
        await callback.answer()
        return

    order_id = callback_data.order_id
    transition = await confirm_order(session, shop_id=shop_id, order_id=order_id)
    # THE DECISION IS DURABLE BEFORE ANYONE IS TOLD. Committing here rather than
    # letting `DbSessionMiddleware` do it at the end of the handler: everything
    # after this point talks to Telegram, and a rollback after the customer has
    # been messaged would leave the order 'placed' while the customer believes
    # it is accepted -- the precise silence this checkpoint exists to remove.
    # Committing even when nothing changed is harmless and keeps the rule in
    # one place.
    await session.commit()
    if not await _report(callback, transition, lang):
        return

    notified = await _tell_the_customer(
        session,
        bot=callback.bot,
        shop_id=shop_id,
        order_id=order_id,
        status=OrderStatus.CONFIRMED,
        reason=None,
    )
    body = _outcome_body(message.html_text, status=OrderStatus.CONFIRMED, lang=lang, reason=None)
    if not notified:
        body = f"{body}\n{t('group.customer_not_notified', lang)}"
    await _stamp_card(
        chat_id=message.chat.id,
        message_id=message.message_id,
        body=body,
        is_photo=bool(message.photo),
        bot=callback.bot,
    )


async def ask_for_a_reason(
    callback: CallbackQuery,
    callback_data: OrderAdminCB,
    session: AsyncSession,
    state: FSMContext,
    shop_id: int,
    lang: str,
) -> None:
    """Reject needs a sentence before it finalises.

    NOTHING IS WRITTEN HERE. The order stays 'placed' until the reason arrives,
    so an admin who taps Reject and changes their mind has changed nothing --
    and a customer is never told "rejected" with no explanation, which is the
    silence this checkpoint exists to remove.
    """
    message = callback.message
    if not isinstance(message, Message):  # pragma: no cover
        await callback.answer()
        return
    if not await _acting_in_the_shops_own_chat(session, shop_id=shop_id, chat_id=message.chat.id):
        log.warning("reject from chat %s, which is not shop %s", message.chat.id, shop_id)
        await callback.answer()
        return

    await callback.answer()
    await state.set_state(AdminOrder.entering_reject_reason)
    await state.update_data(
        order_id=callback_data.order_id,
        card_chat_id=message.chat.id,
        card_message_id=message.message_id,
        card_html=message.html_text,
        card_is_photo=bool(message.photo),
        asked_at=datetime.now(UTC).isoformat(),
    )
    await message.answer(
        t("group.reason_prompt", lang, id=callback_data.order_id),
        reply_markup=reject_prompt_keyboard(lang, callback_data.order_id),
    )


async def enter_reason(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    shop_id: int,
    lang: str,
) -> None:
    """The reason, typed in the group. This is what finalises the rejection."""
    data = await state.get_data()
    order_id = data.get("order_id")
    asked_at = data.get("asked_at")
    if order_id is None or asked_at is None:  # pragma: no cover - set together
        await state.clear()
        return

    # A prompt nobody answered promptly is a trap: the gate is letting this
    # admin's group messages through, and an unrelated one must not become a
    # rejection reason.
    if datetime.now(UTC) - datetime.fromisoformat(asked_at) > REASON_WINDOW:
        await state.clear()
        await message.answer(t("group.reason_expired", lang, id=order_id))
        return

    await state.clear()
    reason = (message.text or "").strip()[:REJECTION_REASON_MAX_LENGTH]
    transition = await reject_order(session, shop_id=shop_id, order_id=order_id, reason=reason)
    # Same phase boundary as `confirm`. One commit covers the status change AND
    # the pings `reject_order` cancelled in the same transaction, so there is
    # still no instant where an order is rejected and its reminders are armed.
    await session.commit()
    if transition.missing:
        await message.answer(t("group.order_missing", lang))
        return
    if transition.already_handled:
        await message.answer(t("group.already_handled", lang))
        return

    notified = await _tell_the_customer(
        session,
        bot=message.bot,
        shop_id=shop_id,
        order_id=order_id,
        status=OrderStatus.REJECTED,
        reason=reason,
    )
    body = _outcome_body(
        str(data.get("card_html", "")), status=OrderStatus.REJECTED, lang=lang, reason=reason
    )
    if not notified:
        body = f"{body}\n{t('group.customer_not_notified', lang)}"
    await _stamp_card(
        chat_id=int(data["card_chat_id"]),
        message_id=int(data["card_message_id"]),
        body=body,
        is_photo=bool(data.get("card_is_photo")),
        bot=message.bot,
    )


async def abort_rejection(
    callback: CallbackQuery,
    callback_data: OrderAdminCB,
    state: FSMContext,
    lang: str,
) -> None:
    """Withdraw a Reject that was never finalised.

    Nothing was written when the prompt went up, so nothing has to be undone:
    the order is still 'placed' and the card still carries both buttons.
    """
    await callback.answer()
    await state.clear()
    message = callback.message
    if isinstance(message, Message):
        with suppress(TelegramBadRequest):
            await message.edit_text(
                t("group.reject_aborted", lang, id=callback_data.order_id), reply_markup=None
            )


def build_admin_orders_router() -> Router:
    """A factory, not a singleton: an aiogram Router attaches to exactly one
    Dispatcher, and the shadow sweep builds a second one."""
    router = Router(name="admin_orders")

    router.callback_query.register(confirm, OrderAdminCB.filter(F.action == "confirm"))
    router.callback_query.register(ask_for_a_reason, OrderAdminCB.filter(F.action == "reject"))
    router.callback_query.register(abort_rejection, OrderAdminCB.filter(F.action == "abort"))
    # Gated on the STATE, so this cannot catch ordinary group chatter -- and
    # the chat gate will not even deliver such a message unless this same
    # state is set. Two independent conditions for one narrow exception.
    #
    # `catch_all` is what tells the shadow sweep this accepts ANY text on
    # purpose, the same declaration every other text-waiting state makes. It
    # is a claim, not a suppression: the sweep still requires nav's Cancel and
    # onboarding's /start to be registered ahead of it, which is why this
    # router is last of the three.
    router.message.register(
        enter_reason, AdminOrder.entering_reject_reason, F.text, flags={"catch_all": True}
    )
    return router
