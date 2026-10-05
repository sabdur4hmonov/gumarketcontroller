"""The creator's view of a taklifnoma's wishes wall (CP17).

"📖 Tilaklar" in the edit menu lists the newest WISHES_LISTED wishes, hidden
ones marked, with one button per wish: 🙈 hides it from the page, 👁 shows it
again. Every tap re-checks that the wish is on THIS customer's own page in
THIS shop (share_page_wishes.set_hidden) -- a crafted button opens nothing.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.bot.callbacks import MyPageCB, WishCB
from gulbot.i18n import t
from gulbot.models.customer import Customer
from gulbot.services import share_page_wishes
from gulbot.services.share_page_wishes import OwnWish
from gulbot.utils.render import escape

#: How many wishes one list shows (a Telegram message holds 4096 characters).
WISHES_LISTED = 10
#: How much of each wish the list quotes.
QUOTE_MAX = 120


def _quote(text: str) -> str:
    return text if len(text) <= QUOTE_MAX else text[: QUOTE_MAX - 1] + "…"


def wishes_text(lang: str, wishes: list[OwnWish]) -> str:
    if not wishes:
        return t("pages.wishes_none", lang)
    lines = [t("pages.wishes_list", lang)]
    for n, w in enumerate(wishes, start=1):
        mark = " 🙈" if w.hidden else ""
        lines.append(f"{n}. <b>{escape(w.author)}</b>{mark}: {escape(_quote(w.body))}")
    return "\n\n".join(lines)


def wishes_keyboard(lang: str, page_id: int, wishes: list[OwnWish]) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=f"{'👁' if w.hidden else '🙈'} {n}",
            callback_data=WishCB(
                page_id=page_id, wish_id=w.id, action="show" if w.hidden else "hide"
            ).pack(),
        )
        for n, w in enumerate(wishes, start=1)
    ]
    rows = [buttons[i : i + 5] for i in range(0, len(buttons), 5)]
    rows.append(
        [
            InlineKeyboardButton(
                text=t("ibtn.pages.edit_back", lang),
                callback_data=MyPageCB(action="edit", page_id=page_id).pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show_wishes(
    target: Message, session: AsyncSession, customer: Customer, page_id: int, lang: str
) -> None:
    wishes = await share_page_wishes.wishes_for_creator(
        session,
        shop_id=customer.shop_id,
        customer_id=customer.id,
        page_id=page_id,
        limit=WISHES_LISTED,
    )
    if wishes is None:
        await target.answer(t("pages.gone", lang))
        return
    await target.answer(
        wishes_text(lang, wishes), reply_markup=wishes_keyboard(lang, page_id, wishes)
    )


async def on_wish(
    callback: CallbackQuery,
    callback_data: WishCB,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    await callback.answer()
    if callback_data.action not in ("hide", "show") or not isinstance(callback.message, Message):
        return
    changed = await share_page_wishes.set_hidden(
        session,
        shop_id=customer.shop_id,
        customer_id=customer.id,
        page_id=callback_data.page_id,
        wish_id=callback_data.wish_id,
        hidden=callback_data.action == "hide",
    )
    if not changed:
        await session.rollback()
        await callback.message.answer(t("pages.gone", lang))
        return
    await session.commit()
    await show_wishes(callback.message, session, customer, callback_data.page_id, lang)


def build_share_page_wishes_router() -> Router:
    router = Router(name="share_page_wishes")
    router.callback_query.register(on_wish, WishCB.filter())
    return router
