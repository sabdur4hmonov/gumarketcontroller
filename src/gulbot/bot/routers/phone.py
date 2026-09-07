"""Collecting the customer's phone number.

Owns the SHARED half of a step that happens in two places: at the end of
onboarding, where it is skippable, and inside the order flow, where it is not.
Only the parsing and storing live here. Each flow keeps its own continuation,
because "what happens next" is the one thing the two genuinely disagree about --
and because a shared continuation would mean this module importing the order
router, which imports this one.

WHY IT IS ASKED AT THE END OF ONBOARDING. Asking before the customer has saved
a single date is pure friction for a service that has not yet done anything for
them. By the time the chain finishes they have their dates in and know what the
bot is for, and the ask can say plainly what the number is for: a courier
phoning before delivery.

WHY A SHARED CONTACT THAT IS NOT THEIRS IS REFUSED. `customers.phone` is this
customer's number. Accepting a friend's contact would put a stranger's number on
the shop's order card under this customer's name, and the courier would ring it.
Telegram sets `contact.user_id` only for the sender's own contact, so that check
is the difference between a number and a guess.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.bot.keyboards import main_menu_keyboard, share_phone_keyboard
from gulbot.bot.states import Onboarding
from gulbot.i18n import t
from gulbot.i18n.catalog import CATALOG
from gulbot.models.customer import Customer
from gulbot.services.customers import set_phone
from gulbot.utils.phone import normalize_phone, normalize_shared_contact
from gulbot.utils.render import escape

SKIP_LABELS = set(CATALOG["btn.phone.skip"].values())


async def ask_for_phone(target: Message, state: FSMContext, lang: str, *, with_skip: bool) -> None:
    """Show the ask. The caller sets the state, because the state is what
    decides which continuation runs."""
    key = "phone.ask_onboarding" if with_skip else "phone.ask_order"
    await target.answer(t(key, lang), reply_markup=share_phone_keyboard(lang, with_skip=with_skip))


async def accept_contact(
    message: Message, session: AsyncSession, customer: Customer, lang: str
) -> str | None:
    """Store a shared contact. Returns the stored number, or None if refused.

    Verified, because Telegram vouched for it -- but only after checking the
    contact is the SENDER's. See the module docstring.
    """
    contact = message.contact
    sender = message.from_user
    if contact is None or sender is None:  # pragma: no cover - filtered on F.contact
        return None
    if contact.user_id != sender.id:
        await message.answer(t("phone.not_yours", lang))
        return None
    phone = normalize_shared_contact(contact.phone_number)
    if phone is None:  # pragma: no cover - Telegram's own numbers are well formed
        await message.answer(t("phone.invalid", lang))
        return None
    await set_phone(session, customer=customer, phone=phone, verified=True)
    return phone


async def accept_typed(
    message: Message, session: AsyncSession, customer: Customer, lang: str
) -> str | None:
    """Store a hand-typed number. Returns it, or None if it could not be read.

    NOT verified. Typing the number by hand is a legitimate choice -- the
    Telegram-linked number is often not the one a customer wants a courier
    calling -- so it is stored and marked, never refused for being unverified.
    """
    phone = normalize_phone(message.text or "")
    if phone is None:
        await message.answer(t("phone.invalid", lang))
        return None
    await set_phone(session, customer=customer, phone=phone, verified=False)
    return phone


async def _finish_onboarding(message: Message, state: FSMContext, lang: str) -> None:
    await state.clear()
    await message.answer(
        t("recipients.onboarding_done", lang), reply_markup=main_menu_keyboard(lang)
    )


async def onboarding_contact(
    message: Message, state: FSMContext, session: AsyncSession, customer: Customer, lang: str
) -> None:
    phone = await accept_contact(message, session, customer, lang)
    if phone is None:
        return
    await message.answer(t("phone.saved", lang, phone=escape(phone)))
    await _finish_onboarding(message, state, lang)


async def onboarding_skip(message: Message, state: FSMContext, lang: str) -> None:
    """Declining is a supported answer, not a failure. The reminder half of the
    product works perfectly well without a number; the order flow will ask when
    it actually needs one."""
    await _finish_onboarding(message, state, lang)


async def onboarding_typed(
    message: Message, state: FSMContext, session: AsyncSession, customer: Customer, lang: str
) -> None:
    phone = await accept_typed(message, session, customer, lang)
    if phone is None:
        return
    await message.answer(t("phone.saved", lang, phone=escape(phone)))
    await _finish_onboarding(message, state, lang)


def build_phone_router() -> Router:
    router = Router(name="phone")

    # Specific first. A contact message is not text, so it cannot be swallowed
    # by the catch-all below -- but Skip IS text, and would be stored as a phone
    # number if it were registered after it. That is the ordering bug the sweep
    # exists to catch, so it is written in the order that makes it impossible.
    router.message.register(onboarding_contact, Onboarding.sharing_phone, F.contact)
    router.message.register(onboarding_skip, Onboarding.sharing_phone, F.text.in_(SKIP_LABELS))
    # catch_all: within this state any text is a candidate phone number.
    router.message.register(
        onboarding_typed, Onboarding.sharing_phone, F.text, flags={"catch_all": True}
    )
    return router
