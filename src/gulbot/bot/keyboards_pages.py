"""Keyboards for the Ha/Yo'q and taklifnoma flows.

Every value a button carries is one the router checks again on arrival; the
constants here (hours, minutes) are the sets it checks against, so the two
cannot drift.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final
from urllib.parse import quote

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

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
from gulbot.i18n import t
from gulbot.models.share_page import EVENT_TYPES, PAGE_TEMPLATES, PageKind, SharePage
from gulbot.web import strings
from gulbot.web.render import THEME_NAMES

#: Start hours offered for an event. Nothing before seven in the morning.
INVITE_HOURS: Final = tuple(range(7, 24))
INVITE_MINUTES: Final = (0, 15, 30, 45)

THEME_ICONS: Final = {
    "milliy": "🪷",
    "atlas": "🧵",
    "minimal": "🤍",
    "bog": "🌿",
    "romantik": "💗",
    "oltin": "✨",
    "quvnoq": "🎉",
    "tungi": "🌙",
    "pastel": "🍬",
    "konvert": "✉️",
    "foto": "🖼",
    "bold": "🅱️",
    "geometrik": "🔷",
    "akvarel": "🎨",
    "vintaj": "📜",
    "oqqora": "🖤",
    "bolalar": "🎈",
    "suzani": "🌺",
    "neon": "💡",
    "deco": "🏛",
}

LANG_BUTTONS: Final = (
    ("uz", "🇺🇿 O'zbekcha (lotin)"),
    ("uz_cyrl", "🇺🇿 Ўзбекча (кирилл)"),
    ("ru", "🇷🇺 Русский"),
    ("en", "🇬🇧 English"),
)


def _rows(buttons: Sequence[InlineKeyboardButton], width: int) -> list[list[InlineKeyboardButton]]:
    return [list(buttons[i : i + width]) for i in range(0, len(buttons), width)]


def pages_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("ibtn.pages.yesno", lang),
                    callback_data=PageMenuCB(action=PageKind.YESNO.value).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("ibtn.pages.invite", lang),
                    callback_data=PageMenuCB(action=PageKind.INVITE.value).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("ibtn.pages.apology", lang),
                    callback_data=PageMenuCB(action=PageKind.APOLOGY.value).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("ibtn.pages.mine", lang),
                    callback_data=PageMenuCB(action="mine").pack(),
                )
            ],
        ]
    )


def page_lang_keyboard() -> InlineKeyboardMarkup:
    """Written in each language's own name, so it reads the same to everyone."""
    buttons = [
        InlineKeyboardButton(text=label, callback_data=PageLangCB(lang=code).pack())
        for code, label in LANG_BUTTONS
    ]
    return InlineKeyboardMarkup(inline_keyboard=_rows(buttons, 2))


def question_keyboard(lang: str, page_lang: str) -> InlineKeyboardMarkup:
    """The ready questions, shown in the language the PAGE will be in."""
    rows = [
        [
            InlineKeyboardButton(
                text=strings.question(preset, page_lang),
                callback_data=PageQuestionCB(preset=preset).pack(),
            )
        ]
        for preset in strings.QUESTIONS
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text=t("ibtn.pages.custom_question", lang),
                callback_data=PageQuestionCB(preset="custom").pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def template_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=f"{THEME_ICONS[theme]} {THEME_NAMES[theme]}",
            callback_data=PageTemplateCB(template=theme).pack(),
        )
        for theme in PAGE_TEMPLATES
    ]
    return InlineKeyboardMarkup(inline_keyboard=_rows(buttons, 2))


def toggle_keyboard(lang: str, field: str) -> InlineKeyboardMarkup:
    yes_key, no_key = (
        ("ibtn.pages.notify_yes", "ibtn.pages.notify_no")
        if field == "notify"
        else ("ibtn.pages.rsvp_yes", "ibtn.pages.rsvp_no")
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(yes_key, lang),
                    callback_data=PageChoiceCB(field=field, value="yes").pack(),
                ),
                InlineKeyboardButton(
                    text=t(no_key, lang), callback_data=PageChoiceCB(field=field, value="no").pack()
                ),
            ]
        ]
    )


def event_keyboard(lang: str) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=t(f"ibtn.event.{event}", lang), callback_data=InviteEventCB(event=event).pack()
        )
        for event in EVENT_TYPES
    ]
    return InlineKeyboardMarkup(inline_keyboard=_rows(buttons, 2))


