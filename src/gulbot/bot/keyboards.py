"""Reply keyboards, built from the i18n catalog."""

from __future__ import annotations

from collections.abc import Sequence

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

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
from gulbot.i18n import t
from gulbot.models.occasion import MAX_DAY_IN_MONTH, OccasionType


def _kb(rows: list[list[str]]) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=label) for label in row] for row in rows],
        resize_keyboard=True,
    )


def language_keyboard(lang: str, *, with_back: bool) -> ReplyKeyboardMarkup:
    rows = [[t("btn.language.uz", lang), t("btn.language.ru", lang)]]
    if with_back:
        rows.append([t("btn.nav.back", lang)])
    return _kb(rows)


def main_menu_keyboard(lang: str) -> ReplyKeyboardMarkup:
    return _kb(
        [
            [t("btn.menu.occasions", lang)],
            [t("btn.menu.settings", lang), t("btn.menu.help", lang)],
        ]
    )


def settings_keyboard(lang: str) -> ReplyKeyboardMarkup:
    return _kb([[t("btn.settings.change_language", lang)], [t("btn.nav.back", lang)]])


# --- inline keyboards for the occasion flow --------------------------------


def _back_button(lang: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=t("ibtn.back", lang), callback_data=BackCB(action="back").pack()
    )


def occasion_type_keyboard(lang: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=t(f"occtype.{preset.value}", lang),
                callback_data=OccasionTypeCB(type=preset.value).pack(),
            )
        ]
        for preset in OccasionType
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def month_keyboard(lang: str) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=t(f"month.{month}", lang), callback_data=MonthCB(month=month).pack()
        )
        for month in range(1, 13)
    ]
    rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
    rows.append([_back_button(lang)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def day_keyboard(lang: str, month: int) -> InlineKeyboardMarkup:
    """Built FROM the chosen month, so an impossible day is never offered.

    This is why Feb 30 and Apr 31 are structurally unreachable rather than
    merely validated after the fact.
    """
    last_day = MAX_DAY_IN_MONTH[month - 1]
    buttons = [
        InlineKeyboardButton(text=str(day), callback_data=DayCB(day=day).pack())
        for day in range(1, last_day + 1)
    ]
    rows = [buttons[i : i + 7] for i in range(0, len(buttons), 7)]
    rows.append([_back_button(lang)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def year_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("ibtn.skip_year", lang),
                    callback_data=YearSkipCB(action="skip").pack(),
                )
            ],
            [_back_button(lang)],
        ]
    )


def confirm_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("ibtn.save", lang), callback_data=ConfirmCB(action="save").pack()
                ),
                InlineKeyboardButton(
                    text=t("ibtn.discard", lang),
                    callback_data=ConfirmCB(action="discard").pack(),
                ),
            ],
            [_back_button(lang)],
        ]
    )


def occasion_list_keyboard(lang: str, occasions: Sequence[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{t('ibtn.deactivate', lang)} {label}",
                callback_data=OccasionActionCB(action="deactivate", occasion_id=occasion_id).pack(),
            )
        ]
        for occasion_id, label in occasions
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text=t("ibtn.add_occasion", lang),
                callback_data=AddOccasionCB(action="start").pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
