"""A shop owner connects a new shop -- on the PLATFORM bot.

The platform bot is not any shop's bot: a new owner has no bot yet, and the
pilot's bot is a customer-facing one where every private message registers a
customer. So this conversation runs on its own bot (PLATFORM_BOT_TOKEN), in its
own dispatcher, with /start as its entry -- the one command convention this
repo has.

THE STEPS, one `ShopOnboarding` state each:

1. entering_token      BotFather instructions, then the pasted token. A FORMAT
                       check only; the message is deleted, and the token is
                       kept in the conversation as ciphertext, never plaintext.
2. choosing_branding   Have a channel and a logo already? Then the shop name,
   entering_shop_name  and a ready-to-paste AI prompt: enhance the logo they
                       have, or generate one around the name.
3. waiting_channel     @username or a forwarded post. The SHOP's bot must be an
                       admin there (bot/chat_checks.py); then how to post
                       products, in the indexer's own conventions.
4. waiting_group       Telegram's chat picker. The shop's bot must be an admin
                       AND post a test message -- verify_group.py's check.
5. sharing_phone       The owner's own number.

NOTHING IS WRITTEN UNTIL THE END. The answers live in the conversation state,
so a bad token, an unreachable channel, a cancel or a drop-off leave no shop
row behind, and /start resumes at the step the owner left -- across a restart
too, since the state is in Redis. The last answer writes the whole shop in one
transaction (services/shop_onboarding.py), then tells the pollers, so the new
shop's bot goes live at once.

Shared dates (the spec's step 4) are deliberately absent: the codebase has no
shared dates to follow, and the owner chose to design that with a real
"remind every customer" feature rather than collect dates nothing sends.
Payments are out of scope for this round.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    Message,
    MessageOriginChannel,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.bot.callbacks import OnboardBrandingCB
from gulbot.bot.chat_checks import ChatCheck, Problem, check_channel, check_group
from gulbot.bot.keyboards import (
    OWNER_GROUP_REQUEST_ID,
    branding_keyboard,
    owner_cancel_keyboard,
    pick_group_keyboard,
    share_phone_keyboard,
)
from gulbot.bot.states import ShopOnboarding
from gulbot.i18n import t
from gulbot.i18n.catalog import CATALOG
from gulbot.services.shop_onboarding import NewShop, bot_is_taken, create_onboarded_shop
from gulbot.services.shop_tokens import (
    TokenCipherError,
    bot_id_of,
    decrypt_token,
    encrypt_token,
    is_token_shaped,
)
from gulbot.utils.phone import normalize_phone, normalize_shared_contact
from gulbot.utils.render import escape

log = logging.getLogger("gulbot.bot.onboarding")

#: The worked example in the posting guide. tests/test_shop_onboarding_service.py
#: runs it through the indexer's own parsers and checks the catalog carries it
#: verbatim, so the guide cannot drift from what the indexer actually reads.
POSTING_EXAMPLE = "Qizil atirgul buketi 51 ta\nNarxi: 450 000 so'm\n#atirgul #buket"

GROUP_REQUEST_ID = OWNER_GROUP_REQUEST_ID
CANCEL_LABELS = set(CATALOG["btn.nav.cancel"].values())
NAME_MAX_LENGTH = 200

#: A public channel reference: @name, or a t.me link to it.
CHANNEL_REF = re.compile(r"(?:@|(?:https?://)?t\.me/)([A-Za-z][A-Za-z0-9_]{3,31})/?")

#: Builds the NEW shop's bot from its token. Injected, so tests answer as
#: Telegram would without a network; production passes the registry's factory.
ShopBotFactory = Callable[[str], Bot]
#: Told the new shop's id once it is committed, so its bot starts polling now.
ShopCreated = Callable[[int], Awaitable[object]]

CHANNEL_PROBLEMS = {
    Problem.NOT_FOUND: "owner.channel_not_found",
    Problem.NOT_ADMIN: "owner.channel_not_admin",
    Problem.WRONG_TYPE: "owner.channel_wrong_type",
    Problem.UNREACHABLE: "owner.telegram_unreachable",
    Problem.CANNOT_POST: "owner.channel_not_admin",
}
GROUP_PROBLEMS = {
    Problem.NOT_FOUND: "owner.group_not_found",
    Problem.NOT_ADMIN: "owner.group_not_admin",
    Problem.WRONG_TYPE: "owner.group_wrong_type",
    Problem.CANNOT_POST: "owner.group_cannot_post",
    Problem.UNREACHABLE: "owner.telegram_unreachable",
}

Markup = InlineKeyboardMarkup | ReplyKeyboardMarkup | ReplyKeyboardRemove


def _prompt_for(state: str | None, lang: str) -> tuple[str, Markup] | None:
    """What a step asks, and with which keyboard. Used to begin each step AND
    to resume it, so the two can never disagree."""
    prompts: dict[str | None, tuple[str, Markup]] = {
        ShopOnboarding.entering_token.state: ("owner.welcome", owner_cancel_keyboard(lang)),
        ShopOnboarding.choosing_branding.state: ("owner.branding_ask", branding_keyboard(lang)),
        ShopOnboarding.entering_shop_name.state: ("owner.name_ask", owner_cancel_keyboard(lang)),
        ShopOnboarding.waiting_channel.state: ("owner.channel_ask", owner_cancel_keyboard(lang)),
        ShopOnboarding.waiting_group.state: ("owner.group_ask", pick_group_keyboard(lang)),
        ShopOnboarding.sharing_phone.state: (
            "owner.phone_ask",
            share_phone_keyboard(lang, with_skip=False),
        ),
    }
    found = prompts.get(state)
    return None if found is None else (t(found[0], lang), found[1])


async def _ask(message: Message, state: FSMContext, step: State, lang: str) -> None:
    await state.set_state(step)
    prompt = _prompt_for(step.state, lang)
    assert prompt is not None
    await message.answer(prompt[0], reply_markup=prompt[1])


async def _back_to_the_token(message: Message, state: FSMContext, lang: str, key: str) -> None:
    """Start again from step 1, keeping nothing -- least of all a token."""
    await state.set_data({})
    await state.set_state(ShopOnboarding.entering_token)
    await message.answer(t(key, lang), reply_markup=owner_cancel_keyboard(lang))


async def _delete_quietly(message: Message) -> None:
    try:
        await message.delete()
    except TelegramAPIError as exc:  # older than 48 h, already gone: harmless
        log.info("could not delete a pasted token message: %s", type(exc).__name__)


async def _shop_token(state: FSMContext) -> str:
    data = await state.get_data()
    return decrypt_token(str(data["token"]))


# --- escape hatches ----------------------------------------------------------


async def cancel_onboarding(message: Message, state: FSMContext, lang: str) -> None:
    await state.clear()
    await message.answer(t("owner.cancelled", lang), reply_markup=ReplyKeyboardRemove())


async def start_or_resume(message: Message, state: FSMContext, lang: str) -> None:
    """/start begins -- or, mid-flow, picks up exactly where the owner left."""
    current = await state.get_state()
    resumed = _prompt_for(current, lang)
    if resumed is not None:
        await message.answer(t("owner.resume", lang))
        await message.answer(resumed[0], reply_markup=resumed[1])
        return
    await state.clear()
    await _ask(message, state, ShopOnboarding.entering_token, lang)


async def idle(message: Message, lang: str) -> None:
    await message.answer(t("owner.idle", lang))


async def stale_button(callback: CallbackQuery) -> None:
    """A tap on a keyboard from an earlier step: acknowledged, nothing else."""
    await callback.answer()


# --- step 1: the token -------------------------------------------------------


async def receive_token(
    message: Message, state: FSMContext, session: AsyncSession, bot: Bot, lang: str
) -> None:
    pasted = (message.text or "").strip()
    if ":" in pasted:
        # Anything that might be a token leaves the chat history, valid or not.
        await _delete_quietly(message)
    if not is_token_shaped(pasted):
        await message.answer(t("owner.token_invalid", lang))
        return

    # Late: the factory builds the dispatcher this router is part of.
    from gulbot.bot.factory import process_bot_id

    bot_id = bot_id_of(pasted)
    # The platform's own bot and the pilot's are never another shop's.
    if bot_id in (bot.id, process_bot_id()) or await bot_is_taken(session, bot_id=bot_id):
        await message.answer(t("owner.token_taken", lang))
        return
    try:
        ciphertext = encrypt_token(pasted)
    except TokenCipherError as unusable:
        log.error("owner onboarding cannot store a token: %s", unusable)
        await message.answer(t("owner.not_configured", lang))
        return

    await state.update_data(token=ciphertext)
    log.info("owner %s registered bot %s (pending)", message.chat.id, bot_id)
    await message.answer(t("owner.token_saved", lang))
    await _ask(message, state, ShopOnboarding.choosing_branding, lang)


# --- step 2: branding and the name ----------------------------------------


async def choose_branding(
    callback: CallbackQuery, callback_data: OnboardBrandingCB, state: FSMContext, lang: str
) -> None:
    await callback.answer()
    await state.update_data(has_branding=callback_data.answer == "yes")
    if isinstance(callback.message, Message):
        await _ask(callback.message, state, ShopOnboarding.entering_shop_name, lang)


async def branding_by_text(message: Message, lang: str) -> None:
    await message.answer(t("owner.branding_ask", lang), reply_markup=branding_keyboard(lang))


async def receive_name(message: Message, state: FSMContext, lang: str) -> None:
    name = (message.text or "").strip()
    if not 1 <= len(name) <= NAME_MAX_LENGTH:
        await message.answer(t("owner.name_invalid", lang))
        return
    data = await state.get_data()
    key = "owner.logo_enhance" if data.get("has_branding") else "owner.logo_generate"
    await state.update_data(name=name)
    await message.answer(t(key, lang, name=escape(name)))
    await _ask(message, state, ShopOnboarding.waiting_channel, lang)


# --- step 3: the channel ---------------------------------------------------


def _forwarded_from_channel(message: Message) -> bool:
    return isinstance(message.forward_origin, MessageOriginChannel)


async def _checked_with_the_shop_bot(
    state: FSMContext,
    shop_bot_factory: ShopBotFactory,
    check: Callable[[Bot], Awaitable[ChatCheck]],
) -> ChatCheck:
    """Build the shop's bot from its token, ask, and close it again."""
    shop_bot = shop_bot_factory(await _shop_token(state))
    try:
        return await check(shop_bot)
    finally:
        await shop_bot.session.close()


