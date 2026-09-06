"""Placing an order. The last customer-facing flow.

PICKER-ONLY, the same discipline held since CP3. Dates and hours are buttons;
only the address and the landmark accept free text, and both are sanitised with
CP3's sanitiser rather than a second implementation. A free-text delivery time
in uz/ru produces garbage no parser fixes, and every text-waiting state is
somewhere Cancel and /start have to be proven to still win -- which is why there
are exactly two of them.

NOTHING IS WRITTEN UNTIL THE CONFIRMATION IS TAPPED. The flow accumulates a
draft in FSM state; `orders` sees its first row when the customer says Ha.

THE SUBMIT TOKEN IS MINTED WITH THE CONFIRMATION SCREEN, not at submit. Both
halves of a double-tap therefore carry the same token and collide on a unique
index. Answering the callback and clearing the keyboard are still done, and are
still not the guarantee -- see `services/orders.py`.

TELLING THE SHOP IS NOT DONE INLINE. Submit writes an outbox row (ping 0) and
commits; the message to the group is then FLUSHED from here so it arrives at
once, with the beat as the safety net if this process dies mid-send. Sending
inline and hoping would mean a Telegram hiccup could lose an order the customer
has already been told was accepted, which is the worst failure this system has.

WHAT THIS FLOW DOES NOT DO: transition a status. It writes 'placed' and stops.
No confirm, no reject, no delivery, no customer-facing status updates beyond the
one acknowledgement. `tests/test_order_scope.py` fails the build if that changes.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, time, timedelta
from typing import Any

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.bot.callbacks import (
    OrderBackCB,
    OrderConfirmCB,
    OrderDateCB,
    OrderHourCB,
    OrderLocationCB,
    OrderStartCB,
)
from gulbot.bot.keyboards import (
    main_menu_keyboard,
    order_confirm_keyboard,
    order_date_keyboard,
    order_hour_keyboard,
    order_location_keyboard,
    share_location_keyboard,
)
from gulbot.bot.states import PlaceOrder
from gulbot.i18n import t
from gulbot.i18n.catalog import CATALOG
from gulbot.models.customer import Customer
from gulbot.models.order import LANDMARK_MAX_LENGTH
from gulbot.models.product import Product
from gulbot.scheduling.delivery import available_dates, available_hours
from gulbot.scheduling.occurrences import TASHKENT
from gulbot.sending.order_pings import run_order_ping_tick
from gulbot.sending.telegram import TelegramTransport
from gulbot.services.orders import (
    OrderDraft,
    announce_order,
    create_order,
    dates_at_capacity,
    load_slot_policy,
    materialize_order_pings,
)
from gulbot.utils.render import escape, format_date_long, format_price
from gulbot.utils.text import sanitize_label

log = logging.getLogger("gulbot.bot.orders")

BACK_LABELS = set(CATALOG["btn.nav.back"].values())


def _target(callback: CallbackQuery) -> Message:
    message = callback.message
    assert isinstance(message, Message)
    return message


async def _show_dates(
    target: Message, state: FSMContext, session: AsyncSession, shop_id: int, lang: str
) -> None:
    policy = await load_slot_policy(session, shop_id=shop_id)
    now_local = datetime.now(TASHKENT)
    horizon_end = now_local.date() + timedelta(days=policy.horizon_days)
    full = await dates_at_capacity(
        session, shop_id=shop_id, horizon_start=now_local.date(), horizon_end=horizon_end
    )
    dates = available_dates(policy, now_local, full_dates=full)
    if not dates:
        await state.clear()
        await target.answer(t("order.no_slots", lang), reply_markup=main_menu_keyboard(lang))
        return
    await state.set_state(PlaceOrder.choosing_date)
    await target.answer(
        t("order.choose_date", lang),
        reply_markup=order_date_keyboard(lang, dates, now_local.date()),
    )


async def start_order(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, customer: Customer, lang: str
) -> None:
    """Entry. Takes only a product id, so a browse screen can call it too."""
    await callback.answer()
    data = OrderStartCB.unpack(callback.data or "")
    product = await session.scalar(
        select(Product).where(Product.id == data.product_id, Product.shop_id == customer.shop_id)
    )
    target = _target(callback)
    if product is None:
        await state.clear()
        await target.answer(t("order.gone", lang), reply_markup=main_menu_keyboard(lang))
        return

    # Captured now so the confirmation screen and the fallback snapshot show
    # what the customer actually chose, even if the indexer edits the post.
    await state.update_data(
        product_id=product.id,
        product_name=product.name,
        price_uzs=product.price_uzs,
        telegram_file_id=product.telegram_file_id,
    )
    await _show_dates(target, state, session, customer.shop_id, lang)


async def pick_date(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, customer: Customer, lang: str
) -> None:
    await callback.answer()
    offset = OrderDateCB.unpack(callback.data or "").offset
    policy = await load_slot_policy(session, shop_id=customer.shop_id)
    now_local = datetime.now(TASHKENT)
    chosen = now_local.date() + timedelta(days=offset)

    hours = available_hours(policy, chosen, now_local)
    target = _target(callback)
    if not hours:
        # The picker is rebuilt rather than trusted: minutes may have passed
        # since it was rendered, and the lead time moves.
        await _show_dates(target, state, session, customer.shop_id, lang)
        return

    await state.update_data(delivery_date=chosen.isoformat())
    await state.set_state(PlaceOrder.choosing_hour)
    await target.answer(t("order.choose_hour", lang), reply_markup=order_hour_keyboard(lang, hours))


async def pick_hour(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    await callback.answer()
    hour = OrderHourCB.unpack(callback.data or "").hour
    await state.update_data(delivery_hour=hour)
    await state.set_state(PlaceOrder.choosing_location)
    await _target(callback).answer(
        t("order.choose_location", lang), reply_markup=order_location_keyboard(lang)
    )


async def pick_location_mode(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    await callback.answer()
    mode = OrderLocationCB.unpack(callback.data or "").mode
    target = _target(callback)
    if mode == "text":
        await state.set_state(PlaceOrder.entering_address)
        await target.answer(t("order.enter_address", lang))
        return
    await state.set_state(PlaceOrder.waiting_location)
    await target.answer(t("order.share_location", lang), reply_markup=share_location_keyboard(lang))


async def _ask_landmark(target: Message, state: FSMContext, lang: str) -> None:
    await state.set_state(PlaceOrder.entering_landmark)
    await target.answer(t("order.enter_landmark", lang))


async def enter_address(message: Message, state: FSMContext, lang: str) -> None:
    address = sanitize_label(message.text or "", max_length=LANDMARK_MAX_LENGTH)
    if not address:
        await message.answer(t("order.address_empty", lang))
        return
    await state.update_data(location_text=address, location_lat=None, location_lon=None)
    await _ask_landmark(message, state, lang)


async def receive_location(message: Message, state: FSMContext, lang: str) -> None:
    location = message.location
    assert location is not None
    await state.update_data(
        location_text=None, location_lat=location.latitude, location_lon=location.longitude
    )
    await _ask_landmark(message, state, lang)


def _summary(lang: str, data: dict[str, Any]) -> str:
    """What the customer confirms, and what they are told afterwards.

    The bouquet line REUSES the reminder's keys, so the
    "narx operator tomonidan tasdiqlanadi" wording exists in exactly one place.
    """
    name = escape(str(data["product_name"]))
    price = data.get("price_uzs")
    bouquet = (
        t("reminder.bouquet", lang, name=name, price=format_price(int(price)))
        if price
        else t("reminder.bouquet.no_price", lang, name=name)
    )
    day = datetime.fromisoformat(str(data["delivery_date"])).date()
    location = (
        escape(str(data["location_text"]))
        if data.get("location_text")
        else t("order.location_pin", lang)
    )
    return t(
        "order.summary",
        lang,
        bouquet=bouquet,
        date=format_date_long(day.day, day.month, None, lang),
        hour=f"{int(data['delivery_hour']):02d}:00",
        location=location,
        landmark=escape(str(data.get("landmark", ""))),
    )


async def enter_landmark(message: Message, state: FSMContext, lang: str) -> None:
    landmark = sanitize_label(message.text or "", max_length=LANDMARK_MAX_LENGTH)
    if not landmark:
        await message.answer(t("order.landmark_empty", lang))
        return
    # The token is minted HERE, with the screen: both halves of a double-tap
    # then carry the same one and collide on the unique index.
    await state.update_data(landmark=landmark, submit_token=uuid.uuid4().hex)
    await state.set_state(PlaceOrder.confirming)
    data = await state.get_data()
    await message.answer(
        t("order.confirm", lang, summary=_summary(lang, data)),
        reply_markup=order_confirm_keyboard(lang),
    )


async def submit_order(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, customer: Customer, lang: str
) -> None:
    await callback.answer()
    data = await state.get_data()
    target = _target(callback)
    if "submit_token" not in data:
        await state.clear()
        await target.answer(t("order.gone", lang), reply_markup=main_menu_keyboard(lang))
        return

    # Best effort, and not the guarantee: the unique index is.
    with suppress_telegram_errors():
        await target.edit_reply_markup(reply_markup=None)

    day = datetime.fromisoformat(str(data["delivery_date"])).date()
    hour = time(int(data["delivery_hour"]))
    draft = OrderDraft(
        product_id=int(data["product_id"]),
        product_name=str(data["product_name"]),
        price_uzs=data.get("price_uzs"),
        telegram_file_id=str(data["telegram_file_id"]),
        delivery_date=day,
        delivery_hour=hour,
        landmark=str(data["landmark"]),
        submit_token=str(data["submit_token"]),
        recipient_id=data.get("recipient_id"),
        location_text=data.get("location_text"),
        location_lat=data.get("location_lat"),
        location_lon=data.get("location_lon"),
    )
    order, created = await create_order(
        session, shop_id=customer.shop_id, customer_id=customer.id, draft=draft
    )
    if order is not None and created:
        delivery_at_utc = datetime.combine(day, hour, tzinfo=TASHKENT).astimezone(UTC)
        await materialize_order_pings(session, order=order, delivery_at_utc=delivery_at_utc)
        await announce_order(session, order=order)

    await state.clear()
    # The loser of a double-tap is told the same thing: from the customer's
    # side one order was placed, which is true.
    await target.answer(
        t("order.placed", lang, summary=_summary(lang, data)),
        reply_markup=main_menu_keyboard(lang),
    )

    if order is not None and created:
        await _tell_the_shop_now(session, callback, order_id=order.id)


async def _tell_the_shop_now(
    session: AsyncSession, callback: CallbackQuery, *, order_id: int
) -> None:
    """Deliver this order's announcement immediately instead of waiting a beat.

    Runs exactly the tick's own code, narrowed to one order, so there is ONE
    implementation of claiming and sending. The claim is what makes calling it
    from here safe: the beat cannot send a second copy of a row this already
    took, and if this process dies mid-send the claim goes stale and the beat
    picks it up.

    Deliberately last, and deliberately swallowing everything. The customer has
    already been told their order was accepted, and that is true -- the row is
    committed. If Telegram is down for the group, the ping stays in the outbox
    and the beat retries it; an exception escaping here would turn a delivered
    order into an error message for the customer.
    """
    if callback.bot is None:  # pragma: no cover - aiogram always sets it
        return
    try:
        await run_order_ping_tick(
            session,
            transport=TelegramTransport(callback.bot),
            now_utc=datetime.now(UTC),
            only_order_id=order_id,
        )
    except Exception:  # pragma: no cover - the beat is the retry
        log.exception("immediate shop notification failed for order %s", order_id)


async def discard_order(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    await callback.answer()
    await state.clear()
    await _target(callback).answer(t("nav.cancelled", lang), reply_markup=main_menu_keyboard(lang))


# --- per-state Back. Registered once per state, never globally: a single
# ungated Back handler would shadow every one of these, and the sweep says so.


async def back_from_date(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    await callback.answer()
    await state.clear()
    await _target(callback).answer(t("menu.title", lang), reply_markup=main_menu_keyboard(lang))


async def back_to_dates(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, customer: Customer, lang: str
) -> None:
    await callback.answer()
    await _show_dates(_target(callback), state, session, customer.shop_id, lang)


async def back_to_hours(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, customer: Customer, lang: str
) -> None:
    await callback.answer()
    data = await state.get_data()
    policy = await load_slot_policy(session, shop_id=customer.shop_id)
    now_local = datetime.now(TASHKENT)
    day = datetime.fromisoformat(str(data["delivery_date"])).date()
    hours = available_hours(policy, day, now_local)
    target = _target(callback)
    if not hours:
        await _show_dates(target, state, session, customer.shop_id, lang)
        return
    await state.set_state(PlaceOrder.choosing_hour)
    await target.answer(t("order.choose_hour", lang), reply_markup=order_hour_keyboard(lang, hours))


async def back_to_location(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    await callback.answer()
    await state.set_state(PlaceOrder.choosing_location)
    await _target(callback).answer(
        t("order.choose_location", lang), reply_markup=order_location_keyboard(lang)
    )


async def back_to_location_from_pin(message: Message, state: FSMContext, lang: str) -> None:
    """The pin step lives on a REPLY keyboard, so its Back is a text button."""
    await state.set_state(PlaceOrder.choosing_location)
    await message.answer(
        t("order.choose_location", lang), reply_markup=order_location_keyboard(lang)
    )


class suppress_telegram_errors:  # noqa: N801  - used as a context manager
    """Editing the keyboard away is cosmetic; failing to is not an error.

    The message may already have been edited by the other half of a double-tap,
    or be too old. Neither should stop an order being written.
    """

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return exc_type is not None


def build_orders_router() -> Router:
    router = Router(name="orders")

    # Entry, from the button under a bouquet.
    router.callback_query.register(start_order, StateFilter(None), OrderStartCB.filter())

    # Back first, per state, so it is never shadowed by the step's own handler.
    router.callback_query.register(back_from_date, PlaceOrder.choosing_date, OrderBackCB.filter())
    router.callback_query.register(back_to_dates, PlaceOrder.choosing_hour, OrderBackCB.filter())
    router.callback_query.register(
        back_to_hours, PlaceOrder.choosing_location, OrderBackCB.filter()
    )
    router.callback_query.register(
        back_to_location, PlaceOrder.entering_address, OrderBackCB.filter()
    )
    router.callback_query.register(
        back_to_location, PlaceOrder.entering_landmark, OrderBackCB.filter()
    )
    router.callback_query.register(back_to_location, PlaceOrder.confirming, OrderBackCB.filter())
    router.message.register(
        back_to_location_from_pin, PlaceOrder.waiting_location, F.text.in_(BACK_LABELS)
    )

    # The steps.
    router.callback_query.register(pick_date, PlaceOrder.choosing_date, OrderDateCB.filter())
    router.callback_query.register(pick_hour, PlaceOrder.choosing_hour, OrderHourCB.filter())
    router.callback_query.register(
        pick_location_mode, PlaceOrder.choosing_location, OrderLocationCB.filter()
    )
    # A location message, not text: specific, so NOT a catch-all.
    router.message.register(receive_location, PlaceOrder.waiting_location, F.location)
    # catch_all: within its state this accepts ANY text, so nav and commands
    # registered ahead of it are meant to win.
    router.message.register(
        enter_address, PlaceOrder.entering_address, F.text, flags={"catch_all": True}
    )
    router.message.register(
        enter_landmark, PlaceOrder.entering_landmark, F.text, flags={"catch_all": True}
    )
    router.callback_query.register(
        submit_order, PlaceOrder.confirming, OrderConfirmCB.filter(F.action == "submit")
    )
    router.callback_query.register(
        discard_order, PlaceOrder.confirming, OrderConfirmCB.filter(F.action == "discard")
    )
    return router
