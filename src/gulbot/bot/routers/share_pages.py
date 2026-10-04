"""Ha/Yo'q pages and taklifnomas, made in the shop's bot, shared as a link.

PICKERS WHEREVER POSSIBLE -- the rule since CP3. Free text is asked for only
where nothing else can work: the customer's own question, names, the venue and
an optional message. Each of those states is a `catch_all` on purpose and sits
after nav and onboarding, so Cancel and /start still win from inside it (the
shadow sweep enforces that). A button label typed into one of them is refused
rather than stored as a name.

EVERY CALLBACK VALUE IS CHECKED AGAINST THE SET ITS KEYBOARD WAS BUILT FROM,
not trusted because a keyboard offered it -- the crafted-callback finding of
the pre-deployment audit. Languages, questions, designs and event types are
membership tests; a month must be inside the window, a day must exist in that
month and not be past, an hour and a minute must be ones offered. A page id is
only ever looked up with this shop AND this customer (see services/share_pages.py),
so a crafted MyPageCB can neither read nor delete anyone else's page.

THE SHOP IS THE DISPATCHER'S. `customer.shop_id` comes from the middleware bound
to this shop's dispatcher, and the link back on the page is this bot's own
username -- so a page made in shop A's bot sends its visitors to shop A.
"""

from __future__ import annotations

import contextlib
import logging
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.bot.callbacks import (
    InviteDayCB,
    InviteEventCB,
    InviteHourCB,
    InviteMinuteCB,
    InviteMonthCB,
    MyPageCB,
    PageChoiceCB,
    PageConfirmCB,
    PageLangCB,
    PageMenuCB,
    PageQuestionCB,
    PageSkipCB,
    PageTemplateCB,
)
from gulbot.bot.keyboards import main_menu_keyboard
from gulbot.bot.keyboards_pages import (
    INVITE_HOURS,
    INVITE_MINUTES,
    cancel_reply_keyboard,
    confirm_keyboard,
    event_keyboard,
    hour_keyboard,
    link_keyboard,
    minute_keyboard,
    month_keyboard,
    my_page_keyboard,
    my_pages_keyboard,
    page_day_keyboard,
    page_lang_keyboard,
    pages_menu_keyboard,
    question_keyboard,
    skip_keyboard,
    template_keyboard,
    toggle_keyboard,
)
from gulbot.bot.states import InvitePage, YesNoPage
from gulbot.i18n import button_labels, t
from gulbot.i18n.catalog import CATALOG
from gulbot.models.customer import Customer
from gulbot.models.share_page import (
    EVENT_TYPES,
    MESSAGE_MAX,
    NAME_MAX,
    PAGE_LANGUAGES,
    PAGE_TEMPLATES,
    QUESTION_MAX,
    QUESTION_PRESETS,
    VENUE_MAX,
    PageKind,
    SharePage,
)
from gulbot.models.shop import Shop
from gulbot.services import share_pages
from gulbot.services.share_pages import InviteDraft, PageLimitReached, YesNoDraft, clean_text
from gulbot.utils.render import escape
from gulbot.web import links, strings
from gulbot.web.render import THEME_NAMES

log = logging.getLogger("gulbot.bot.share_pages")

NL_ = chr(10)

PAGES_LABELS = set(CATALOG["btn.menu.pages"].values())

LANG_NAMES = {
    "uz": "O'zbekcha (lotin)",
    "uz_cyrl": "Ўзбекча (кирилл)",
    "ru": "Русский",
    "en": "English",
}


# --- helpers ---------------------------------------------------------------


def _target(callback: CallbackQuery) -> Message:
    message = callback.message
    if message is None:  # pragma: no cover - Telegram always attaches one
        raise RuntimeError("callback without a message")
    return message  # type: ignore[return-value]


async def _shop_today(session: AsyncSession, shop_id: int) -> date:
    name = await session.scalar(select(Shop.timezone).where(Shop.id == shop_id))
    return datetime.now(ZoneInfo(name or "Asia/Tashkent")).date()


def _months(today: date) -> list[tuple[int, int]]:
    first, last = share_pages.event_window(today)
    months, year, month = [], first.year, first.month
    while (year, month) <= (last.year, last.month):
        months.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def _days(today: date, year: int, month: int) -> list[int]:
    first, last = share_pages.event_window(today)
    days = []
    for day in range(1, 32):
        try:
            candidate = date(year, month, day)
        except ValueError:
            break
        if first <= candidate <= last:
            days.append(day)
    return days


