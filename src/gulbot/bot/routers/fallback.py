"""Last resort. Must stay registered last.

Flagged `fallback` so the shadowing sweep can tell an intentional catch-all from
an accidental one. A fallback that matches BEFORE a real handler is precisely
the registration-order bug the sweep fails the build on.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from gulbot.bot.keyboards import main_menu_keyboard
from gulbot.i18n import t


async def unknown_text(message: Message, lang: str) -> None:
    await message.answer(t("common.unknown", lang), reply_markup=main_menu_keyboard(lang))


def build_fallback_router() -> Router:
    router = Router(name="fallback")
    router.message.register(unknown_text, F.text, flags={"fallback": True})
    return router
