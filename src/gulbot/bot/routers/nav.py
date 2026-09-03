"""Back and Cancel. Registered ahead of every flow router.

Handlers are plain functions; registration happens in build_nav_router() so the
order is visible in one place. Module-level Router singletons cannot be attached
to a second Dispatcher, which breaks tests and the shadow sweep.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from gulbot.bot.keyboards import main_menu_keyboard, settings_keyboard
from gulbot.bot.states import SettingsFlow
from gulbot.i18n import t
from gulbot.i18n.catalog import CATALOG

BACK_LABELS = set(CATALOG["btn.nav.back"].values())
CANCEL_LABELS = set(CATALOG["btn.nav.cancel"].values())


async def cancel_anywhere(message: Message, state: FSMContext, lang: str) -> None:
    current = await state.get_state()
    await state.clear()
    key = "nav.cancelled" if current is not None else "nav.nothing_to_cancel"
    await message.answer(t(key, lang), reply_markup=main_menu_keyboard(lang))


async def back_to_settings(message: Message, state: FSMContext, lang: str) -> None:
    await state.clear()
    await message.answer(t("settings.title", lang), reply_markup=settings_keyboard(lang))


async def back_to_menu(message: Message, state: FSMContext, lang: str) -> None:
    await state.clear()
    await message.answer(t("menu.title", lang), reply_markup=main_menu_keyboard(lang))


def build_nav_router() -> Router:
    router = Router(name="nav")
    router.message.register(cancel_anywhere, F.text.in_(CANCEL_LABELS))
    # More specific state first. back_to_menu MUST keep StateFilter(None): without
    # it, it swallows Back inside every flow -- the shadow sweep caught exactly
    # that on its first run.
    router.message.register(
        back_to_settings, SettingsFlow.choosing_language, F.text.in_(BACK_LABELS)
    )
    router.message.register(back_to_menu, StateFilter(None), F.text.in_(BACK_LABELS))
    return router