async def _verify_channel(
    message: Message,
    state: FSMContext,
    lang: str,
    shop_bot_factory: ShopBotFactory,
    ref: int | str,
) -> None:
    try:
        result = await _checked_with_the_shop_bot(
            state, shop_bot_factory, lambda shop_bot: check_channel(shop_bot, ref)
        )
    except TokenCipherError as unusable:
        log.error("owner onboarding cannot read its own token: %s", unusable)
        await message.answer(t("owner.not_configured", lang))
        return
    if result.problem is Problem.TOKEN_REJECTED:
        await _back_to_the_token(message, state, lang, "owner.token_rejected")
        return
    if result.problem is not None:
        await message.answer(t(CHANNEL_PROBLEMS[result.problem], lang))
        return
    await state.update_data(channel_id=result.chat_id)
    await message.answer(t("owner.channel_ok", lang, title=escape(result.title)))
    await message.answer(t("owner.posting_guide", lang))
    await _ask(message, state, ShopOnboarding.waiting_group, lang)


async def channel_by_forward(
    message: Message, state: FSMContext, lang: str, shop_bot_factory: ShopBotFactory
) -> None:
    origin = message.forward_origin
    assert isinstance(origin, MessageOriginChannel)  # the filter guarantees it
    await _verify_channel(message, state, lang, shop_bot_factory, origin.chat.id)


