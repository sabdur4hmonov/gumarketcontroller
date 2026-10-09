"""A Ha/Yo'q page's DATE PLAN, made in the bot (CP17).

After the question: "add a date plan?" Then 1-5 places (typed -- they are the
creator's own words) and 1-5 times (pickers: month, day, hour, minute, never
typed). The recipient later picks one of each.

The same steps serve EDITING: started from the edit menu with `edit_page_id`
in the FSM data, they end by replacing the page's plan in place instead of
moving on to the design. Locked once the page is answered, like every edit.

Every value is re-checked: a month in the window, a day that exists and has
not passed, an hour that is still ahead today, a minute that was offered, no
duplicates, at most five of each. The service checks the plan again.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.bot.callbacks import (
    InviteDayCB,
    InviteHourCB,
    InviteMinuteCB,
    InviteMonthCB,
    PlanCB,
)
from gulbot.bot.keyboards import main_menu_keyboard
from gulbot.bot.keyboards_pages import (
    INVITE_HOURS,
    INVITE_MINUTES,
    cancel_reply_keyboard,
    minute_keyboard,
    month_keyboard,
    page_day_keyboard,
)
from gulbot.bot.routers.share_pages import (
    _ask_template,
    _days,
    _months,
    _shop_today,
    _take_text,
    _target,
)
from gulbot.bot.states import YesNoPage
from gulbot.i18n import t
from gulbot.models.customer import Customer
from gulbot.models.share_page import PLACE_MAX, PLAN_MAX
from gulbot.models.shop import Shop
from gulbot.services import share_pages
from gulbot.services.share_pages import EditRefused
from gulbot.utils.render import escape
from gulbot.web import links


def _button(lang: str, key: str, action: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=t(key, lang), callback_data=PlanCB(action=action).pack())


def ask_plan_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button(lang, "ibtn.pages.plan_add", "add")],
            [_button(lang, "ibtn.pages.plan_skip", "skip")],
        ]
    )


def _after_place_keyboard(lang: str, count: int) -> InlineKeyboardMarkup:
    rows = []
    if count < PLAN_MAX:
        rows.append([_button(lang, "ibtn.pages.more_place", "more_place")])
    rows.append([_button(lang, "ibtn.pages.places_done", "places_done")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _after_slot_keyboard(lang: str, count: int) -> InlineKeyboardMarkup:
    rows = []
    if count < PLAN_MAX:
        rows.append([_button(lang, "ibtn.pages.more_slot", "more_slot")])
    rows.append([_button(lang, "ibtn.pages.slots_done", "slots_done")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _hours_keyboard(hours: list[int]) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=f"{h:02d}:__", callback_data=InviteHourCB(hour=h).pack())
        for h in hours
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[buttons[i : i + 4] for i in range(0, len(buttons), 4)]
    )


async def _tz(session: AsyncSession, shop_id: int) -> ZoneInfo:
    name = await session.scalar(select(Shop.timezone).where(Shop.id == shop_id))
    return ZoneInfo(name or "Asia/Tashkent")


async def _offered_hours(
    session: AsyncSession, customer: Customer, year: int, month: int, day: int
) -> list[int]:
    """Hours still ahead: all of them on a later day, only the coming ones today."""
    tz = await _tz(session, customer.shop_id)
    now = datetime.now(tz)
    if (year, month, day) == (now.year, now.month, now.day):
        return [h for h in INVITE_HOURS if h > now.hour]
    return list(INVITE_HOURS)


async def ask_plan(target: Message, state: FSMContext, lang: str) -> None:
    """The step after the question, in creation."""
    await state.update_data(places=[], slots=[])
    await state.set_state(YesNoPage.asking_plan)
    await target.answer(t("pages.ask_plan", lang), reply_markup=ask_plan_keyboard(lang))


async def start_plan_edit(
    target: Message, state: FSMContext, lang: str, page_id: int, has_plan: bool
) -> None:
    """From the edit menu: build a new plan for this page, or remove it."""
    await state.clear()
    await state.update_data(edit_page_id=page_id, places=[], slots=[])
    if has_plan:
        await target.answer(
            t("pages.ask_plan", lang),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [_button(lang, "ibtn.pages.plan_add", "add")],
                    [_button(lang, "ibtn.pages.plan_remove", "remove")],
                ]
            ),
        )
        await state.set_state(YesNoPage.asking_plan)
        return
    await _ask_place(target, state, lang)


async def _ask_place(target: Message, state: FSMContext, lang: str) -> None:
    data = await state.get_data()
    n = len(data.get("places") or []) + 1
    await state.set_state(YesNoPage.entering_place)
    await target.answer("📍", reply_markup=cancel_reply_keyboard(lang))
    await target.answer(t("pages.enter_place", lang, n=n, max=PLAN_MAX))


async def _ask_slot_month(
    target: Message, state: FSMContext, session: AsyncSession, customer: Customer, lang: str
) -> None:
    data = await state.get_data()
    n = len(data.get("slots") or []) + 1
    today = await _shop_today(session, customer.shop_id)
    await state.set_state(YesNoPage.plan_month)
    await target.answer(
        t("pages.choose_slot_month", lang, n=n, max=PLAN_MAX),
        reply_markup=month_keyboard(lang, _months(today)),
    )


async def plan_action(
    callback: CallbackQuery,
    callback_data: PlanCB,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    await callback.answer()
    target = _target(callback)
    current = await state.get_state()
    data = await state.get_data()
    action = callback_data.action
    places: list[str] = list(data.get("places") or [])
    slots: list[str] = list(data.get("slots") or [])
    if current == YesNoPage.asking_plan.state:
        if action == "add":
            await _ask_place(target, state, lang)
        elif action == "skip" and "edit_page_id" not in data:
            await state.update_data(places=[], slots=[])
            await _ask_template(target, state, lang, YesNoPage.choosing_template, "yesno")
        elif action == "remove" and "edit_page_id" in data:
            await _finish_edit(target, state, session, customer, lang, (), ())
    elif current == YesNoPage.after_place.state:
        if action == "more_place" and len(places) < PLAN_MAX:
            await _ask_place(target, state, lang)
        elif action == "places_done" and places:
            await _ask_slot_month(target, state, session, customer, lang)
    elif current == YesNoPage.after_slot.state:
        if action == "more_slot" and len(slots) < PLAN_MAX:
            await _ask_slot_month(target, state, session, customer, lang)
        elif action == "slots_done" and slots:
            if "edit_page_id" in data:
                await _finish_edit(
                    target,
                    state,
                    session,
                    customer,
                    lang,
                    tuple(places),
                    tuple(datetime.fromisoformat(s) for s in slots),
                )
            else:
                await _ask_template(target, state, lang, YesNoPage.choosing_template, "yesno")


async def enter_place(message: Message, state: FSMContext, lang: str) -> None:
    place = await _take_text(message, lang, PLACE_MAX)
    if place is None:
        return
    data = await state.get_data()
    places: list[str] = list(data.get("places") or [])
    if place in places:
        await message.answer(t("pages.place_duplicate", lang))
        return
    places.append(place)
    await state.update_data(places=places)
    await state.set_state(YesNoPage.after_place)
    await message.answer("👌", reply_markup=main_menu_keyboard(lang))
    await message.answer(
        t("pages.place_added", lang, place=escape(place)),
        reply_markup=_after_place_keyboard(lang, len(places)),
    )


async def slot_month(
    callback: CallbackQuery,
    callback_data: InviteMonthCB,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    await callback.answer()
    today = await _shop_today(session, customer.shop_id)
    chosen = (callback_data.year, callback_data.month)
    if chosen not in _months(today):
        return
    await state.update_data(slot_year=chosen[0], slot_month=chosen[1])
    await state.set_state(YesNoPage.plan_day)
    await _target(callback).answer(
        t("pages.choose_day", lang), reply_markup=page_day_keyboard(_days(today, *chosen))
    )


async def slot_day(
    callback: CallbackQuery,
    callback_data: InviteDayCB,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    await callback.answer()
    data = await state.get_data()
    year, month = data.get("slot_year"), data.get("slot_month")
    if not isinstance(year, int) or not isinstance(month, int):
        return
    today = await _shop_today(session, customer.shop_id)
    if (year, month) not in _months(today) or callback_data.day not in _days(today, year, month):
        return
    hours = await _offered_hours(session, customer, year, month, callback_data.day)
    if not hours:
        await _target(callback).answer(t("pages.slot_day_over", lang))
        return
    await state.update_data(slot_day=callback_data.day)
    await state.set_state(YesNoPage.plan_hour)
    await _target(callback).answer(
        t("pages.choose_hour", lang), reply_markup=_hours_keyboard(hours)
    )


async def slot_hour(
    callback: CallbackQuery,
    callback_data: InviteHourCB,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    await callback.answer()
    data = await state.get_data()
    try:
        hours = await _offered_hours(
            session,
            customer,
            int(data["slot_year"]),
            int(data["slot_month"]),
            int(data["slot_day"]),
        )
    except (KeyError, TypeError, ValueError):
        return
    if callback_data.hour not in hours:
        return
    await state.update_data(slot_hour=callback_data.hour)
    await state.set_state(YesNoPage.plan_minute)
    await _target(callback).answer(
        t("pages.choose_minute", lang), reply_markup=minute_keyboard(callback_data.hour)
    )


async def slot_minute(
    callback: CallbackQuery,
    callback_data: InviteMinuteCB,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    await callback.answer()
    if callback_data.minute not in INVITE_MINUTES:
        return
    data = await state.get_data()
    tz = await _tz(session, customer.shop_id)
    try:
        moment = datetime(
            int(data["slot_year"]),
            int(data["slot_month"]),
            int(data["slot_day"]),
            int(data["slot_hour"]),
            callback_data.minute,
            tzinfo=tz,
        )
    except (KeyError, TypeError, ValueError):
        return
    if moment <= datetime.now(UTC):
        await _target(callback).answer(t("pages.slot_day_over", lang))
        return
    slots: list[str] = list(data.get("slots") or [])
    iso = moment.astimezone(UTC).isoformat()
    if iso in slots:
        await _target(callback).answer(t("pages.slot_duplicate", lang))
        return
    slots.append(iso)
    await state.update_data(slots=slots)
    await state.set_state(YesNoPage.after_slot)
    await _target(callback).answer(
        t("pages.slot_added", lang, when=moment.strftime("%d.%m.%Y %H:%M")),
        reply_markup=_after_slot_keyboard(lang, len(slots)),
    )


async def _finish_edit(
    target: Message,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
    places: tuple[str, ...],
    slots: tuple[datetime, ...],
) -> None:
    from gulbot.bot.routers.share_page_edit import edit_menu_keyboard

    data = await state.get_data()
    await state.clear()
    try:
        page = await share_pages.set_plan(
            session,
            shop_id=customer.shop_id,
            customer_id=customer.id,
            page_id=int(data["edit_page_id"]),
            places=places,
            slots=slots,
        )
    except EditRefused as refused:
        await session.rollback()
        key = {
            "gone": "pages.gone",
            "locked": "pages.edit_locked",
            "premium": "premium.locked",
        }.get(refused.reason, "pages.edit_invalid")
        await target.answer(t(key, lang), reply_markup=main_menu_keyboard(lang))
        return
    await session.commit()
    await target.answer(
        t("pages.edit_saved", lang, url=escape(links.page_url(page.token))),
        reply_markup=main_menu_keyboard(lang),
        disable_web_page_preview=True,
    )
    await target.answer(t("pages.edit_menu", lang), reply_markup=edit_menu_keyboard(lang, page))


def plan_summary(data: dict[str, Any], lang: str, tz: ZoneInfo) -> str:
    """For the confirm step: the places, then the times, or "no"."""
    places = list(data.get("places") or [])
    slots = [datetime.fromisoformat(s).astimezone(tz) for s in data.get("slots") or []]
    if not places or not slots:
        return t("pages.word_no", lang)
    return f"{', '.join(escape(p) for p in places)} · " + ", ".join(
        s.strftime("%d.%m %H:%M") for s in slots
    )


def slot_times(data: dict[str, Any]) -> tuple[datetime, ...]:
    return tuple(datetime.fromisoformat(s) for s in data.get("slots") or [])


def build_share_page_plan_router() -> Router:
    router = Router(name="share_page_plan")
    router.callback_query.register(plan_action, PlanCB.filter())
    router.message.register(
        enter_place, YesNoPage.entering_place, F.text, flags={"catch_all": True}
    )
    router.callback_query.register(slot_month, YesNoPage.plan_month, InviteMonthCB.filter())
    router.callback_query.register(slot_day, YesNoPage.plan_day, InviteDayCB.filter())
    router.callback_query.register(slot_hour, YesNoPage.plan_hour, InviteHourCB.filter())
    router.callback_query.register(slot_minute, YesNoPage.plan_minute, InviteMinuteCB.filter())
    return router
