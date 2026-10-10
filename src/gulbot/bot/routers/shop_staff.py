"""/staff in the PLATFORM bot: an owner manages who may decide orders (CP19).

The rule itself is in gulbot.services.shop_staff; this is the owner's way to
the list without psql. Only an owner of at least one shop gets anywhere:
for anyone else the filter does not match, and "/staff" falls through to
onboarding, which answers as it did before this router existed.

EVERY ACTION CHECKS THE TAPPER AGAINST THE SHOP. The shop id rides in the
callback (or, while adding, in the state), and both are only claims: each
handler asks the database whether this person owns that shop before reading
or changing its list.

Adding uses Telegram's own user picker, which hands back the person's id and
name; a typed numeric id works too, for someone the owner cannot pick. Cancel
and /start are onboarding's, as in every other platform state, so this
router's catch-all for the adding step steps aside for both.
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command, Filter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.bot.callbacks import StaffCB
from gulbot.bot.keyboards import (
    STAFF_REQUEST_ID,
    staff_list_keyboard,
    staff_pick_keyboard,
    staff_shops_keyboard,
)
from gulbot.bot.states import StaffAdmin
from gulbot.i18n import t
from gulbot.i18n.catalog import CATALOG
from gulbot.services.shop_staff import (
    MAX_STAFF,
    OwnedShop,
    StaffRefused,
    add_staff,
    owned_shop,
    owned_shops,
    remove_staff,
    staff_of,
)
from gulbot.utils.render import escape

log = logging.getLogger("gulbot.bot.shop_staff")

CANCEL_LABELS = set(CATALOG["btn.nav.cancel"].values())
TYPED_ID = r"^\s*-?\d{1,20}\s*$"


class OwnsAShop(Filter):
    """Matches an owner of at least one shop, and hands the handler the list."""

    async def __call__(self, message: Message, session: AsyncSession) -> bool | dict[str, Any]:
        user = message.from_user
        if user is None:
            return False
        shops = await owned_shops(session, telegram_id=user.id)
        return {"shops": shops} if shops else False


def _name(person: int, label: str | None) -> str:
    return escape(label) if label else str(person)


async def _show(message: Message, session: AsyncSession, shop: OwnedShop, lang: str) -> None:
    members = await staff_of(session, shop_id=shop.shop_id)
    title = t("staff.title", lang, shop=escape(shop.name))
    if members:
        names = "\n".join(
            f"• {_name(m.telegram_id, m.label)} (<code>{m.telegram_id}</code>)" for m in members
        )
        body = t("staff.listed", lang, names=names)
    else:
        body = t("staff.empty", lang)
    keyboard = staff_list_keyboard(
        lang, shop.shop_id, [(m.telegram_id, m.label or str(m.telegram_id)) for m in members]
    )
    await message.answer(f"{title}\n\n{body}", reply_markup=keyboard)


async def open_staff(
    message: Message,
    shops: list[OwnedShop],
    session: AsyncSession,
    state: FSMContext,
    lang: str,
) -> None:
    """/staff. One shop: its list. Several: which one first."""
    if await state.get_state() == StaffAdmin.adding.state:
        await state.clear()
    if len(shops) == 1:
        await _show(message, session, shops[0], lang)
        return
    await message.answer(
        t("staff.pick_shop", lang),
        reply_markup=staff_shops_keyboard(lang, [(s.shop_id, s.name) for s in shops]),
    )


async def on_staff_button(
    callback: CallbackQuery,
    callback_data: StaffCB,
    session: AsyncSession,
    state: FSMContext,
    lang: str,
) -> None:
    message = callback.message
    shop = await owned_shop(
        session, shop_id=callback_data.shop_id, telegram_id=callback.from_user.id
    )
    if shop is None:
        log.warning(
            "staff button for shop %s from %s, who does not own it",
            callback_data.shop_id,
            callback.from_user.id,
        )
        await callback.answer(t("staff.refused.not_owner", lang), show_alert=True)
        return
    if not isinstance(message, Message):  # pragma: no cover - too old to answer
        await callback.answer()
        return

    if callback_data.action == "add":
        await callback.answer()
        await state.set_state(StaffAdmin.adding)
        await state.update_data(staff_shop_id=shop.shop_id)
        await message.answer(t("staff.add_ask", lang), reply_markup=staff_pick_keyboard(lang))
        return
    if callback_data.action == "remove":
        labels = {m.telegram_id: m.label for m in await staff_of(session, shop_id=shop.shop_id)}
        removed = await remove_staff(
            session,
            shop_id=shop.shop_id,
            owner_id=callback.from_user.id,
            telegram_id=callback_data.person,
        )
        name = labels.get(callback_data.person) or str(callback_data.person)
        # An alert's text is plain, not HTML: no escaping here.
        await callback.answer(
            t("staff.removed", lang, name=name) if removed else t("staff.not_listed", lang)
        )
    else:
        await callback.answer()
    await _show(message, session, shop, lang)


async def _add(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    lang: str,
    *,
    person: int,
    label: str | None,
) -> None:
    owner = message.from_user
    assert owner is not None  # private chats only
    shop_id = (await state.get_data()).get("staff_shop_id")
    shop = (
        None
        if shop_id is None
        else await owned_shop(session, shop_id=int(shop_id), telegram_id=owner.id)
    )
    if shop is None:
        await state.clear()
        await message.answer(t("staff.refused.not_owner", lang), reply_markup=ReplyKeyboardRemove())
        return
    try:
        added = await add_staff(
            session, shop_id=shop.shop_id, owner_id=owner.id, telegram_id=person, label=label
        )
    except StaffRefused as refused:
        if refused.reason == "bad_id":
            await message.answer(t("staff.refused.bad_id", lang))
            return  # still adding: let them try again
        await state.clear()
        await message.answer(
            t(f"staff.refused.{refused.reason}", lang, max=MAX_STAFF),
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    await state.clear()
    key = "staff.added" if added else "staff.already"
    await message.answer(
        t(key, lang, name=_name(person, label)), reply_markup=ReplyKeyboardRemove()
    )
    await _show(message, session, shop, lang)


async def picked_a_person(
    message: Message, session: AsyncSession, state: FSMContext, lang: str
) -> None:
    shared = message.users_shared
    assert shared is not None and shared.users  # the filter guarantees it
    person = shared.users[0]
    label = " ".join(p for p in (person.first_name, person.last_name) if p) or (
        f"@{person.username}" if person.username else None
    )
    await _add(message, session, state, lang, person=person.user_id, label=label)


async def typed_an_id(
    message: Message, session: AsyncSession, state: FSMContext, lang: str
) -> None:
    await _add(message, session, state, lang, person=int((message.text or "").strip()), label=None)


async def adding_something_else(message: Message, lang: str) -> None:
    await message.answer(t("staff.add_ask", lang), reply_markup=staff_pick_keyboard(lang))


def build_shop_staff_router() -> Router:
    """Before onboarding: /staff must reach an owner in any state, and the
    adding step's answers must not be eaten by onboarding's idle catch-all."""
    router = Router(name="shop_staff")
    router.message.register(open_staff, Command("staff"), OwnsAShop())
    router.callback_query.register(on_staff_button, StaffCB.filter())
    router.message.register(
        picked_a_person, StaffAdmin.adding, F.users_shared.request_id == STAFF_REQUEST_ID
    )
    router.message.register(typed_an_id, StaffAdmin.adding, F.text.regexp(TYPED_ID))
    # Cancel and commands step aside to onboarding, which owns both.
    router.message.register(
        adding_something_else,
        StaffAdmin.adding,
        ~F.text.in_(CANCEL_LABELS),
        ~F.text.startswith("/"),
        flags={"catch_all": True},
    )
    return router