async def channel_by_name(
    message: Message, state: FSMContext, lang: str, shop_bot_factory: ShopBotFactory
) -> None:
    found = CHANNEL_REF.fullmatch((message.text or "").strip())
    if found is None:
        await message.answer(t("owner.channel_unreadable", lang))
        return
    await _verify_channel(message, state, lang, shop_bot_factory, f"@{found.group(1)}")


# --- step 4: the admin group -----------------------------------------------


async def receive_group(
    message: Message, state: FSMContext, lang: str, shop_bot_factory: ShopBotFactory
) -> None:
    shared = message.chat_shared
    assert shared is not None  # the filter guarantees it
    test_text = t("owner.group_test_message", lang)
    try:
        result = await _checked_with_the_shop_bot(
            state,
            shop_bot_factory,
            lambda shop_bot: check_group(shop_bot, shared.chat_id, test_text=test_text),
        )
    except TokenCipherError as unusable:
        log.error("owner onboarding cannot read its own token: %s", unusable)
        await message.answer(t("owner.not_configured", lang))
        return
    if result.problem is Problem.TOKEN_REJECTED:
        await _back_to_the_token(message, state, lang, "owner.token_rejected")
        return
    if result.problem is not None:
        await message.answer(t(GROUP_PROBLEMS[result.problem], lang))
        return
    await state.update_data(group_chat_id=result.chat_id)
    await message.answer(t("owner.group_ok", lang, title=escape(result.title)))
    await _ask(message, state, ShopOnboarding.sharing_phone, lang)


async def group_by_other_means(message: Message, lang: str) -> None:
    await message.answer(t("owner.group_ask", lang), reply_markup=pick_group_keyboard(lang))