MONTH_SHORT: Final = {
    "uz": ("Yan", "Fev", "Mar", "Apr", "May", "Iyun", "Iyul", "Avg", "Sen", "Okt", "Noy", "Dek"),
    "ru": ("янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"),
    "en": ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
}


def month_keyboard(lang: str, months: Sequence[tuple[int, int]]) -> InlineKeyboardMarkup:
    names = MONTH_SHORT.get(lang, MONTH_SHORT["uz"])
    buttons = [
        InlineKeyboardButton(
            text=f"{names[month - 1]} {year}",
            callback_data=InviteMonthCB(year=year, month=month).pack(),
        )
        for year, month in months
    ]
    return InlineKeyboardMarkup(inline_keyboard=_rows(buttons, 3))


def page_day_keyboard(days: Sequence[int]) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=str(day), callback_data=InviteDayCB(day=day).pack())
        for day in days
    ]
    return InlineKeyboardMarkup(inline_keyboard=_rows(buttons, 7))


def hour_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=f"{hour:02d}:__", callback_data=InviteHourCB(hour=hour).pack())
        for hour in INVITE_HOURS
    ]
    return InlineKeyboardMarkup(inline_keyboard=_rows(buttons, 4))


def minute_keyboard(hour: int) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=f"{hour:02d}:{minute:02d}", callback_data=InviteMinuteCB(minute=minute).pack()
        )
        for minute in INVITE_MINUTES
    ]
    return InlineKeyboardMarkup(inline_keyboard=_rows(buttons, 4))


def skip_keyboard(lang: str, step: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("ibtn.pages.skip", lang), callback_data=PageSkipCB(step=step).pack()
                )
            ]
        ]
    )


def confirm_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("ibtn.pages.create", lang),
                    callback_data=PageConfirmCB(action="create").pack(),
                ),
                InlineKeyboardButton(
                    text=t("ibtn.pages.cancel", lang),
                    callback_data=PageConfirmCB(action="cancel").pack(),
                ),
            ]
        ]
    )


def cancel_reply_keyboard(lang: str) -> ReplyKeyboardMarkup:
    """While we wait for typed text: Cancel, and nothing a tap could mistake
    for an answer."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t("btn.nav.cancel", lang))]], resize_keyboard=True
    )


def _url_buttons_allowed(url: str) -> bool:
    """Telegram refuses URL buttons it cannot open -- localhost, plain IPs --
    and refusing a whole message over a button would lose the link. Until the
    pages are on a public https domain, the link travels as text only."""
    return url.startswith("https://")


def link_keyboard(lang: str, url: str) -> InlineKeyboardMarkup | None:
    if not _url_buttons_allowed(url):
        return None
    share = f"https://t.me/share/url?url={quote(url, safe='')}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t("ibtn.pages.open", lang), url=url),
                InlineKeyboardButton(text=t("ibtn.pages.share", lang), url=share),
            ]
        ]
    )


def _page_label(page: SharePage) -> str:
    if page.kind == PageKind.APOLOGY:
        text = " ".join((page.message or "").split())
        return f"🕊 {text[:30]}{'…' if len(text) > 30 else ''}"
    if page.kind == PageKind.YESNO:
        text = page.question or ""
        return f"💍 {text[:30]}{'…' if len(text) > 30 else ''}"
    names = (page.name_1 or "") + (f" & {page.name_2}" if page.name_2 else "")
    when = f" · {page.event_date:%d.%m}" if page.event_date else ""
    return f"💌 {names[:26]}{when}"


def my_pages_keyboard(pages: Sequence[SharePage]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_page_label(page),
                    callback_data=MyPageCB(action="open", page_id=page.id).pack(),
                )
            ]
            for page in pages
        ]
    )


def my_page_keyboard(
    lang: str, page_id: int, url: str | None, *, confirming: bool = False
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if confirming:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t("ibtn.pages.really_delete", lang),
                    callback_data=MyPageCB(action="really_delete", page_id=page_id).pack(),
                )
            ]
        )
    else:
        if url is not None and _url_buttons_allowed(url):
            rows.append([InlineKeyboardButton(text=t("ibtn.pages.open", lang), url=url)])
        rows.append(
            [
                InlineKeyboardButton(
                    text=t("ibtn.pages.edit", lang),
                    callback_data=MyPageCB(action="edit", page_id=page_id).pack(),
                ),
                InlineKeyboardButton(
                    text=t("ibtn.pages.delete", lang),
                    callback_data=MyPageCB(action="delete", page_id=page_id).pack(),
                ),
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=t("ibtn.pages.back_list", lang),
                callback_data=MyPageCB(action="list", page_id=0).pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
