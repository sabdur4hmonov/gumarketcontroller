"""Occasions: list, add (picker-driven), deactivate.

Every step except the label and the year is an inline picker. The day keyboard
is built from the chosen month, so Feb 30 and Apr 31 cannot be produced at all;
the Python validator and the database CHECK are the second and third lines of
defence, not the first.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.bot.callbacks import (
    AddOccasionCB,
    BackCB,
    ConfirmCB,
    DayCB,
    MonthCB,
    OccasionActionCB,
    OccasionTypeCB,
    YearSkipCB,
)
from gulbot.bot.keyboards import (
    confirm_keyboard,
    day_keyboard,
    main_menu_keyboard,
    month_keyboard,
    occasion_list_keyboard,
    occasion_type_keyboard,
    year_keyboard,
)
from gulbot.bot.states import AddOccasion
from gulbot.i18n import t
from gulbot.i18n.catalog import CATALOG
from gulbot.models.customer import Customer
from gulbot.models.occasion import OccasionType
from gulbot.services.occasions import (
    create_occasion,
    deactivate_occasion,
    is_valid_month_day,
    is_valid_year,
    list_active_occasions,
    record_store_dates_consent,
)
from gulbot.utils.render import escape, format_date
from gulbot.utils.text import sanitize_label

OCCASIONS_LABELS = set(CATALOG["btn.menu.occasions"].values())


def _reply_target(callback: CallbackQuery) -> Message:
    """The message an inline callback should answer into.

    Telegram omits `message` for callbacks on messages older than 48 hours, so
    this is checked rather than assumed.
    """
    message = callback.message
    if not isinstance(message, Message):
        raise ValueError("callback has no reachable message")
    return message


# --- listing ---------------------------------------------------------------


async def show_occasions(
    message: Message, session: AsyncSession, customer: Customer, lang: str
) -> None:
    occasions = await list_active_occasions(
        session, shop_id=customer.shop_id, customer_id=customer.id
    )
    if not occasions:
        await message.answer(
            t("occasions.empty", lang), reply_markup=occasion_list_keyboard(lang, [])
        )
        return
    lines = [f"• {escape(o.label)} — {format_date(o.day, o.month, o.year)}" for o in occasions]
    await message.answer(
        t("occasions.list_title", lang) + "\n" + "\n".join(lines),
        reply_markup=occasion_list_keyboard(lang, [(o.id, o.label) for o in occasions]),
    )


async def deactivate(
    callback: CallbackQuery,
    callback_data: OccasionActionCB,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    label = await deactivate_occasion(
        session,
        shop_id=customer.shop_id,
        customer_id=customer.id,
        occasion_id=callback_data.occasion_id,
    )
    await callback.answer()
    target = _reply_target(callback)
    if label is None:
        await target.answer(t("occasions.not_found", lang))
        return
    await target.answer(t("occasions.deactivated", lang, label=escape(label)))


# --- add flow --------------------------------------------------------------


async def start_add(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    await state.set_state(AddOccasion.choosing_type)
    await callback.answer()
    await _reply_target(callback).answer(
        t("occasions.choose_type", lang), reply_markup=occasion_type_keyboard(lang)
    )


async def pick_type(
    callback: CallbackQuery, callback_data: OccasionTypeCB, state: FSMContext, lang: str
) -> None:
    await callback.answer()
    target = _reply_target(callback)
    if callback_data.type == OccasionType.CUSTOM.value:
        await state.set_state(AddOccasion.entering_label)
        await target.answer(t("occasions.enter_label", lang))
        return
    await state.update_data(type=callback_data.type, label=t(f"occtype.{callback_data.type}", lang))
    await state.set_state(AddOccasion.choosing_month)
    await target.answer(t("occasions.choose_month", lang), reply_markup=month_keyboard(lang))


async def enter_label(message: Message, state: FSMContext, lang: str) -> None:
    raw = message.text or ""
    label = sanitize_label(raw)
    if not label:
        await message.answer(t("occasions.label_empty", lang))
        return
    if len(raw.strip()) > len(label):
        await message.answer(t("occasions.label_trimmed", lang))
    await state.update_data(type=OccasionType.CUSTOM.value, label=label)
    await state.set_state(AddOccasion.choosing_month)
    await message.answer(t("occasions.choose_month", lang), reply_markup=month_keyboard(lang))


async def pick_month(
    callback: CallbackQuery, callback_data: MonthCB, state: FSMContext, lang: str
) -> None:
    await callback.answer()
    await state.update_data(month=callback_data.month)
    await state.set_state(AddOccasion.choosing_day)
    await _reply_target(callback).answer(
        t("occasions.choose_day", lang),
        reply_markup=day_keyboard(lang, callback_data.month),
    )


async def pick_day(
    callback: CallbackQuery, callback_data: DayCB, state: FSMContext, lang: str
) -> None:
    await callback.answer()
    data = await state.get_data()
    month = int(data["month"])
    target = _reply_target(callback)
    # The picker cannot offer an invalid day, so this can only fire on a forged
    # or replayed callback. Refuse rather than trust the client.
    if not is_valid_month_day(month, callback_data.day):
        await target.answer(t("occasions.choose_day", lang), reply_markup=day_keyboard(lang, month))
        return
    await state.update_data(day=callback_data.day)
    await state.set_state(AddOccasion.entering_year)
    await target.answer(t("occasions.enter_year", lang), reply_markup=year_keyboard(lang))


async def _go_to_confirm(
    answer_to: Message, state: FSMContext, lang: str, year: int | None
) -> None:
    await state.update_data(year=year)
    data = await state.get_data()
    await state.set_state(AddOccasion.confirming)
    summary = t(
        "occasions.confirm",
        lang,
        label=escape(str(data["label"])),
        date=format_date(int(data["day"]), int(data["month"]), year),
    )
    consent = t("occasions.consent", lang)
    await answer_to.answer(f"{summary}\n\n{consent}", reply_markup=confirm_keyboard(lang))


async def enter_year(message: Message, state: FSMContext, lang: str) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or len(raw) != 4:
        await message.answer(t("occasions.year_invalid", lang))
        return
    year = int(raw)
    data = await state.get_data()
    month, day = int(data["month"]), int(data["day"])
    if not 1900 <= year <= 2100:
        await message.answer(t("occasions.year_invalid", lang))
        return
    if not is_valid_year(year, month, day):
        await message.answer(t("occasions.year_not_leap", lang))
        return
    await _go_to_confirm(message, state, lang, year)


async def skip_year(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    await callback.answer()
    await _go_to_confirm(_reply_target(callback), state, lang, None)


async def confirm_save(
    callback: CallbackQuery,
    callback_data: ConfirmCB,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    await callback.answer()
    target = _reply_target(callback)
    if callback_data.action == "discard":
        await state.clear()
        await target.answer(t("nav.cancelled", lang), reply_markup=main_menu_keyboard(lang))
        return

    data = await state.get_data()
    await state.clear()
    occasion = await create_occasion(
        session,
        shop_id=customer.shop_id,
        customer_id=customer.id,
        type_=str(data["type"]),
        label=str(data["label"]),
        month=int(data["month"]),
        day=int(data["day"]),
        year=data.get("year"),
    )
    if occasion is None:
        await target.answer(t("occasions.duplicate", lang), reply_markup=main_menu_keyboard(lang))
        return

    # Consent is recorded at the moment the first date is stored, carrying the
    # version of the wording that was shown on the confirm screen above.
    await record_store_dates_consent(session, shop_id=customer.shop_id, customer_id=customer.id)
    await target.answer(
        t(
            "occasions.saved",
            lang,
            label=escape(occasion.label),
            date=format_date(occasion.day, occasion.month, occasion.year),
        ),
        reply_markup=main_menu_keyboard(lang),
    )


# --- per-state Back --------------------------------------------------------
# Registered once per state, never globally: a single ungated Back handler would
# shadow every one of these. The sweep enforces that.


async def back_from_type(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    await callback.answer()
    await state.clear()
    await _reply_target(callback).answer(
        t("menu.title", lang), reply_markup=main_menu_keyboard(lang)
    )


async def back_from_label(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    await callback.answer()
    await state.set_state(AddOccasion.choosing_type)
    await _reply_target(callback).answer(
        t("occasions.choose_type", lang), reply_markup=occasion_type_keyboard(lang)
    )


async def back_from_month(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    await callback.answer()
    await state.set_state(AddOccasion.choosing_type)
    await _reply_target(callback).answer(
        t("occasions.choose_type", lang), reply_markup=occasion_type_keyboard(lang)
    )


async def back_from_day(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    await callback.answer()
    await state.set_state(AddOccasion.choosing_month)
    await _reply_target(callback).answer(
        t("occasions.choose_month", lang), reply_markup=month_keyboard(lang)
    )


async def back_from_year(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    await callback.answer()
    data = await state.get_data()
    await state.set_state(AddOccasion.choosing_day)
    await _reply_target(callback).answer(
        t("occasions.choose_day", lang), reply_markup=day_keyboard(lang, int(data["month"]))
    )


async def back_from_confirm(callback: CallbackQuery, state: FSMContext, lang: str) -> None:
    await callback.answer()
    await state.set_state(AddOccasion.entering_year)
    await _reply_target(callback).answer(
        t("occasions.enter_year", lang), reply_markup=year_keyboard(lang)
    )


def build_occasions_router() -> Router:
    router = Router(name="occasions")

    router.message.register(show_occasions, StateFilter(None), F.text.in_(OCCASIONS_LABELS))
    router.callback_query.register(deactivate, OccasionActionCB.filter(F.action == "deactivate"))
    router.callback_query.register(start_add, AddOccasionCB.filter(F.action == "start"))

    router.callback_query.register(pick_type, AddOccasion.choosing_type, OccasionTypeCB.filter())
    # catch_all: within its state this accepts ANY text, so nav and commands
    # registered ahead of it are meant to win.
    router.message.register(
        enter_label, AddOccasion.entering_label, F.text, flags={"catch_all": True}
    )
    router.callback_query.register(pick_month, AddOccasion.choosing_month, MonthCB.filter())
    router.callback_query.register(pick_day, AddOccasion.choosing_day, DayCB.filter())
    router.message.register(
        enter_year, AddOccasion.entering_year, F.text, flags={"catch_all": True}
    )
    router.callback_query.register(
        skip_year, AddOccasion.entering_year, YearSkipCB.filter(F.action == "skip")
    )
    router.callback_query.register(confirm_save, AddOccasion.confirming, ConfirmCB.filter())

    # One Back per state.
    router.callback_query.register(back_from_type, AddOccasion.choosing_type, BackCB.filter())
    router.callback_query.register(back_from_label, AddOccasion.entering_label, BackCB.filter())
    router.callback_query.register(back_from_month, AddOccasion.choosing_month, BackCB.filter())
    router.callback_query.register(back_from_day, AddOccasion.choosing_day, BackCB.filter())
    router.callback_query.register(back_from_year, AddOccasion.entering_year, BackCB.filter())
    router.callback_query.register(back_from_confirm, AddOccasion.confirming, BackCB.filter())
    return router