# --- step 5: the owner's phone, and the shop ------------------------------


async def _finish(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    lang: str,
    on_shop_created: ShopCreated,
    *,
    phone: str,
    verified: bool,
) -> None:
    data = await state.get_data()
    owner = message.from_user
    assert owner is not None
    try:
        new = NewShop(
            name=str(data["name"]),
            token=await _shop_token(state),
            channel_id=int(data["channel_id"]),
            group_chat_id=int(data["group_chat_id"]),
            owner_telegram_id=owner.id,
            owner_phone=phone,
            owner_phone_verified=verified,
        )
    except TokenCipherError as unusable:
        log.error("owner onboarding cannot read its own token: %s", unusable)
        await message.answer(t("owner.not_configured", lang))
        return

    try:
        # A savepoint, so a refusal rolls back exactly this write -- the new
        # row included -- and the session stays usable to answer the owner.
        async with session.begin_nested():
            shop_id = await create_onboarded_shop(session, new)
    except IntegrityError:
        # Another shop registered this bot since the token step passed.
        log.warning("owner %s: bot was registered by another shop mid-flow", owner.id)
        await _back_to_the_token(message, state, lang, "owner.token_taken")
        return

    # Committed BEFORE the pollers are told: they read the shop in their own
    # session, and an uncommitted row is invisible to it.
    await session.commit()
    await state.clear()
    log.info("owner %s created shop %s", owner.id, shop_id)
    await message.answer(
        t("owner.done", lang, name=escape(new.name)), reply_markup=ReplyKeyboardRemove()
    )
    try:
        await on_shop_created(shop_id)
    except Exception:
        # The shop exists; the pollers' periodic refresh will still find it.
        log.exception("shop %s was created but could not be started at once", shop_id)


async def owner_contact(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    lang: str,
    on_shop_created: ShopCreated,
) -> None:
    """The owner's OWN contact only -- as for customers (bot/routers/phone.py)."""
    contact, sender = message.contact, message.from_user
    if contact is None or sender is None:  # pragma: no cover - filtered on F.contact
        return
    if contact.user_id != sender.id:
        await message.answer(t("phone.not_yours", lang))
        return
    phone = normalize_shared_contact(contact.phone_number)
    if phone is None:  # pragma: no cover - Telegram's own numbers are well formed
        await message.answer(t("phone.invalid", lang))
        return
    await _finish(message, state, session, lang, on_shop_created, phone=phone, verified=True)


async def owner_typed_phone(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    lang: str,
    on_shop_created: ShopCreated,
) -> None:
    phone = normalize_phone(message.text or "")
    if phone is None:
        await message.answer(t("phone.invalid", lang))
        return
    await _finish(message, state, session, lang, on_shop_created, phone=phone, verified=False)


def build_shop_onboarding_router() -> Router:
    """Order matters, and the shadow sweep checks it against the live platform
    dispatcher. Cancel and /start first, from every state; within a step the
    specific input (a button, a forward, a picked chat, a contact) before that
    step's catch-all, so whatever else the owner sends earns a re-prompt
    rather than silence."""
    router = Router(name="shop_onboarding")
    catch_all: dict[str, Any] = {"catch_all": True}

    router.message.register(cancel_onboarding, F.text.in_(CANCEL_LABELS))
    router.message.register(start_or_resume, CommandStart())

    router.message.register(receive_token, ShopOnboarding.entering_token, flags=catch_all)

    router.callback_query.register(
        choose_branding, ShopOnboarding.choosing_branding, OnboardBrandingCB.filter()
    )
    router.message.register(branding_by_text, ShopOnboarding.choosing_branding, flags=catch_all)

    router.message.register(receive_name, ShopOnboarding.entering_shop_name, flags=catch_all)

    router.message.register(
        channel_by_forward, ShopOnboarding.waiting_channel, _forwarded_from_channel
    )
    router.message.register(channel_by_name, ShopOnboarding.waiting_channel, flags=catch_all)

    router.message.register(
        receive_group,
        ShopOnboarding.waiting_group,
        F.chat_shared.request_id == GROUP_REQUEST_ID,
    )
    router.message.register(group_by_other_means, ShopOnboarding.waiting_group, flags=catch_all)

    router.message.register(owner_contact, ShopOnboarding.sharing_phone, F.contact)
    router.message.register(owner_typed_phone, ShopOnboarding.sharing_phone, flags=catch_all)

    # Outside any step, and stale buttons from any step.
    router.message.register(idle, flags=catch_all)
    router.callback_query.register(stale_button, flags=catch_all)
    return router
