"""Main menu entries."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.types import Message

from gulbot.bot.keyboards import main_menu_keyboard
from gulbot.i18n import t
from gulbot.i18n.catalog import CATALOG

HELP_LABELS = set(CATALOG["btn.menu.help"].values())


async def show_help(message: Message, lang: str) -> None:
    await message.answer(t("help.text", lang), reply_markup=main_menu_keyboard(lang))


def build_menu_router() -> Router:
    router = Router(name="menu")
    router.message.register(show_help, StateFilter(None), F.text.in_(HELP_LABELS))
    return router
