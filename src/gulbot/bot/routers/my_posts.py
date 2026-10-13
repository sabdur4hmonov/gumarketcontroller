""" "📋 Mening e'lonlarim": edit or delete what is already in the channel (CP23 addendum).

For the shop's explicit owners and staff only (services/published_posts.py
re-checks on every action). Change a published post's price, count or
description (editMessageCaption), switch its flower template
(editMessageMedia: a new overlay and caption), regenerate its story image,
or delete it. The catalogue follows through the SAME indexer path as an
edited channel post; a deleted post deactivates its product.
"""

from __future__ import annotations

from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.announcements.designs import render_post
from gulbot.announcements.extraction import Fields
from gulbot.announcements.flower_templates import ALL_TEMPLATES
from gulbot.announcements.layouts import LAYOUT_IDS, LAYOUTS
from gulbot.announcements.themes import THEMES
from gulbot.bot.callbacks import LogoCB, PostCB
from gulbot.bot.states import PostEdit
from gulbot.i18n import t
from gulbot.models.announcement import AnnouncementDraft
from gulbot.models.product import Product
from gulbot.models.shop import Shop
from gulbot.services import announcements as service
from gulbot.services import published_posts as posts
from gulbot.services import shop_logo
from gulbot.services.indexer import FinalizeResult
from gulbot.services.offload import run_cpu

FIELD_PROMPTS = {
    "price": "Yangi narxni yozing (masalan: 450 ming):",
    "count": "Yangi sonini yozing:",
    "description": "Yangi tavsifni yozing:",
}


def post_button(
    draft: AnnouncementDraft | int, label: str, action: str, value: str = ""
) -> InlineKeyboardButton:
    draft_id = draft if isinstance(draft, int) else draft.id
    return InlineKeyboardButton(
        text=label, callback_data=PostCB(action=action, draft=draft_id, value=value).pack()
    )


def title_of(draft: AnnouncementDraft) -> str:
    f = Fields.from_data(draft.fields)
    return f"{', '.join(f.flowers)} · {f.count} dona · {f.price:,} so'm".replace(",", " ", 1)


async def show_list(message: Message, session: AsyncSession, shop_id: int, actor: int) -> None:
    rows = await posts.my_posts(session, shop_id=shop_id, actor=actor)
    if not rows:
        await message.answer("Hali joylangan e'lon yo'q.")
        return
    await message.answer(
        "📋 Joylangan e'lonlar (oxirgi 10 ta):",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[post_button(d, f"📄 {title_of(d)}"[:60], "open")] for d in rows]
        ),
    )


async def show_post(message: Message, session: AsyncSession, draft: AnnouncementDraft) -> None:
    link = service.post_link(draft.receipts[0])
    product = await session.scalar(
        select(Product).where(
            Product.shop_id == draft.shop_id,
            Product.channel_message_id == draft.receipts[0]["message_id"],
        )
    )
    catalogue = (
        f"Katalog: {product.name} — {product.price_uzs or '?'} so'm"
        + ("" if product.active else " (faol emas)")
        if product
        else "Katalogda topilmadi"
    )
    text = f"📄 {escape(title_of(draft))}\n{link}\n{escape(catalogue)}"
    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    post_button(draft, "💰 Narx", "field", "price"),
                    post_button(draft, "🔢 Soni", "field", "count"),
                    post_button(draft, "✍ Tavsif", "field", "description"),
                ],
                [post_button(draft, "🎨 Shablonni almashtirish", "tpls")],
                [post_button(draft, "📸 Istoriya", "story")],
                [post_button(draft, "🗑 O'chirish", "del")],
                [post_button(0, "↩ Ro'yxat", "list")],
                [
                    InlineKeyboardButton(
                        text="🏷 Do'kon logosi", callback_data=LogoCB(action="show").pack()
                    )
                ],
            ]
        ),
    )


def _report(result: FinalizeResult) -> str:
    return {
        "finalized": "katalog yangilandi",
        "noop": "katalog o'zgarmadi",
        "deactivated": "katalogdan olindi",
        "dropped": "katalogdan olindi",
    }.get(result.outcome.value, "katalog: " + result.outcome.value)


async def menu(message: Message, state: FSMContext, session: AsyncSession, shop_id: int) -> None:
    if message.from_user is None or message.chat.type != "private":
        return
    try:
        await state.clear()
        await show_list(message, session, shop_id, message.from_user.id)
    except service.AnnouncementRefused as exc:
        await message.answer(escape(str(exc)))


