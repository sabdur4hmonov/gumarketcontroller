"""/start and first-contact language choice."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.bot.keyboards import language_keyboard, main_menu_keyboard
from gulbot.bot.routers.occasions import begin_onboarding_chain
from gulbot.bot.states import Onboarding
from gulbot.i18n import t
from gulbot.i18n.catalog import CATALOG
from gulbot.models.customer import Customer
from gulbot.services.customers import set_language

UZ_LABELS = set(CATALOG["btn.language.uz"].values())
RU_LABELS = set(CATALOG["btn.language.ru"].values())


async def start(message: Message, state: FSMContext, lang: str, customer_created: bool) -> None:
    await state.clear()
    if customer_created:
        await state.set_state(Onboarding.choosing_language)
        await message.answer(
            t("start.choose_language", lang),
            reply_markup=language_keyboard(lang, with_back=False),
        )
        return
    name = message.from_user.first_name if message.from_user else ""
    await message.answer(
        t("start.welcome_back", lang, name=name), reply_markup=main_menu_keyboard(lang)
    )


async def _choose(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    chosen: str,
) -> None:
    """First-contact language choice, which chains straight into onboarding.

    The equivalent handler in the settings router deliberately does NOT chain:
    a returning customer switching language wants the menu, not a date wizard.
    """
    await set_language(session, customer=customer, lang=chosen)
    await state.clear()
    await message.answer(t("language.saved", chosen), reply_markup=main_menu_keyboard(chosen))
    await begin_onboarding_chain(message, state, chosen)


async def choose_uz(
    message: Message, state: FSMContext, session: AsyncSession, customer: Customer
) -> None:
    await _choose(message, state, session, customer, "uz")


async def choose_ru(
    message: Message, state: FSMContext, session: AsyncSession, customer: Customer
) -> None:
    await _choose(message, state, session, customer, "ru")


def build_onboarding_router() -> Router:
    router = Router(name="onboarding")
    router.message.register(start, CommandStart())
    router.message.register(choose_uz, Onboarding.choosing_language, F.text.in_(UZ_LABELS))
    router.message.register(choose_ru, Onboarding.choosing_language, F.text.in_(RU_LABELS))
    return router
