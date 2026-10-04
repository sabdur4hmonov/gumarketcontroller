"""Settings screen and language change."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.bot.keyboards import language_keyboard, main_menu_keyboard, settings_keyboard
from gulbot.bot.states import SettingsFlow
from gulbot.i18n import t
from gulbot.i18n.catalog import CATALOG
from gulbot.models.customer import Customer
from gulbot.services.customers import set_language

SETTINGS_LABELS = set(CATALOG["btn.menu.settings"].values())
CHANGE_LANGUAGE_LABELS = set(CATALOG["btn.settings.change_language"].values())
UZ_LABELS = set(CATALOG["btn.language.uz"].values())
RU_LABELS = set(CATALOG["btn.language.ru"].values())
EN_LABELS = set(CATALOG["btn.language.en"].values())


async def open_settings(message: Message, lang: str) -> None:
    await message.answer(t("settings.title", lang), reply_markup=settings_keyboard(lang))


async def ask_language(message: Message, state: FSMContext, lang: str) -> None:
    await state.set_state(SettingsFlow.choosing_language)
    await message.answer(
        t("start.choose_language", lang), reply_markup=language_keyboard(lang, with_back=True)
    )


async def _apply(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    chosen: str,
) -> None:
    await set_language(session, customer=customer, lang=chosen)
    await state.clear()
    await message.answer(t("language.saved", chosen))
    await message.answer(t("menu.title", chosen), reply_markup=main_menu_keyboard(chosen))


async def set_uz(
    message: Message, state: FSMContext, session: AsyncSession, customer: Customer
) -> None:
    await _apply(message, state, session, customer, "uz")


async def set_ru(
    message: Message, state: FSMContext, session: AsyncSession, customer: Customer
) -> None:
    await _apply(message, state, session, customer, "ru")


async def set_en(
    message: Message, state: FSMContext, session: AsyncSession, customer: Customer
) -> None:
    await _apply(message, state, session, customer, "en")


def build_settings_router() -> Router:
    router = Router(name="settings")
    router.message.register(open_settings, StateFilter(None), F.text.in_(SETTINGS_LABELS))
    router.message.register(ask_language, StateFilter(None), F.text.in_(CHANGE_LANGUAGE_LABELS))
    router.message.register(set_uz, SettingsFlow.choosing_language, F.text.in_(UZ_LABELS))
    router.message.register(set_ru, SettingsFlow.choosing_language, F.text.in_(RU_LABELS))
    router.message.register(set_en, SettingsFlow.choosing_language, F.text.in_(EN_LABELS))
    return router
