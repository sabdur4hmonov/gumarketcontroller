"""/start and first-contact language choice.

/start may carry a payload: `pg_<token>` is someone arriving from a Ha/Yo'q
page or a taklifnoma through its "Gul buyurtma qilish" link. It is recorded as
a referral -- only if that page belongs to THIS shop -- and a returning
customer is taken straight to the bouquets, which is what the link promised.
"""

from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.bot.keyboards import language_keyboard, main_menu_keyboard
from gulbot.bot.routers.browse import open_browse
from gulbot.bot.routers.occasions import begin_onboarding_chain
from gulbot.bot.states import Onboarding
from gulbot.i18n import t
from gulbot.i18n.catalog import CATALOG
from gulbot.models.customer import Customer
from gulbot.services.customers import set_language
from gulbot.services.share_pages import record_referral

UZ_LABELS = set(CATALOG["btn.language.uz"].values())
RU_LABELS = set(CATALOG["btn.language.ru"].values())

#: A page's link back: `t.me/<this bot>?start=pg_<token>`.
PAGE_PAYLOAD = re.compile(r"^pg_([A-Za-z0-9_-]{20,32})$")


async def _came_from_page(
    session: AsyncSession, customer: Customer | None, command: CommandObject | None
) -> bool:
    match = PAGE_PAYLOAD.match((command.args or "").strip()) if command is not None else None
    if match is None or customer is None:
        return False
    return await record_referral(
        session, shop_id=customer.shop_id, customer_id=customer.id, token=match.group(1)
    )


async def start(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    lang: str,
    customer_created: bool,
    customer: Customer | None = None,
    command: CommandObject | None = None,
) -> None:
    await state.clear()
    from_page = await _came_from_page(session, customer, command)
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
    if from_page and customer is not None:
        await open_browse(message, state, session, customer, lang)


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
