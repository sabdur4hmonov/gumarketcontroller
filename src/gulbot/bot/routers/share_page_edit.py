"""Editing a page after it is made: every text block, the date, the map, the
design, the language. THE LINK DOES NOT CHANGE -- the same row is updated in
place, so everyone who already has the link sees the new content.

WHO MAY EDIT WHAT. The page id rides in the buttons, so it is never trusted:
every handler re-loads the page with this shop and this customer
(`share_pages.update_page` scopes the write the same way, and refuses fields
the page's kind does not have). A Ha/Yo'q page is LOCKED once answered, and
the creator is told why: the answer was given to exactly that question.

Text steps are state-scoped catch_alls after nav and onboarding, like the
creation flow, so Cancel and /start still win; a button label is refused
rather than saved as text.
"""

from __future__ import annotations

import logging
from datetime import date, time
from decimal import Decimal
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.bot.callbacks import (
    EditFieldCB,
    EditValueCB,
    InviteDayCB,
    InviteHourCB,
    InviteMinuteCB,
    InviteMonthCB,
    MyPageCB,
    PageLangCB,
    PageTemplateCB,
)
from gulbot.bot.keyboards import main_menu_keyboard
from gulbot.bot.keyboards_pages import (
    INVITE_HOURS,
    INVITE_MINUTES,
    cancel_reply_keyboard,
    hour_keyboard,
    minute_keyboard,
    month_keyboard,
    page_day_keyboard,
    page_lang_keyboard,
    template_keyboard,
)
from gulbot.bot.routers.share_pages import _days, _months, _shop_today, _take_text, _target
from gulbot.bot.states import EditPage
from gulbot.i18n import t
from gulbot.models.customer import Customer
from gulbot.models.share_page import PageKind, SharePage
from gulbot.services import share_pages
from gulbot.services.share_pages import TEXT_FIELDS, EditRefused, effective_text
from gulbot.utils.render import escape
from gulbot.web import links, strings

log = logging.getLogger("gulbot.bot.share_page_edit")

#: Fields whose empty value means "the event type's preset".
PRESET_FIELDS = frozenset({"title", "message", "closing"})
#: Optional extras that may be removed outright.
CLEARABLE_FIELDS = frozenset({"name_2", "dress_code", "program", "contact"})


def _field_button(lang: str, page_id: int, field: str, label_key: str, **kw: str) -> list[Any]:
    return [
        InlineKeyboardButton(
            text=t(label_key, lang, **kw),
            callback_data=EditFieldCB(page_id=page_id, field=field).pack(),
        )
    ]


