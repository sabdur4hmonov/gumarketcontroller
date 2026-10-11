"""Staff-only photo/text/voice → review → style → exact preview → publish."""

from __future__ import annotations

import io
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.announcements.extraction import Fields
from gulbot.announcements.images import IMAGE_LABELS, IMAGE_STYLES, overlay
from gulbot.announcements.lexicon import COLOURS, FLOWERS
from gulbot.announcements.numbers import parse_number
from gulbot.announcements.templates import CAPTION_LABELS, CAPTION_STYLES, caption, escaped_fit
from gulbot.bot.callbacks import AnnouncementCB
from gulbot.bot.states import Announcement
from gulbot.i18n import t
from gulbot.models.announcement import AnnouncementDraft
from gulbot.models.shop import Shop
from gulbot.services import announcements as service


def button(
    draft: AnnouncementDraft, label: str, action: str, value: str = ""
) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=label,
        callback_data=AnnouncementCB(
            action=action, draft=draft.id, revision=draft.revision, value=value
        ).pack(),
    )


def review_keyboard(draft: AnnouncementDraft) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                button(draft, "🌹 Gul turi", "edit", "flowers"),
                button(draft, "🎨 Rang", "edit", "colour"),
            ],
            [button(draft, "🔢 Soni", "edit", "count"), button(draft, "💰 Narxi", "edit", "price")],
            [button(draft, "✍ Tavsif", "edit", "description")],
            [button(draft, "✅ Tasdiqlash", "confirm")],
        ]
    )


async def show_review(message: Message, draft: AnnouncementDraft) -> None:
    f = Fields.from_data(draft.fields)
    lines = [
        "E'lonni tekshiring:",
        f"Gullar: {', '.join(f.flowers) or '⚠ tanlanmagan'}",
        f"Soni: {f.count or '⚠ kiritilmagan'}",
        f"Narxi: {f.price or '⚠ kiritilmagan'} so'm",
        f"Rang: {f.colour or '⚠ tanlanmagan'}",
        f"Tavsif: {f.description[:1000]}",
    ]
    if f.raw:
        lines.append(f"Asl matn: {f.raw[:1000]}")
    lines.extend(f"⚠ {w}" for w in f.warnings)
    lines.extend(f"Imlo: {c}" for c in f.corrections[:10])
    await message.answer(escaped_fit("\n".join(lines), 3900), reply_markup=review_keyboard(draft))


def style_keyboard(draft: AnnouncementDraft) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                button(draft, f"📝 {CAPTION_LABELS.get(draft.caption_style, 'Matn')}", "captions"),
                button(draft, f"🖼 {IMAGE_LABELS.get(draft.image_style, 'Rasm')}", "images"),
            ],
            [button(draft, "⭐ Do'kon uchun saqlash", "favourite")],
            [button(draft, "👁 Aniq ko'rinish", "preview")],
            [button(draft, "✏ Ma'lumotlarni qayta tekshirish", "review")],
        ]
    )


