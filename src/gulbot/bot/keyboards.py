"""Reply keyboards, built from the i18n catalog."""

from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from gulbot.i18n import t


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
    return _kb([[t("btn.menu.settings", lang), t("btn.menu.help", lang)]])


def settings_keyboard(lang: str) -> ReplyKeyboardMarkup:
    return _kb([[t("btn.settings.change_language", lang)], [t("btn.nav.back", lang)]])