def edit_menu_keyboard(lang: str, page: SharePage) -> InlineKeyboardMarkup:
    yes, no = t("pages.word_yes", lang), t("pages.word_no", lang)
    rows: list[list[Any]] = []
    if page.kind == PageKind.YESNO:
        rows += [
            _field_button(lang, page.id, "question", "ibtn.pages.f_question"),
            _field_button(lang, page.id, "plan", "ibtn.pages.f_plan"),
            _field_button(
                lang,
                page.id,
                "notify_creator",
                "ibtn.pages.f_notify",
                state=yes if page.notify_creator else no,
            ),
        ]
    else:
        couple = page.event_type in strings.COUPLE_EVENTS
        rows.append(_field_button(lang, page.id, "title", "ibtn.pages.f_title"))
        if couple:
            rows.append(
                _field_button(lang, page.id, "name_1", "ibtn.pages.f_groom")
                + _field_button(lang, page.id, "name_2", "ibtn.pages.f_bride")
            )
        else:
            rows.append(_field_button(lang, page.id, "name_1", "ibtn.pages.f_name_1"))
        rows += [
            _field_button(lang, page.id, "message", "ibtn.pages.f_message"),
            _field_button(lang, page.id, "event_at", "ibtn.pages.f_event_at"),
            _field_button(lang, page.id, "venue", "ibtn.pages.f_venue")
            + _field_button(lang, page.id, "location", "ibtn.pages.f_location"),
            _field_button(lang, page.id, "dress_code", "ibtn.pages.f_dress_code")
            + _field_button(lang, page.id, "program", "ibtn.pages.f_program"),
            _field_button(lang, page.id, "contact", "ibtn.pages.f_contact")
            + _field_button(lang, page.id, "closing", "ibtn.pages.f_closing"),
            _field_button(
                lang,
                page.id,
                "rsvp_enabled",
                "ibtn.pages.f_rsvp",
                state=yes if page.rsvp_enabled else no,
            ),
        ]
    rows.append(
        _field_button(lang, page.id, "template", "ibtn.pages.f_template")
        + _field_button(lang, page.id, "lang", "ibtn.pages.f_lang")
    )
    rows.append(
        [
            InlineKeyboardButton(
                text=t("ibtn.pages.edit_done", lang),
                callback_data=MyPageCB(action="open", page_id=page.id).pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _value_keyboard(lang: str, field: str) -> InlineKeyboardMarkup:
    rows = []
    if field in PRESET_FIELDS:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t("ibtn.pages.edit_reset", lang),
                    callback_data=EditValueCB(action="reset").pack(),
                )
            ]
        )
    if field in CLEARABLE_FIELDS or field == "location":
        rows.append(
            [
                InlineKeyboardButton(
                    text=t("ibtn.pages.edit_clear", lang),
                    callback_data=EditValueCB(action="clear").pack(),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=t("ibtn.pages.edit_back", lang),
                callback_data=EditValueCB(action="back").pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _own(session: AsyncSession, customer: Customer, page_id: int) -> SharePage | None:
    return await share_pages.get_own_page(
        session, shop_id=customer.shop_id, customer_id=customer.id, page_id=page_id
    )


async def open_edit_menu(
    target: Message,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
    page_id: int,
) -> None:
    """The entry from "My pages", and where every edit returns to."""
    await state.clear()
    page = await _own(session, customer, page_id)
    if page is None:
        await target.answer(t("pages.gone", lang))
        return
    if page.kind == PageKind.YESNO and page.answered_at is not None:
        await target.answer(t("pages.edit_locked", lang))
        return
    await target.answer(t("pages.edit_menu", lang), reply_markup=edit_menu_keyboard(lang, page))


async def _save(
    target: Message,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
    page_id: int,
    changes: dict[str, object],
) -> None:
    await state.clear()
    try:
        page = await share_pages.update_page(
            session,
            shop_id=customer.shop_id,
            customer_id=customer.id,
            page_id=page_id,
            changes=changes,
        )
    except EditRefused as refused:
        await session.rollback()
        key = {"gone": "pages.gone", "locked": "pages.edit_locked"}.get(
            refused.reason, "pages.edit_invalid"
        )
        await target.answer(t(key, lang), reply_markup=main_menu_keyboard(lang))
        return
    await session.commit()
    await target.answer(
        t("pages.edit_saved", lang, url=escape(links.page_url(page.token))),
        reply_markup=main_menu_keyboard(lang),
        disable_web_page_preview=True,
    )
    await target.answer(t("pages.edit_menu", lang), reply_markup=edit_menu_keyboard(lang, page))


async def pick_field(
    callback: CallbackQuery,
    callback_data: EditFieldCB,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    await callback.answer()
    target = _target(callback)
    page = await _own(session, customer, callback_data.page_id)
    if page is None:
        await target.answer(t("pages.gone", lang))
        return
    field = callback_data.field
    plan = field == "plan" and page.kind == PageKind.YESNO
    if not plan and field not in share_pages.EDITABLE_FIELDS[page.kind]:
        return
    if page.kind == PageKind.YESNO and page.answered_at is not None:
        await target.answer(t("pages.edit_locked", lang))
        return
    if plan:
        from gulbot.bot.routers.share_page_plan import start_plan_edit

        await start_plan_edit(
            target, state, lang, page.id, await share_pages.has_plan(session, page_id=page.id)
        )
        return
    await state.clear()
    await state.update_data(edit_page_id=page.id, edit_field=field)

    if field in ("rsvp_enabled", "notify_creator"):
        await _save(
            target, state, session, customer, lang, page.id, {field: not getattr(page, field)}
        )
    elif field in TEXT_FIELDS:
        cap = TEXT_FIELDS[field][0]
        current = effective_text(page, field)
        prompt = t(
            "pages.edit_current",
            lang,
            current=escape(current) if current else t("pages.edit_empty_now", lang),
            max=cap,
        )
        if field == "contact":
            prompt = f"{prompt}\n\n{t('pages.edit_contact_hint', lang)}"
        await state.set_state(EditPage.entering_text)
        await target.answer("✍️", reply_markup=cancel_reply_keyboard(lang))
        await target.answer(prompt, reply_markup=_value_keyboard(lang, field))
    elif field == "event_at":
        today = await _shop_today(session, customer.shop_id)
        await state.set_state(EditPage.choosing_month)
        await target.answer(
            t("pages.choose_month", lang), reply_markup=month_keyboard(lang, _months(today))
        )
    elif field == "location":
        await state.set_state(EditPage.sending_location)
        await target.answer(
            t("pages.edit_location", lang), reply_markup=_value_keyboard(lang, field)
        )
    elif field == "template":
        await state.set_state(EditPage.choosing_template)
        await target.answer(
            t(
                "pages.choose_template",
                lang,
                gallery=escape(links.gallery_url(page.kind, page.lang)),
            ),
            reply_markup=template_keyboard(),
            disable_web_page_preview=True,
        )
    elif field == "lang":
        await state.set_state(EditPage.choosing_lang)
        await target.answer(t("pages.choose_lang", lang), reply_markup=page_lang_keyboard())


async def _editing(state: FSMContext) -> tuple[int, str] | None:
    data = await state.get_data()
    page_id, field = data.get("edit_page_id"), data.get("edit_field")
    if not isinstance(page_id, int) or not isinstance(field, str):
        return None
    return page_id, field


async def enter_text(
    message: Message, state: FSMContext, session: AsyncSession, customer: Customer, lang: str
) -> None:
    editing = await _editing(state)
    if editing is None or editing[1] not in TEXT_FIELDS:
        await state.clear()
        return
    page_id, field = editing
    cap, multiline, _ = TEXT_FIELDS[field]
    value = await _take_text(message, lang, cap, multiline=multiline)
    if value is None:
        return
    await _save(message, state, session, customer, lang, page_id, {field: value})


async def value_action(
    callback: CallbackQuery,
    callback_data: EditValueCB,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    await callback.answer()
    target = _target(callback)
    editing = await _editing(state)
    if editing is None:
        return
    page_id, field = editing
    action = callback_data.action
    if action == "back":
        await open_edit_menu(target, state, session, customer, lang, page_id)
    elif (action == "reset" and field in PRESET_FIELDS) or (
        action == "clear" and field in CLEARABLE_FIELDS
    ):
        await _save(target, state, session, customer, lang, page_id, {field: None})
    elif action == "clear" and field == "location":
        await _save(target, state, session, customer, lang, page_id, {"location": None})


async def edit_month(
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
    await state.update_data(year=chosen[0], month=chosen[1])
    await state.set_state(EditPage.choosing_day)
    await _target(callback).answer(
        t("pages.choose_day", lang), reply_markup=page_day_keyboard(_days(today, *chosen))
    )


async def edit_day(
    callback: CallbackQuery,
    callback_data: InviteDayCB,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    await callback.answer()
    data = await state.get_data()
    year, month = data.get("year"), data.get("month")
    if not isinstance(year, int) or not isinstance(month, int):
        return
    today = await _shop_today(session, customer.shop_id)
    if (year, month) not in _months(today) or callback_data.day not in _days(today, year, month):
        return
    await state.update_data(day=callback_data.day)
    await state.set_state(EditPage.choosing_hour)
    await _target(callback).answer(t("pages.choose_hour", lang), reply_markup=hour_keyboard())


async def edit_hour(
    callback: CallbackQuery, callback_data: InviteHourCB, state: FSMContext, lang: str
) -> None:
    await callback.answer()
    if callback_data.hour not in INVITE_HOURS:
        return
    await state.update_data(hour=callback_data.hour)
    await state.set_state(EditPage.choosing_minute)
    await _target(callback).answer(
        t("pages.choose_minute", lang), reply_markup=minute_keyboard(callback_data.hour)
    )


async def edit_minute(
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
    editing = await _editing(state)
    try:
        when = date(int(data["year"]), int(data["month"]), int(data["day"]))
        at = time(int(data["hour"]), callback_data.minute)
    except (KeyError, TypeError, ValueError):
        await state.clear()
        return
    if editing is None:
        return
    await _save(
        _target(callback), state, session, customer, lang, editing[0], {"event_at": (when, at)}
    )


async def edit_location(
    message: Message, state: FSMContext, session: AsyncSession, customer: Customer, lang: str
) -> None:
    editing = await _editing(state)
    point = message.location or (message.venue.location if message.venue else None)
    if editing is None or point is None:
        return
    lat = Decimal(str(round(point.latitude, 6)))
    lon = Decimal(str(round(point.longitude, 6)))
    await _save(message, state, session, customer, lang, editing[0], {"location": (lat, lon)})


async def edit_location_text(message: Message, lang: str) -> None:
    await message.answer(t("pages.edit_location", lang))


async def edit_template(
    callback: CallbackQuery,
    callback_data: PageTemplateCB,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    await callback.answer()
    editing = await _editing(state)
    if editing is None:
        return
    await _save(
        _target(callback),
        state,
        session,
        customer,
        lang,
        editing[0],
        {"template": callback_data.template},
    )


async def edit_lang(
    callback: CallbackQuery,
    callback_data: PageLangCB,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    await callback.answer()
    editing = await _editing(state)
    if editing is None:
        return
    await _save(
        _target(callback), state, session, customer, lang, editing[0], {"lang": callback_data.lang}
    )


def build_share_page_edit_router() -> Router:
    router = Router(name="share_page_edit")
    router.callback_query.register(pick_field, EditFieldCB.filter())
    router.callback_query.register(value_action, EditValueCB.filter())
    router.message.register(enter_text, EditPage.entering_text, F.text, flags={"catch_all": True})
    router.callback_query.register(edit_month, EditPage.choosing_month, InviteMonthCB.filter())
    router.callback_query.register(edit_day, EditPage.choosing_day, InviteDayCB.filter())
    router.callback_query.register(edit_hour, EditPage.choosing_hour, InviteHourCB.filter())
    router.callback_query.register(edit_minute, EditPage.choosing_minute, InviteMinuteCB.filter())
    router.message.register(edit_location, EditPage.sending_location, F.location | F.venue)
    router.message.register(
        edit_location_text, EditPage.sending_location, F.text, flags={"catch_all": True}
    )
    router.callback_query.register(
        edit_template, EditPage.choosing_template, PageTemplateCB.filter()
    )
    router.callback_query.register(edit_lang, EditPage.choosing_lang, PageLangCB.filter())
    return router