def flower_keyboard(draft: AnnouncementDraft) -> InlineKeyboardMarkup:
    selected = Fields.from_data(draft.fields).flowers
    rows = [
        [button(draft, ("✓ " if name in selected else "") + name, "flower", name)]
        for name in FLOWERS
    ]
    rows.append([button(draft, "✅ Tayyor", "review")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def enter(message: Message, state: FSMContext, session: AsyncSession, shop_id: int) -> None:
    if message.from_user is None or message.chat.type != "private":
        return
    try:
        draft = await service.new_draft(session, shop_id=shop_id, actor=message.from_user.id)
    except service.AnnouncementRefused as exc:
        await message.answer(str(exc))
        return
    await state.clear()
    await state.set_state(Announcement.photos)
    await state.update_data(announcement_id=draft.id)
    await message.answer(
        "1–10 ta surat yuboring (albom ham mumkin). "
        "So'ng guldastani ovoz yoki matn bilan tavsiflang."
    )


async def current(
    message: Message, state: FSMContext, session: AsyncSession, shop_id: int
) -> AnnouncementDraft:
    if message.from_user is None or message.chat.type != "private":
        raise service.AnnouncementRefused("Ruxsat yo'q")
    data = await state.get_data()
    return await service.draft_for(
        session,
        shop_id=shop_id,
        actor=message.from_user.id,
        draft_id=int(data.get("announcement_id", 0)),
    )


async def receive_photo(
    message: Message, state: FSMContext, session: AsyncSession, shop_id: int
) -> None:
    try:
        draft = await current(message, state, session, shop_id)
        service.editable(draft)
        if not message.photo:
            return
        photo = message.photo[-1]
        if (photo.file_size or 0) > 10_000_000 or len(draft.photos) >= 10:
            raise service.AnnouncementRefused("Ko'pi bilan 10 ta surat, har biri 10 MB gacha")
        if photo.file_id not in draft.photos:
            draft.photos = [*draft.photos, photo.file_id]
            service.invalidate(draft, status="review" if draft.fields else "collecting")
        await message.answer(f"Suratlar: {len(draft.photos)}/10. Endi ovoz yoki matn yuboring.")
    except service.AnnouncementRefused as exc:
        await message.answer(escape(str(exc)))


async def receive_text(
    message: Message, state: FSMContext, session: AsyncSession, shop_id: int
) -> None:
    try:
        draft = await current(message, state, session, shop_id)
        if not draft.photos:
            raise service.AnnouncementRefused("Avval surat yuboring")
        if draft.status == "transcribing":
            draft.status = "review"  # Text fallback supersedes this queued result.
        await service.parse_description(session, draft, message.text or "")
        await state.set_state(Announcement.review)
        await show_review(message, draft)
    except ValueError as exc:
        await message.answer(escape(str(exc)))


async def receive_voice(
    message: Message, state: FSMContext, session: AsyncSession, shop_id: int
) -> None:
    from gulbot.worker.stt_tasks import enqueue_transcription

    try:
        draft = await current(message, state, session, shop_id)
        service.editable(draft)
        if not draft.photos or message.voice is None:
            raise service.AnnouncementRefused("Avval surat yuboring")
        if message.voice.duration > 120 or (message.voice.file_size or 0) > 10_000_000:
            raise service.AnnouncementRefused("Ovoz 2 daqiqa va 10 MB gacha bo'lishi kerak")
        acknowledgement = await message.answer("Ovoz qayta ishlanmoqda...")
        service.invalidate(draft)
        draft.status = "transcribing"
        draft.acknowledgement_id = acknowledgement.message_id
        await session.commit()  # Worker must see the draft before it is queued.
        try:
            draft.job_id = await enqueue_transcription(
                shop_id=shop_id,
                actor=draft.author_id,
                draft_id=draft.id,
                revision=draft.revision,
                file_id=message.voice.file_id,
            )
            await session.commit()
        except Exception:
            draft.status = "review"
            await message.answer("Ovoz xizmati hozir ishlamadi. Tavsifni matn bilan yuboring.")
        await state.set_state(Announcement.review)
    except ValueError as exc:
        await message.answer(escape(str(exc)))


async def edit_text(
    message: Message, state: FSMContext, session: AsyncSession, shop_id: int
) -> None:
    try:
        data = await state.get_data()
        draft = await current(message, state, session, shop_id)
        if draft.revision != data.get("announcement_revision"):
            raise service.AnnouncementRefused("Bu tahrir eskirgan. Oxirgi tugmani bosing")
        f = Fields.from_data(draft.fields)
        value, key = message.text or "", data.get("announcement_field")
        if key == "count":
            count = parse_number(value)
            if not 1 <= count <= 9999:
                raise ValueError("Soni 1–9999")
            f.count = count
        elif key == "price":
            price = parse_number(value)
            if not 10_000 <= price <= 50_000_000:
                raise ValueError("Narxi 10 000–50 000 000 so'm")
            f.price = price
        elif key == "description" and len(value) <= 4096:
            f.description = value
        else:
            raise ValueError("Tahrir maydoni yoki matn noto'g'ri")
        service.invalidate(draft)
        draft.fields = f.data()
        await state.set_state(Announcement.review)
        await show_review(message, draft)
    except ValueError as exc:
        await message.answer(escape(str(exc)))


async def exact_preview(
    bot: Bot, message: Message, session: AsyncSession, draft: AnnouncementDraft
) -> None:
    if draft.status not in {"confirmed", "preview"}:
        raise service.AnnouncementRefused("Avval tasdiqlang")
    shop_name = await session.scalar(select(Shop.name).where(Shop.id == draft.shop_id))
    f = Fields.from_data(draft.fields)
    body = caption(f, style=draft.caption_style, shop_name=shop_name or "")
    media: list[str | BufferedInputFile] = list(draft.photos)
    if draft.image_style != "none":
        buffer = io.BytesIO()
        await bot.download(draft.photos[0], destination=buffer)
        rendered = overlay(
            buffer.getvalue(),
            style=draft.image_style,
            price=f.price or 0,
            shop_name=shop_name or "",
        )
        media[0] = BufferedInputFile(rendered, filename="bouquet.jpg")
    if len(media) == 1:
        messages = [
            await bot.send_photo(message.chat.id, media[0], caption=body, parse_mode="HTML")
        ]
    else:
        messages = await bot.send_media_group(
            message.chat.id,
            media=[
                InputMediaPhoto(media=m, caption=body if i == 0 else None, parse_mode="HTML")
                for i, m in enumerate(media)
            ],
        )
    if any(not m.photo for m in messages):
        raise service.AnnouncementRefused("Surat ko'rinishi tayyorlanmadi")
    draft.preview_media = [m.photo[-1].file_id for m in messages if m.photo]
    draft.preview_caption = body
    draft.status = "preview"
    await message.answer(
        "Shu ko'rinish kanalga joylanadi.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [button(draft, "📢 Joylash", "publish")],
                [button(draft, "🎨 Uslubni o'zgartirish", "styles")],
            ]
        ),
    )


