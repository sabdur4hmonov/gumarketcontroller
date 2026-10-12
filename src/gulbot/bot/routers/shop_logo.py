"""/logo: the shop owner sends the shop's own logo (CP23 addendum).

The logo then appears on every photo of the shop's announcements and on its
story images, in a corner clear of the text. Owners only -- the shop's
explicit owner_telegram_ids; staff publish, owners decide the brand.
A PNG sent as a FILE keeps its transparency; a photo works too.
"""

from __future__ import annotations

import asyncio
import io

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.announcements.designs import render_post
from gulbot.bot.callbacks import LogoCB
from gulbot.bot.states import ShopLogoUpload
from gulbot.models.shop import Shop
from gulbot.services import shop_logo

ASK = (
    "Do'kon logosini yuboring. Shaffof fonli logo uchun uni PNG FAYL qilib yuboring "
    "(📎 → Fayl); oddiy rasm ham bo'ladi."
)
SAMPLE_PRICE = 450_000


def _keyboard(has_logo: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="🔄 Yangi logo", callback_data=LogoCB(action="new").pack())]]
    if has_logo:
        rows.append(
            [InlineKeyboardButton(text="🗑 O'chirish", callback_data=LogoCB(action="remove").pack())]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _sample(logo: Image.Image, shop_name: str) -> bytes:
    """How the logo will sit on a post: a plain sample photo, classic layout."""
    blank = io.BytesIO()
    Image.new("RGB", (900, 1200), "#d9c3b5").save(blank, format="JPEG")
    return render_post(
        blank.getvalue(),
        template="atirgul.classic",
        price=SAMPLE_PRICE,
        colour="qizil",
        shop_name=shop_name,
        logo=logo,
    ).jpeg


async def show(message: Message, session: AsyncSession, shop_id: int, actor: int) -> None:
    if not await shop_logo.is_owner(session, shop_id=shop_id, actor=actor):
        await message.answer("Logoni faqat do'kon egasi o'rnatadi.")
        return
    logo = await shop_logo.logo_image(session, shop_id)
    if logo is None:
        await message.answer("Do'konning logosi hali yo'q.\n" + ASK, reply_markup=_keyboard(False))
        return
    png = io.BytesIO()
    logo.save(png, format="PNG")
    await message.answer_document(
        BufferedInputFile(png.getvalue(), filename="logo.png"),
        caption="Hozirgi logo. Har bir e'lon rasmida va istoriyada chiqadi.",
        reply_markup=_keyboard(True),
    )


async def command(message: Message, state: FSMContext, session: AsyncSession, shop_id: int) -> None:
    if message.from_user is None or message.chat.type != "private":
        return
    await state.clear()
    await show(message, session, shop_id, message.from_user.id)


async def action(
    callback: CallbackQuery,
    callback_data: LogoCB,
    state: FSMContext,
    session: AsyncSession,
    shop_id: int,
) -> None:
    message = callback.message
    actor = callback.from_user.id
    if not isinstance(message, Message) or message.chat.type != "private":
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    if not await shop_logo.is_owner(session, shop_id=shop_id, actor=actor):
        await callback.answer("Logoni faqat do'kon egasi o'rnatadi", show_alert=True)
        return
    if callback_data.action == "show":
        await show(message, session, shop_id, actor)
    elif callback_data.action == "new":
        await state.set_state(ShopLogoUpload.waiting)
        await message.answer(ASK)
    elif callback_data.action == "remove":
        await shop_logo.remove_logo(session, shop_id=shop_id, actor=actor)
        await message.answer("🗑 Logo o'chirildi: endi rasmlarda chiqmaydi.")
    else:
        await callback.answer("Bunday amal yo'q", show_alert=True)
        return
    await callback.answer()


async def receive(
    message: Message, state: FSMContext, session: AsyncSession, shop_id: int, bot: Bot
) -> None:
    if message.from_user is None or message.chat.type != "private":
        return
    if message.photo:
        file_id, size = message.photo[-1].file_id, message.photo[-1].file_size or 0
    elif message.document and (message.document.mime_type or "").startswith("image/"):
        file_id, size = message.document.file_id, message.document.file_size or 0
    else:
        await message.answer(ASK)
        return
    if size > shop_logo.MAX_BYTES:
        await message.answer("Logo fayli 10 MB dan oshmasin.")
        return
    buffer = io.BytesIO()
    await bot.download(file_id, destination=buffer)
    try:
        saved = await shop_logo.set_logo(
            session, shop_id=shop_id, actor=message.from_user.id, data=buffer.getvalue()
        )
    except shop_logo.LogoRefused as refused:
        await message.answer(str(refused))
        return
    await session.commit()
    await state.clear()
    logo = await shop_logo.logo_image(session, shop_id)
    name = await session.scalar(select(Shop.name).where(Shop.id == shop_id)) or ""
    if logo is not None:
        sample = await asyncio.to_thread(_sample, logo, name)
        await message.answer_photo(
            BufferedInputFile(sample, filename="logo-namuna.jpg"),
            caption=(
                f"✅ Logo saqlandi ({saved.width}×{saved.height}). "
                "Endi har bir e'lon rasmida va istoriyada shunday chiqadi."
            ),
        )


def build_shop_logo_router() -> Router:
    router = Router(name="shop_logo")
    router.message.register(command, Command("logo"))
    router.callback_query.register(action, LogoCB.filter())
    router.message.register(
        receive,
        StateFilter(ShopLogoUpload.waiting),
        F.photo | F.document,
        flags={"catch_all": True},
    )
    return router
