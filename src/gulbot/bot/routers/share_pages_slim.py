"""The shop bot's pages menu when the wizard is OFF (CP27.5, the default).

Making, editing and managing pages moved to Taklifnoma Studio (CP27.1-27.4):
the bot's share-page flow is ONE button, "🌐 Taklifnoma yaratish", which sends
the creator a one-time studio link (and the Mini App button on https).

Everything the old wizard left behind still gets a useful answer instead of a
dead button: any of its inline buttons in a chat's history, any menu action,
and a conversation stopped half-way through it (its state is cleared). Each
answer is the studio link. Notifications are untouched: Ha and RSVP messages
come from the worker, and the wishes router (a notification with buttons)
stays registered in both modes.

SHARE_WIZARD_IN_BOT=true brings the old wizard back at once (bot/routers
__init__.build_routers); its code and tests are kept.
"""

from __future__ import annotations

from typing import Final

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.bot.callbacks import (
    ColorCB,
    EditFieldCB,
    EditValueCB,
    InviteDayCB,
    InviteEventCB,
    InviteHourCB,
    InviteMinuteCB,
    InviteMonthCB,
    MusicCB,
    MyPageCB,
    PageChoiceCB,
    PageConfirmCB,
    PageLangCB,
    PageMenuCB,
    PageQuestionCB,
    PageSkipCB,
    PageTemplateCB,
    PhotoCB,
    PlanCB,
    SealCB,
)
from gulbot.bot.routers.share_pages import PAGES_LABELS, _send_studio_link
from gulbot.bot.states import ApologyPage, EditPage, InvitePage, YesNoPage
from gulbot.i18n import t
from gulbot.models.customer import Customer
from gulbot.web import links

#: Every inline button the old wizard and its editors ever sent. The wishes
#: buttons (WishCB) are not here: that router stays in both modes.
WIZARD_BUTTONS: Final = (
    MyPageCB,
    PageLangCB,
    PageQuestionCB,
    PageTemplateCB,
    PageChoiceCB,
    InviteEventCB,
    InviteMonthCB,
    InviteDayCB,
    InviteHourCB,
    InviteMinuteCB,
    PageSkipCB,
    PageConfirmCB,
    PlanCB,
    PhotoCB,
    ColorCB,
    SealCB,
    MusicCB,
    EditFieldCB,
    EditValueCB,
)
#: The prefixes as they start callback data ("pgmin:" is not "pgmine:").
WIZARD_PREFIXES: Final = tuple(f"{cb.__prefix__}{cb.__separator__}" for cb in WIZARD_BUTTONS)


def studio_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("ibtn.pages.studio", lang),
                    callback_data=PageMenuCB(action="studio").pack(),
                )
            ]
        ]
    )


async def open_menu(message: Message, state: FSMContext, lang: str) -> None:
    await state.clear()
    if not links.pages_available():
        await message.answer(t("pages.unavailable", lang))
        return
    await message.answer(t("pages.menu_studio", lang), reply_markup=studio_menu_keyboard(lang))


async def to_the_studio(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
    bot: Bot,
) -> None:
    """Any menu action, and any old wizard button: the studio link."""
    await callback.answer()
    await state.clear()
    if not isinstance(callback.message, Message):
        return
    if not links.pages_available():
        await callback.message.answer(t("pages.unavailable", lang))
        return
    await _send_studio_link(callback.message, session, customer, lang, bot)


async def left_mid_wizard(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
    bot: Bot,
) -> None:
    """A conversation stopped half-way through the old wizard: start over in
    the studio rather than read this text as a name or a venue."""
    await state.clear()
    await message.answer(t("pages.moved_to_studio", lang))
    if links.pages_available():
        await _send_studio_link(message, session, customer, lang, bot)


def build_share_pages_slim_router() -> Router:
    router = Router(name="share_pages_slim")
    router.message.register(open_menu, StateFilter(None), F.text.in_(PAGES_LABELS))
    router.callback_query.register(to_the_studio, PageMenuCB.filter())
    router.callback_query.register(to_the_studio, F.data.startswith(WIZARD_PREFIXES))
    router.message.register(
        left_mid_wizard,
        StateFilter(YesNoPage, InvitePage, ApologyPage, EditPage),
        flags={"catch_all": True},
    )
    return router