async def action(
    callback: CallbackQuery,
    callback_data: AnnouncementCB,
    state: FSMContext,
    session: AsyncSession,
    shop_id: int,
    bot: Bot,
) -> None:
    message = callback.message
    if not isinstance(message, Message) or message.chat.type != "private":
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    cb = callback_data
    try:
        draft = await service.draft_for(
            session,
            shop_id=shop_id,
            actor=callback.from_user.id,
            draft_id=cb.draft,
            revision=cb.revision,
        )
        await state.update_data(announcement_id=draft.id)
        if cb.action == "publish":
            link = await service.publish(
                session,
                bot=bot,
                shop_id=shop_id,
                actor=callback.from_user.id,
                draft_id=cb.draft,
                revision=cb.revision,
            )
            await message.answer(f"Joylandi: {link}")
            await state.clear()
        elif cb.action == "confirm":
            service.confirm(draft)
            await state.set_state(Announcement.styling)
            await message.answer(
                "Matn va rasm uslubini tanlang.", reply_markup=style_keyboard(draft)
            )
        elif cb.action == "edit":
            service.editable(draft)
            if cb.value in {"flowers", "colour"}:
                if cb.value == "flowers":
                    markup = flower_keyboard(draft)
                else:
                    rows = [[button(draft, label, "colour", label)] for label in COLOURS]
                    rows.append([button(draft, "✅ Tayyor", "review")])
                    markup = InlineKeyboardMarkup(inline_keyboard=rows)
                await message.answer("Tanlang:", reply_markup=markup)
            elif cb.value in {"count", "price", "description"}:
                await state.set_state(Announcement.editing)
                await state.update_data(
                    announcement_field=cb.value, announcement_revision=draft.revision
                )
                await message.answer("Yangi qiymatni yozing:")
            else:
                raise service.AnnouncementRefused("Bunday maydon yo'q")
        elif cb.action in {"flower", "colour"}:
            service.editable(draft)
            f = Fields.from_data(draft.fields)
            if cb.action == "flower" and cb.value in FLOWERS:
                f.flowers = (
                    [name for name in f.flowers if name != cb.value]
                    if cb.value in f.flowers
                    else [*f.flowers, cb.value]
                )
                if len(f.flowers) > 8:
                    raise service.AnnouncementRefused("Ko'pi bilan 8 xil gul")
            elif cb.action == "colour" and cb.value in COLOURS:
                f.colour = cb.value
            else:
                raise service.AnnouncementRefused("Bunday gul/rang yo'q")
            service.invalidate(draft)
            draft.fields = f.data()
            await state.set_state(Announcement.review)
            if cb.action == "flower":
                await message.answer(
                    "Bir yoki bir nechta gul turini tanlang:", reply_markup=flower_keyboard(draft)
                )
            else:
                await show_review(message, draft)
        elif cb.action == "review":
            service.invalidate(draft)
            await state.set_state(Announcement.review)
            await show_review(message, draft)
        elif cb.action in {"captions", "images"}:
            if draft.status not in {"confirmed", "preview"}:
                raise service.AnnouncementRefused("Avval tasdiqlang")
            options = list(CAPTION_STYLES) if cb.action == "captions" else ["none", *IMAGE_STYLES]
            kind = "caption" if cb.action == "captions" else "image"
            labels = CAPTION_LABELS if kind == "caption" else IMAGE_LABELS
            await message.answer(
                "Uslubni tanlang:",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[button(draft, labels[name], kind, name)] for name in options]
                ),
            )
        elif cb.action in {"caption", "image"}:
            service.choose_style(draft, kind=cb.action, value=cb.value)
            labels = CAPTION_LABELS if cb.action == "caption" else IMAGE_LABELS
            await message.answer(
                f"Tanlandi: {labels[cb.value]}", reply_markup=style_keyboard(draft)
            )
        elif cb.action == "favourite":
            await service.save_favourite(
                session, shop_id=shop_id, actor=callback.from_user.id, draft=draft
            )
            await message.answer(
                "Do'konning sevimli uslubi saqlandi.", reply_markup=style_keyboard(draft)
            )
        elif cb.action == "styles":
            service.editable(draft)
            if draft.status not in {"confirmed", "preview"}:
                raise service.AnnouncementRefused("Avval tasdiqlang")
            await message.answer("Uslublar:", reply_markup=style_keyboard(draft))
        elif cb.action == "preview":
            await exact_preview(bot, message, session, draft)
        else:
            raise service.AnnouncementRefused("Bunday amal yo'q")
        await callback.answer()
    except ValueError as exc:
        await callback.answer(str(exc)[:180], show_alert=True)


def build_announcement_router() -> Router:
    router = Router(name="announcements")
    labels = {t("btn.menu.announcement", lang) for lang in ("uz", "ru", "en")}
    router.message.register(enter, StateFilter(None), F.text.in_(labels))
    router.callback_query.register(action, AnnouncementCB.filter())
    collecting = StateFilter(Announcement.photos, Announcement.review)
    router.message.register(receive_photo, collecting, F.photo)
    router.message.register(receive_voice, collecting, F.voice)
    router.message.register(receive_text, collecting, F.text, flags={"catch_all": True})
    router.message.register(
        edit_text, StateFilter(Announcement.editing), F.text, flags={"catch_all": True}
    )
    return router
