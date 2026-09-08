"""Browsing the catalogue, and ordering without waiting for a reminder.

Until CP11 the only route into ordering was the button attached to a reminder.
A customer who opened the bot wanting flowers today could not buy any -- the
product sold only to people who happened to have a date coming up. This is the
menu button that fixes that, and it is the largest functional gap the pre-launch
walkthrough turned up.

THE VIEW IS THE SHOP'S OWN POST, reproduced with `copyMessage` rather than
re-composed by us. Their words, their formatting, their line breaks, exactly as
posted. Two reasons it is a COPY and not our own `sendPhoto` with their caption
pasted in:

  * the bot sends with parse_mode=HTML, so a caption containing `<` or `&` --
    "3<5 gul", "atirgul & lola" -- would make the send FAIL outright. Escaping
    it would work but would stop being verbatim, which was the request.
  * a copy carries the shop's own entities, so bold and links survive.

An ALBUM copies its anchor photo only; `copyMessages` can take the whole group
but cannot carry a keyboard, and the order button is worth more than the extra
angles.

WHEN THE CAPTION IS NOTHING BUT HASHTAGS the copy is skipped and the bouquet is
shown with our own minimal caption instead. Both bouquets in the shop's channel
on the day this was written were captioned exactly `#gulkinder` and
`#gulbuketlar`, and copying that verbatim would show the customer a bare tag.
Verbatim is right when there is something to be verbatim ABOUT.

PAGING IS A CURSOR STACK IN FSM DATA. Forward paging pushes the cursor it came
from; Back pops it. That keeps the query keyset-only -- no OFFSET, which would
walk and discard every earlier row on each tap and could skip or repeat a row
when a new post arrives mid-browse.

NO TEXT-WAITING STATES. Every step is a button, so this adds nothing to the
surface that Cancel and /start have to be proven against. A search box would
change that, and is deliberately not here.
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.bot.callbacks import BrowsePageCB, BrowsePickCB
from gulbot.bot.keyboards import browse_list_keyboard, browse_product_keyboard, main_menu_keyboard
from gulbot.bot.states import Browse
from gulbot.catalog.hashtags import extract_hashtags
from gulbot.i18n import t
from gulbot.i18n.catalog import CATALOG
from gulbot.models.customer import Customer
from gulbot.sending.telegram import TelegramTransport
from gulbot.services.bouquets import Bouquet, list_bouquets, load_product
from gulbot.utils.render import escape, format_price

log = logging.getLogger("gulbot.bot.browse")

BROWSE_LABELS = set(CATALOG["btn.menu.browse"].values())


def row_label(bouquet: Bouquet, lang: str) -> str:
    """One list row. Price on the same line -- a customer scanning a list is
    choosing on price as much as on name."""
    if bouquet.has_price and bouquet.price_uzs is not None:
        return t("browse.row", lang, name=bouquet.name, price=format_price(bouquet.price_uzs))
    return t("browse.row.no_price", lang, name=bouquet.name)


def caption_is_only_tags(caption: str | None) -> bool:
    """True when copying the post verbatim would show the customer a bare tag.

    `product_name` already answers "is there a name in here", but it applies a
    length cut and a price trim on top; this asks the narrower question, so a
    caption of `#lola 150 000 so'm` still counts as having something to show.
    """
    if not caption:
        return True
    without_tags = caption
    for tag in extract_hashtags(caption):
        without_tags = without_tags.replace(f"#{tag}", " ")
    # Whatever is left after the tags: does any of it carry information?
    return not any(ch.isalnum() for ch in without_tags)


async def _show_page(
    target: Message,
    state: FSMContext,
    session: AsyncSession,
    *,
    shop_id: int,
    lang: str,
    edit: bool,
) -> None:
    """Render the current page from whatever the cursor stack says.

    `edit` rewrites the existing list message rather than sending a new one, so
    paging does not leave a trail of dead lists up the chat.
    """
    data = await state.get_data()
    stack: list[Any] = list(data.get("browse_stack") or [])
    after = tuple(stack[-1]) if stack else None

    listing = await list_bouquets(session, shop_id=shop_id, after=after)
    if not listing.bouquets:
        await state.clear()
        await target.answer(t("browse.empty", lang), reply_markup=main_menu_keyboard(lang))
        return

    await state.update_data(browse_cursor=list(listing.cursor) if listing.cursor else None)
    keyboard = browse_list_keyboard(
        lang,
        [(b.product_id, row_label(b, lang)) for b in listing.bouquets],
        has_prev=bool(stack),
        has_next=listing.has_more,
    )
    body = t("browse.title", lang)
    if edit:
        await target.edit_text(body, reply_markup=keyboard)
    else:
        await target.answer(body, reply_markup=keyboard)
    await state.set_state(Browse.listing)


async def open_browse(
    message: Message, state: FSMContext, session: AsyncSession, customer: Customer, lang: str
) -> None:
    """The main-menu entry."""
    await state.clear()
    await _show_page(message, state, session, shop_id=customer.shop_id, lang=lang, edit=False)


async def page_next(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, customer: Customer, lang: str
) -> None:
    await callback.answer()
    data = await state.get_data()
    cursor = data.get("browse_cursor")
    if cursor is None:
        return
    stack: list[Any] = list(data.get("browse_stack") or [])
    stack.append(cursor)
    await state.update_data(browse_stack=stack)
    await _show_page(
        _target(callback), state, session, shop_id=customer.shop_id, lang=lang, edit=True
    )


async def page_prev(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, customer: Customer, lang: str
) -> None:
    await callback.answer()
    data = await state.get_data()
    stack: list[Any] = list(data.get("browse_stack") or [])
    if stack:
        stack.pop()
    await state.update_data(browse_stack=stack)
    await _show_page(
        _target(callback), state, session, shop_id=customer.shop_id, lang=lang, edit=True
    )


async def back_to_list(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, customer: Customer, lang: str
) -> None:
    """From a product view back to the page it was chosen from.

    A NEW list message, not an edit: the message this button hangs off is the
    copied post, and rewriting the shop's photo into a text list would be a
    strange thing to watch happen.
    """
    await callback.answer()
    await _show_page(
        _target(callback), state, session, shop_id=customer.shop_id, lang=lang, edit=False
    )


async def pick_product(
    callback: CallbackQuery,
    callback_data: BrowsePickCB,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    """Show one bouquet as the shop posted it, with an order button under it."""
    await callback.answer()
    target = _target(callback)
    product = await load_product(
        session, shop_id=customer.shop_id, product_id=callback_data.product_id
    )
    if product is None:
        # Deactivated or deleted between the list being drawn and this tap.
        await target.answer(t("browse.gone", lang))
        return

    await state.set_state(Browse.viewing)
    keyboard = browse_product_keyboard(lang, product.id)
    transport = TelegramTransport(callback.bot) if callback.bot is not None else None

    verbatim = (
        transport is not None
        and product.channel_chat_id is not None
        and product.channel_message_id is not None
        and not caption_is_only_tags(product.caption_raw)
    )
    if verbatim and transport is not None:
        outcome = await transport.copy_message(
            chat_id=target.chat.id,
            from_chat_id=product.channel_chat_id,  # type: ignore[arg-type]
            message_id=product.channel_message_id,  # type: ignore[arg-type]
            reply_markup=keyboard,
        )
        if outcome.ok:
            return
        # The post was deleted from the channel, or the bot lost access to it.
        # Falling back is better than telling a customer a live bouquet is gone.
        log.warning("copy of product %s failed: %s", product.id, outcome.error_code)

    await target.answer_photo(
        photo=product.telegram_file_id,
        caption=_minimal_caption(product, lang),
        reply_markup=keyboard,
    )


def _minimal_caption(product: Any, lang: str) -> str:
    """Our own wording, used when the shop's caption has nothing in it.

    Reuses the reminder's keys, so "narx operator tomonidan tasdiqlanadi" exists
    in exactly one place and the shop and the customer cannot end up reading
    different words for the same situation.
    """
    name = escape(product.name)
    if product.price_uzs:
        return t("reminder.bouquet", lang, name=name, price=format_price(product.price_uzs))
    return t("reminder.bouquet.no_price", lang, name=name)


def _target(callback: CallbackQuery) -> Message:
    message = callback.message
    if message is None:  # pragma: no cover - Telegram always attaches one
        raise RuntimeError("callback without a message")
    return message  # type: ignore[return-value]


def build_browse_router() -> Router:
    router = Router(name="browse")

    # Entry from the main menu. StateFilter(None) so it cannot fire from inside
    # another flow, where the customer meant the word rather than the button.
    router.message.register(open_browse, StateFilter(None), F.text.in_(BROWSE_LABELS))

    router.callback_query.register(
        page_next, Browse.listing, BrowsePageCB.filter(F.action == "next")
    )
    router.callback_query.register(
        page_prev, Browse.listing, BrowsePageCB.filter(F.action == "prev")
    )
    router.callback_query.register(
        back_to_list, Browse.viewing, BrowsePageCB.filter(F.action == "close")
    )
    router.callback_query.register(pick_product, Browse.listing, BrowsePickCB.filter())
    return router