async def _bot_username(bot: Bot | None) -> str | None:
    """This shop's bot, as t.me knows it. The page links back to it."""
    if bot is None:
        return None
    try:
        me = await bot.me()
    except Exception:  # a failed getMe must not lose the page
        log.warning("could not read the bot's username; the page will have no shop link")
        return None
    return me.username


def _expires_text(page: SharePage, tz: ZoneInfo) -> str:
    return page.expires_at.astimezone(tz).strftime("%d.%m.%Y")


async def _send_link(message: Message, session: AsyncSession, page: SharePage, lang: str) -> None:
    tz = ZoneInfo(
        await session.scalar(select(Shop.timezone).where(Shop.id == page.shop_id))
        or "Asia/Tashkent"
    )
    url = links.page_url(page.token)
    await message.answer(
        t("pages.created", lang, url=escape(url), expires=_expires_text(page, tz)),
        reply_markup=link_keyboard(lang, url),
        disable_web_page_preview=False,
    )
    await message.answer(t("menu.title", lang), reply_markup=main_menu_keyboard(lang))


def _refuse_label(text: str | None) -> bool:
    """A reply-keyboard button pressed while we wait for a name is not a name."""
    return text is None or text.strip() in button_labels() or text.strip().startswith("/")


async def _take_text(
    message: Message, lang: str, limit: int, *, multiline: bool = False
) -> str | None:
    if _refuse_label(message.text):
        await message.answer(t("pages.text_empty", lang))
        return None
    value = clean_text(message.text, limit, multiline=multiline)
    if value is None:
        await message.answer(t("pages.text_empty", lang))
        return None
    if len((message.text or "").strip()) > limit:
        await message.answer(t("pages.text_trimmed", lang, max=limit))
    return value


# --- entry -----------------------------------------------------------------


async def open_menu(message: Message, state: FSMContext, lang: str) -> None:
    await state.clear()
    if not links.pages_available():
        await message.answer(t("pages.unavailable", lang))
        return
    await message.answer(t("pages.menu", lang), reply_markup=pages_menu_keyboard(lang))