async def action(
    callback: CallbackQuery,
    callback_data: PostCB,
    state: FSMContext,
    session: AsyncSession,
    shop_id: int,
    bot: Bot,
) -> None:
    message = callback.message
    if not isinstance(message, Message) or message.chat.type != "private":
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    cb, actor = callback_data, callback.from_user.id
    try:
        if cb.action == "list":
            await show_list(message, session, shop_id, actor)
            await callback.answer()
            return
        draft = await posts.post_for(session, shop_id=shop_id, actor=actor, draft_id=cb.draft)
        if cb.action == "open":
            await show_post(message, session, draft)
        elif cb.action == "field":
            if cb.value not in FIELD_PROMPTS:
                raise service.AnnouncementRefused("Bunday maydon yo'q")
            await state.set_state(PostEdit.value)
            await state.update_data(post_id=draft.id, post_field=cb.value)
            await message.answer(FIELD_PROMPTS[cb.value])
        elif cb.action == "tpls":
            theme = (draft.template or "").partition(".")[0] or service.draft_theme(draft)
            await message.answer(
                f"{THEMES[theme].emoji[0]} Yangi shablonni tanlang:",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [post_button(draft, LAYOUTS[layout].label[0], "tpl", f"{theme}.{layout}")]
                        for layout in LAYOUT_IDS
                    ]
                ),
            )
        elif cb.action == "tpl":
            if cb.value not in ALL_TEMPLATES:
                raise service.AnnouncementRefused("Bunday shablon yo'q")
            shop_name = await session.scalar(select(Shop.name).where(Shop.id == shop_id)) or ""
            fields = Fields.from_data(draft.fields)
            from gulbot.bot.routers.announcements import first_photo

            photo = await first_photo(bot, draft)
            logo = await shop_logo.logo_image(session, shop_id) if draft.logo_on else None
            rendered = await run_cpu(
                render_post,
                photo,
                template=cb.value,
                price=fields.price or 0,
                colour=fields.colour,
                shop_name=shop_name,
                lang=draft.caption_lang,
                logo=logo,
            )
            result = await posts.switch_template(
                session,
                bot,
                shop_id=shop_id,
                actor=actor,
                draft_id=draft.id,
                template=cb.value,
                image=rendered.jpeg,
            )
            await session.commit()
            await message.answer(f"✅ Shablon almashtirildi; {_report(result)}.")
        elif cb.action == "story":
            from gulbot.bot.routers.announcements import send_story_previews

            await send_story_previews(bot, message, session, draft)
        elif cb.action == "del":
            await message.answer(
                "Post kanaldan o'chiriladi va katalogdan olinadi. Ishonchingiz komilmi?",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [post_button(draft, "🗑 Ha, o'chirish", "delok")],
                        [post_button(draft, "↩ Yo'q", "open")],
                    ]
                ),
            )
        elif cb.action == "delok":
            result = await posts.delete_post(
                session, bot, shop_id=shop_id, actor=actor, draft_id=draft.id
            )
            await session.commit()
            await message.answer(f"🗑 O'chirildi; {_report(result)}.")
        else:
            raise service.AnnouncementRefused("Bunday amal yo'q")
        await callback.answer()
    except ValueError as exc:
        await callback.answer(str(exc)[:180], show_alert=True)


async def edit_value(
    message: Message, state: FSMContext, session: AsyncSession, shop_id: int, bot: Bot
) -> None:
    if message.from_user is None or message.chat.type != "private":
        return
    data = await state.get_data()
    try:
        result = await posts.edit_field(
            session,
            bot,
            shop_id=shop_id,
            actor=message.from_user.id,
            draft_id=int(data.get("post_id", 0)),
            field=str(data.get("post_field", "")),
            value=message.text or "",
        )
        await session.commit()
        await state.clear()
        draft = await posts.post_for(
            session, shop_id=shop_id, actor=message.from_user.id, draft_id=int(data["post_id"])
        )
        await message.answer(f"✅ Post yangilandi; {_report(result)}.")
        await show_post(message, session, draft)
    except ValueError as exc:
        await message.answer(escape(str(exc)))


def build_my_posts_router() -> Router:
    router = Router(name="my_posts")
    labels = {t("btn.menu.my_posts", lang) for lang in ("uz", "ru", "en")}
    router.message.register(menu, StateFilter(None), F.text.in_(labels))
    router.callback_query.register(action, PostCB.filter())
    router.message.register(
        edit_value, StateFilter(PostEdit.value), F.text, flags={"catch_all": True}
    )
    return router
