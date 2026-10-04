"""Dress-code colours (CP17): picked from a fixed palette, never typed.

"🎨 Ranglar" in a taklifnoma's edit menu opens the palette. Each tap toggles a
colour (at most COLORS_MAX) in the FSM and redraws the keyboard; "Tayyor"
saves them all at once through share_pages.update_page -- scoped, capped and
validated like every other edit -- and "Ranglarsiz" removes them.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.bot.callbacks import ColorCB
from gulbot.bot.states import EditPage
from gulbot.i18n import t
from gulbot.models.customer import Customer
from gulbot.models.share_page import SharePage
from gulbot.web import sections


def colors_keyboard(lang: str, chosen: list[str]) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=("✓ " if key in chosen else "") + names[lang],
            callback_data=ColorCB(color=key).pack(),
        )
        for key, (_hex, names) in sections.DRESS_PALETTE.items()
    ]
    rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
    rows.append(
        [
            InlineKeyboardButton(
                text=t("ibtn.pages.colors_none", lang), callback_data=ColorCB(color="none").pack()
            ),
            InlineKeyboardButton(
                text=t("ibtn.pages.photo_done", lang), callback_data=ColorCB(color="done").pack()
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def start_color_edit(target: Message, state: FSMContext, page: SharePage, lang: str) -> None:
    chosen = sections.colors_of(page.dress_colors)
    await state.clear()
    await state.update_data(edit_page_id=page.id, edit_field="dress_colors", colors=chosen)
    await state.set_state(EditPage.choosing_colors)
    await target.answer(
        t("pages.ask_colors", lang, max=sections.COLORS_MAX),
        reply_markup=colors_keyboard(lang, chosen),
    )


async def on_color(
    callback: CallbackQuery,
    callback_data: ColorCB,
    state: FSMContext,
    session: AsyncSession,
    customer: Customer,
    lang: str,
) -> None:
    from gulbot.bot.routers.share_page_edit import _save
    from gulbot.bot.routers.share_pages import _target

    if await state.get_state() != EditPage.choosing_colors.state:
        await callback.answer()
        return
    data = await state.get_data()
    page_id = data.get("edit_page_id")
    chosen = [c for c in data.get("colors", []) if c in sections.DRESS_PALETTE]
    if not isinstance(page_id, int):
        await callback.answer()
        await state.clear()
        return
    action = callback_data.color
    if action in ("done", "none"):
        await callback.answer()
        changes: dict[str, object] = {"dress_colors": tuple(chosen) if action == "done" else None}
        await _save(_target(callback), state, session, customer, lang, page_id, changes)
        return
    if action not in sections.DRESS_PALETTE:
        await callback.answer()
        return
    if action in chosen:
        chosen.remove(action)
    elif len(chosen) >= sections.COLORS_MAX:
        await callback.answer(t("pages.colors_max", lang, max=sections.COLORS_MAX), show_alert=True)
        return
    else:
        chosen.append(action)
    await callback.answer()
    await state.update_data(colors=chosen)
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=colors_keyboard(lang, chosen))


def build_share_page_colors_router() -> Router:
    router = Router(name="share_page_colors")
    router.callback_query.register(on_color, ColorCB.filter())
    return router