async def menu_choice(
    callback: CallbackQuery,
    callback_data: PageMenuCB,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    await callback.answer()
    target = _target(callback)
    await state.clear()
    if not links.pages_available():
        await target.answer(t("pages.unavailable", lang))
        return
    if callback_data.action == "mine":
        await _show_list(target, session, customer, lang)
        return
    if callback_data.action == PageKind.YESNO:
        await state.update_data(kind=PageKind.YESNO.value)
        await state.set_state(YesNoPage.choosing_lang)
        await target.answer(t("pages.choose_lang", lang), reply_markup=page_lang_keyboard())
        return
    if callback_data.action == PageKind.INVITE:
        await state.update_data(kind=PageKind.INVITE.value)
        await state.set_state(InvitePage.choosing_event)
        await target.answer(t("pages.choose_event", lang), reply_markup=event_keyboard(lang))


# --- Ha/Yo'q ---------------------------------------------------------------


async def yesno_lang(
    callback: CallbackQuery, callback_data: PageLangCB, state: FSMContext, lang: str
) -> None:
    await callback.answer()
    if callback_data.lang not in PAGE_LANGUAGES:
        return
    await state.update_data(page_lang=callback_data.lang)
    await state.set_state(YesNoPage.choosing_question)
    await _target(callback).answer(
        t("pages.choose_question", lang), reply_markup=question_keyboard(lang, callback_data.lang)
    )


async def yesno_question(
    callback: CallbackQuery, callback_data: PageQuestionCB, state: FSMContext, lang: str
) -> None:
    await callback.answer()
    preset = callback_data.preset
    if preset not in QUESTION_PRESETS:
        return
    data = await state.get_data()
    page_lang = data.get("page_lang")
    if page_lang not in PAGE_LANGUAGES:
        return
    if preset == "custom":
        await state.update_data(preset="custom")
        await state.set_state(YesNoPage.entering_question)
        await _target(callback).answer(
            t("pages.enter_question", lang, max=QUESTION_MAX),
            reply_markup=cancel_reply_keyboard(lang),
        )
        return
    await state.update_data(preset=preset, question=strings.question(preset, page_lang))
    from gulbot.bot.routers.share_page_plan import ask_plan

    await ask_plan(_target(callback), state, lang)


async def yesno_enter_question(message: Message, state: FSMContext, lang: str) -> None:
    question = await _take_text(message, lang, QUESTION_MAX)
    if question is None:
        return
    await state.update_data(question=question)
    await message.answer("✍️", reply_markup=main_menu_keyboard(lang))
    from gulbot.bot.routers.share_page_plan import ask_plan

    await ask_plan(message, state, lang)


async def _ask_template(
    target: Message, state: FSMContext, lang: str, next_state: Any, kind: str
) -> None:
    data = await state.get_data()
    page_lang = data.get("page_lang", "uz")
    await state.set_state(next_state)
    await target.answer(
        t("pages.choose_template", lang, gallery=escape(links.gallery_url(kind, page_lang))),
        reply_markup=template_keyboard(),
        disable_web_page_preview=True,
    )


async def yesno_template(
    callback: CallbackQuery, callback_data: PageTemplateCB, state: FSMContext, lang: str
) -> None:
    await callback.answer()
    if callback_data.template not in PAGE_TEMPLATES:
        return
    await state.update_data(template=callback_data.template, photo_file_id=None)
    if callback_data.template == "foto":
        from gulbot.bot.routers.share_page_photo import ask_photo

        await ask_photo(_target(callback), state, lang, YesNoPage.sending_photo)
        return
    await ask_notify(_target(callback), state, lang)


async def ask_notify(target: Message, state: FSMContext, lang: str) -> None:
    await state.set_state(YesNoPage.choosing_notify)
    await target.answer(t("pages.ask_notify", lang), reply_markup=toggle_keyboard(lang, "notify"))


async def yesno_notify(
    callback: CallbackQuery,
    callback_data: PageChoiceCB,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    await callback.answer()
    if callback_data.field != "notify" or callback_data.value not in ("yes", "no"):
        return
    await state.update_data(notify=callback_data.value == "yes")
    data = await state.get_data()
    if not _yesno_ready(data):
        await state.clear()
        await _target(callback).answer(t("pages.cancelled", lang))
        return
    await state.set_state(YesNoPage.confirming)
    await _target(callback).answer(
        t(
            "pages.confirm_yesno",
            lang,
            question=escape(data["question"]),
            lang_name=LANG_NAMES[data["page_lang"]],
            template=THEME_NAMES[data["template"]],
            notify=t("pages.word_yes" if data["notify"] else "pages.word_no", lang),
            plan=plan_summary(data, lang, await _shop_zone(session, customer.shop_id)),
        ),
        reply_markup=confirm_keyboard(lang),
    )


async def _shop_zone(session: AsyncSession, shop_id: int) -> ZoneInfo:
    name = await session.scalar(select(Shop.timezone).where(Shop.id == shop_id))
    return ZoneInfo(name or "Asia/Tashkent")


def plan_summary(data: dict[str, Any], lang: str, tz: ZoneInfo) -> str:
    from gulbot.bot.routers import share_page_plan

    return share_page_plan.plan_summary(data, lang, tz)


def _yesno_ready(data: dict[str, Any]) -> bool:
    return (
        data.get("page_lang") in PAGE_LANGUAGES
        and data.get("preset") in QUESTION_PRESETS
        and isinstance(data.get("question"), str)
        and data.get("template") in PAGE_TEMPLATES
        and isinstance(data.get("notify"), bool)
    )


# --- Taklifnoma --------------------------------------------------------------


async def invite_event(
    callback: CallbackQuery, callback_data: InviteEventCB, state: FSMContext, lang: str
) -> None:
    await callback.answer()
    if callback_data.event not in EVENT_TYPES:
        return
    await state.update_data(event=callback_data.event)
    await state.set_state(InvitePage.choosing_lang)
    await _target(callback).answer(t("pages.choose_lang", lang), reply_markup=page_lang_keyboard())


async def invite_lang(
    callback: CallbackQuery, callback_data: PageLangCB, state: FSMContext, lang: str
) -> None:
    await callback.answer()
    if callback_data.lang not in PAGE_LANGUAGES:
        return
    await state.update_data(page_lang=callback_data.lang)
    data = await state.get_data()
    couple = data.get("event") in strings.COUPLE_EVENTS
    await state.set_state(InvitePage.entering_name_1)
    await _target(callback).answer(
        t("pages.enter_couple_1" if couple else "pages.enter_name_single", lang, max=NAME_MAX),
        reply_markup=cancel_reply_keyboard(lang),
    )


async def invite_name_1(
    message: Message, state: FSMContext, session: AsyncSession, customer: Customer, lang: str
) -> None:
    name = await _take_text(message, lang, NAME_MAX)
    if name is None:
        return
    await state.update_data(name_1=name)
    data = await state.get_data()
    if data.get("event") in strings.COUPLE_EVENTS:
        await state.set_state(InvitePage.entering_name_2)
        await message.answer(t("pages.enter_couple_2", lang, max=NAME_MAX))
        return
    await state.update_data(name_2=None)
    await _ask_month(message, state, session, customer, lang)


async def invite_name_2(
    message: Message, state: FSMContext, session: AsyncSession, customer: Customer, lang: str
) -> None:
    name = await _take_text(message, lang, NAME_MAX)
    if name is None:
        return
    await state.update_data(name_2=name)
    await _ask_month(message, state, session, customer, lang)


async def _ask_month(
    message: Message, state: FSMContext, session: AsyncSession, customer: Customer, lang: str
) -> None:
    today = await _shop_today(session, customer.shop_id)
    await state.set_state(InvitePage.choosing_month)
    await message.answer("📅", reply_markup=main_menu_keyboard(lang))
    await message.answer(
        t("pages.choose_month", lang), reply_markup=month_keyboard(lang, _months(today))
    )


async def invite_month(
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
    days = _days(today, *chosen)
    await state.update_data(year=chosen[0], month=chosen[1])
    await state.set_state(InvitePage.choosing_day)
    await _target(callback).answer(
        t("pages.choose_day", lang), reply_markup=page_day_keyboard(days)
    )


async def invite_day(
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
    await state.set_state(InvitePage.choosing_hour)
    await _target(callback).answer(t("pages.choose_hour", lang), reply_markup=hour_keyboard())


async def invite_hour(
    callback: CallbackQuery, callback_data: InviteHourCB, state: FSMContext, lang: str
) -> None:
    await callback.answer()
    if callback_data.hour not in INVITE_HOURS:
        return
    await state.update_data(hour=callback_data.hour)
    await state.set_state(InvitePage.choosing_minute)
    await _target(callback).answer(
        t("pages.choose_minute", lang), reply_markup=minute_keyboard(callback_data.hour)
    )


async def invite_minute(
    callback: CallbackQuery, callback_data: InviteMinuteCB, state: FSMContext, lang: str
) -> None:
    await callback.answer()
    if callback_data.minute not in INVITE_MINUTES:
        return
    await state.update_data(minute=callback_data.minute)
    await state.set_state(InvitePage.entering_venue)
    await _target(callback).answer(
        t("pages.enter_venue", lang, max=VENUE_MAX), reply_markup=cancel_reply_keyboard(lang)
    )


async def invite_venue(message: Message, state: FSMContext, lang: str) -> None:
    venue = await _take_text(message, lang, VENUE_MAX)
    if venue is None:
        return
    await state.update_data(venue=venue)
    await state.set_state(InvitePage.sending_location)
    await message.answer("📍", reply_markup=main_menu_keyboard(lang))
    await message.answer(
        t("pages.ask_location", lang), reply_markup=skip_keyboard(lang, "location")
    )


async def invite_location(message: Message, state: FSMContext, lang: str) -> None:
    point = message.location or (message.venue.location if message.venue else None)
    if point is None:  # pragma: no cover - the filter admits only these two
        return
    lat = Decimal(str(round(point.latitude, 6)))
    lon = Decimal(str(round(point.longitude, 6)))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return
    await state.update_data(lat=str(lat), lon=str(lon))
    await message.answer(t("pages.location_saved", lang))
    await _ask_message(message, state, lang)


async def invite_location_text(message: Message, lang: str) -> None:
    """Typed text where a map pin was asked for: say how, do not guess."""
    await message.answer(
        t("pages.ask_location", lang), reply_markup=skip_keyboard(lang, "location")
    )


async def _ask_message(target: Message, state: FSMContext, lang: str) -> None:
    await state.set_state(InvitePage.entering_message)
    await target.answer(
        t("pages.enter_message", lang, max=MESSAGE_MAX), reply_markup=skip_keyboard(lang, "message")
    )


async def invite_skip(
    callback: CallbackQuery, callback_data: PageSkipCB, state: FSMContext, lang: str
) -> None:
    await callback.answer()
    current = await state.get_state()
    if callback_data.step == "location" and current == InvitePage.sending_location.state:
        await state.update_data(lat=None, lon=None)
        await _ask_message(_target(callback), state, lang)
    elif callback_data.step == "message" and current == InvitePage.entering_message.state:
        await state.update_data(message=None)
        await _ask_rsvp(_target(callback), state, lang)


async def invite_message(message: Message, state: FSMContext, lang: str) -> None:
    text = await _take_text(message, lang, MESSAGE_MAX, multiline=True)
    if text is None:
        return
    await state.update_data(message=text)
    await _ask_rsvp(message, state, lang)


async def _ask_rsvp(target: Message, state: FSMContext, lang: str) -> None:
    await state.set_state(InvitePage.choosing_rsvp)
    await target.answer(t("pages.ask_rsvp", lang), reply_markup=toggle_keyboard(lang, "rsvp"))


async def invite_rsvp(
    callback: CallbackQuery, callback_data: PageChoiceCB, state: FSMContext, lang: str
) -> None:
    await callback.answer()
    if callback_data.field != "rsvp" or callback_data.value not in ("yes", "no"):
        return
    await state.update_data(rsvp=callback_data.value == "yes")
    await _ask_template(_target(callback), state, lang, InvitePage.choosing_template, "invite")


async def invite_template(
    callback: CallbackQuery, callback_data: PageTemplateCB, state: FSMContext, lang: str
) -> None:
    await callback.answer()
    if callback_data.template not in PAGE_TEMPLATES:
        return
    await state.update_data(template=callback_data.template, photo_file_id=None)
    if callback_data.template == "foto":
        from gulbot.bot.routers.share_page_photo import ask_photo

        await ask_photo(_target(callback), state, lang, InvitePage.sending_photo)
        return
    await invite_summary(_target(callback), state, lang)


async def invite_summary(target: Message, state: FSMContext, lang: str) -> None:
    data = await state.get_data()
    draft = _invite_draft(data)
    if draft is None:
        await state.clear()
        await target.answer(t("pages.cancelled", lang))
        return
    names = draft.name_1 + (f" & {draft.name_2}" if draft.name_2 else "")
    await state.set_state(InvitePage.confirming)
    await target.answer(
        t(
            "pages.confirm_invite",
            lang,
            event=escape(t(f"ibtn.event.{draft.event_type}", lang)),
            names=escape(names),
            date=draft.event_date.strftime("%d.%m.%Y"),
            time=draft.event_time.strftime("%H:%M"),
            venue=escape(draft.venue),
            pin=t("pages.word_pin", lang) if draft.location else "",
            message=escape(draft.message) if draft.message else t("pages.word_default_text", lang),
            rsvp=t("pages.word_yes" if draft.rsvp_enabled else "pages.word_no", lang),
            lang_name=LANG_NAMES[draft.lang],
            template=THEME_NAMES[draft.template],
        ),
        reply_markup=confirm_keyboard(lang),
    )


def _invite_draft(data: dict[str, Any]) -> InviteDraft | None:
    try:
        when = date(int(data["year"]), int(data["month"]), int(data["day"]))
        at = time(int(data["hour"]), int(data["minute"]))
        location = (
            (Decimal(data["lat"]), Decimal(data["lon"]))
            if data.get("lat") is not None and data.get("lon") is not None
            else None
        )
        draft = InviteDraft(
            template=str(data["template"]),
            lang=str(data["page_lang"]),
            event_type=str(data["event"]),
            name_1=str(data["name_1"]),
            name_2=data.get("name_2"),
            event_date=when,
            event_time=at,
            venue=str(data["venue"]),
            location=location,
            message=data.get("message"),
            rsvp_enabled=bool(data.get("rsvp")),
        )
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return None
    if (
        draft.template not in PAGE_TEMPLATES
        or draft.lang not in PAGE_LANGUAGES
        or draft.event_type not in EVENT_TYPES
    ):
        return None
    return draft


# --- confirm ----------------------------------------------------------------


async def confirm(
    callback: CallbackQuery,
    callback_data: PageConfirmCB,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    await callback.answer()
    target = _target(callback)
    data = await state.get_data()
    # Whatever happens next, this conversation is over: a double tap on
    # "Yaratish" finds no state and does nothing.
    await state.clear()
    # Take the buttons off the summary; cosmetic, so a refusal is ignored.
    with contextlib.suppress(Exception):
        await target.edit_reply_markup(reply_markup=None)
    if callback_data.action != "create":
        await target.answer(t("pages.cancelled", lang), reply_markup=main_menu_keyboard(lang))
        return

    draft: YesNoDraft | InviteDraft | None
    if data.get("kind") == PageKind.YESNO and _yesno_ready(data):
        from gulbot.bot.routers.share_page_plan import slot_times

        draft = YesNoDraft(
            template=data["template"],
            lang=data["page_lang"],
            question_preset=data["preset"],
            question=data["question"],
            notify_creator=data["notify"],
            places=tuple(data.get("places") or ()),
            slots=slot_times(data),
        )
    elif data.get("kind") == PageKind.INVITE:
        draft = _invite_draft(data)
    else:
        draft = None
    if draft is None:
        await target.answer(t("pages.cancelled", lang), reply_markup=main_menu_keyboard(lang))
        return

    try:
        page = await share_pages.create_page(
            session,
            shop_id=customer.shop_id,
            customer_id=customer.id,
            bot_username=await _bot_username(callback.bot),
            draft=draft,
            now=datetime.now(UTC),
        )
    except PageLimitReached as limit:
        n = share_pages.CREATE_PER_DAY if limit.which == "daily" else share_pages.LIVE_PER_CUSTOMER
        await target.answer(
            t(f"pages.limit_{limit.which}", lang, n=n), reply_markup=main_menu_keyboard(lang)
        )
        return
    except share_pages.InvalidDraft as bad:
        log.warning("refused a page draft: %s", bad)
        await target.answer(t("pages.cancelled", lang), reply_markup=main_menu_keyboard(lang))
        return
    await session.commit()
    if data.get("photo_file_id") and page.template == "foto":
        from gulbot.bot.routers.share_page_photo import store_after_create

        await store_after_create(
            callback.bot, target, session, customer, page.id, data["photo_file_id"], lang
        )
    await _send_link(target, session, page, lang)


# --- my pages -------------------------------------------------------------------


async def _show_list(target: Message, session: AsyncSession, customer: Customer, lang: str) -> None:
    pages = await share_pages.list_pages(session, shop_id=customer.shop_id, customer_id=customer.id)
    if not pages:
        await target.answer(t("pages.mine_empty", lang), reply_markup=pages_menu_keyboard(lang))
        return
    await target.answer(t("pages.mine_title", lang), reply_markup=my_pages_keyboard(pages))


async def my_page(
    callback: CallbackQuery,
    callback_data: MyPageCB,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    await callback.answer()
    target = _target(callback)
    if callback_data.action == "list":
        await _show_list(target, session, customer, lang)
        return
    if callback_data.action == "edit":
        # Imported here: the edit router imports this module's helpers.
        from gulbot.bot.routers.share_page_edit import open_edit_menu

        await open_edit_menu(target, state, session, customer, lang, callback_data.page_id)
        return
    page = await share_pages.get_own_page(
        session, shop_id=customer.shop_id, customer_id=customer.id, page_id=callback_data.page_id
    )
    if page is None:
        await target.answer(t("pages.gone", lang))
        return
    if callback_data.action == "open":
        await target.answer(
            await _detail(session, page, lang),
            reply_markup=my_page_keyboard(lang, page.id, links.page_url(page.token)),
            disable_web_page_preview=True,
        )
    elif callback_data.action == "delete":
        await target.answer(
            t("pages.confirm_delete", lang),
            reply_markup=my_page_keyboard(lang, page.id, None, confirming=True),
        )
    elif callback_data.action == "really_delete":
        deleted = await share_pages.delete_page(
            session, shop_id=customer.shop_id, customer_id=customer.id, page_id=page.id
        )
        await session.commit()
        await target.answer(t("pages.deleted" if deleted else "pages.gone", lang))
        await _show_list(target, session, customer, lang)


async def _detail(session: AsyncSession, page: SharePage, lang: str) -> str:
    tz = ZoneInfo(
        await session.scalar(select(Shop.timezone).where(Shop.id == page.shop_id))
        or "Asia/Tashkent"
    )
    common = {
        "url": escape(links.page_url(page.token)),
        "views": page.view_count,
        "clicks": page.cta_click_count,
        "expires": _expires_text(page, tz),
    }
    if page.kind == PageKind.YESNO:
        answer = (
            t(
                "pages.answer_yes",
                lang,
                when=page.answered_at.astimezone(tz).strftime("%d.%m %H:%M"),
            )
            if page.answered_at
            else t("pages.answer_none", lang)
        )
        if page.chosen_place and page.chosen_slot_at:
            from gulbot.sending.page_notify import when_text

            answer += NL_ + t(
                "pages.detail_choice",
                lang,
                place=escape(page.chosen_place),
                when=when_text(page.chosen_slot_at, lang, str(tz)),
            )
        return t(
            "pages.detail_yesno",
            lang,
            question=escape(page.question or ""),
            answer=answer,
            **common,
        )
    names = (page.name_1 or "") + (f" & {page.name_2}" if page.name_2 else "")
    if page.rsvp_enabled:
        summary = await share_pages.rsvp_summary(session, shop_id=page.shop_id, page_id=page.id)
        rsvp = t(
            "pages.rsvp_counts",
            lang,
            coming=summary.coming,
            guests=summary.guests,
            not_coming=summary.not_coming,
        )
    else:
        rsvp = t("pages.rsvp_off", lang)
    return t(
        "pages.detail_invite",
        lang,
        names=escape(names),
        event=escape(t(f"ibtn.event.{page.event_type}", lang)),
        date=f"{page.event_date:%d.%m.%Y} {page.event_time:%H:%M}"
        if page.event_date and page.event_time
        else "",
        rsvp=rsvp,
        **common,
    )


def build_share_pages_router() -> Router:
    router = Router(name="share_pages")

    router.message.register(open_menu, StateFilter(None), F.text.in_(PAGES_LABELS))
    # From any state: the menu's buttons restart cleanly rather than going dead
    # once a flow has begun.
    router.callback_query.register(menu_choice, PageMenuCB.filter())
    router.callback_query.register(my_page, MyPageCB.filter())

    router.callback_query.register(yesno_lang, YesNoPage.choosing_lang, PageLangCB.filter())
    router.callback_query.register(
        yesno_question, YesNoPage.choosing_question, PageQuestionCB.filter()
    )
    router.message.register(
        yesno_enter_question, YesNoPage.entering_question, F.text, flags={"catch_all": True}
    )
    router.callback_query.register(
        yesno_template, YesNoPage.choosing_template, PageTemplateCB.filter()
    )
    router.callback_query.register(yesno_notify, YesNoPage.choosing_notify, PageChoiceCB.filter())

    router.callback_query.register(invite_event, InvitePage.choosing_event, InviteEventCB.filter())
    router.callback_query.register(invite_lang, InvitePage.choosing_lang, PageLangCB.filter())
    router.message.register(
        invite_name_1, InvitePage.entering_name_1, F.text, flags={"catch_all": True}
    )
    router.message.register(
        invite_name_2, InvitePage.entering_name_2, F.text, flags={"catch_all": True}
    )
    router.callback_query.register(invite_month, InvitePage.choosing_month, InviteMonthCB.filter())
    router.callback_query.register(invite_day, InvitePage.choosing_day, InviteDayCB.filter())
    router.callback_query.register(invite_hour, InvitePage.choosing_hour, InviteHourCB.filter())
    router.callback_query.register(
        invite_minute, InvitePage.choosing_minute, InviteMinuteCB.filter()
    )
    router.message.register(
        invite_venue, InvitePage.entering_venue, F.text, flags={"catch_all": True}
    )
    router.message.register(invite_location, InvitePage.sending_location, F.location | F.venue)
    router.message.register(
        invite_location_text, InvitePage.sending_location, F.text, flags={"catch_all": True}
    )
    router.callback_query.register(invite_skip, PageSkipCB.filter())
    router.message.register(
        invite_message, InvitePage.entering_message, F.text, flags={"catch_all": True}
    )
    router.callback_query.register(invite_rsvp, InvitePage.choosing_rsvp, PageChoiceCB.filter())
    router.callback_query.register(
        invite_template, InvitePage.choosing_template, PageTemplateCB.filter()
    )

    router.callback_query.register(
        confirm, StateFilter(YesNoPage.confirming, InvitePage.confirming), PageConfirmCB.filter()
    )
    return router
