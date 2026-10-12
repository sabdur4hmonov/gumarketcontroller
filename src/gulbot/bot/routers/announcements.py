"""Staff-only photo/text/voice → review → style → exact preview → publish."""

from __future__ import annotations

import asyncio
import io
from collections.abc import Sequence
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
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.announcements.designs import PREVIEW_LONGEST, render_post, stamp_logo
from gulbot.announcements.extraction import Fields
from gulbot.announcements.flower_templates import caption as flower_caption
from gulbot.announcements.flower_templates import split_template
from gulbot.announcements.images import IMAGE_LABELS, IMAGE_STYLES, overlay
from gulbot.announcements.layouts import LAYOUT_IDS, LAYOUTS
from gulbot.announcements.learning import Learned
from gulbot.announcements.lexicon import COLOURS, FLOWERS
from gulbot.announcements.numbers import parse_number
from gulbot.announcements.stories import (
    STORY_LAYOUT_IDS,
    STORY_LAYOUTS,
    STORY_PREVIEW_SCALE,
    render_story,
    story_photo,
)
from gulbot.announcements.templates import CAPTION_LABELS, CAPTION_STYLES, caption, escaped_fit
from gulbot.announcements.themes import THEMES
from gulbot.bot.callbacks import AnnouncementCB
from gulbot.bot.states import Announcement
from gulbot.i18n import t
from gulbot.models.announcement import AnnouncementDraft
from gulbot.models.shop import Shop
from gulbot.services import announcement_learning, instagram, shop_logo
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


def cancel_row(draft: AnnouncementDraft) -> list[InlineKeyboardButton]:
    """ "❌ Bekor qilish" -- on every screen before publication (CP23 addendum)."""
    return [button(draft, "❌ Bekor qilish", "cancel")]


def review_keyboard(draft: AnnouncementDraft) -> InlineKeyboardMarkup:
    """The confirmation screen: every field, the four ways to fix, confirm."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                button(draft, "🌹 Gul turi", "edit", "flowers"),
                button(draft, "🎨 Rang", "edit", "colour"),
            ],
            [button(draft, "🔢 Soni", "edit", "count"), button(draft, "💰 Narxi", "edit", "price")],
            [button(draft, "✍ Tavsif", "edit", "description")],
            [
                button(draft, "✏️ Matnni tuzatish", "retext"),
                button(draft, "🎤 Qaytadan gapirish", "revoice"),
            ],
            [button(draft, "✅ Tasdiqlash", "confirm")],
            [button(draft, "🧠 O'rganilganlar", "learned"), *cancel_row(draft)],
        ]
    )


async def review_text(
    session: AsyncSession,
    draft: AnnouncementDraft,
    *,
    heading: str = "E'lonni tekshiring:",
    learned: Sequence[Learned] = (),
) -> str:
    """What was heard, what was understood (⚠ where unsure), what was learned,
    and exactly what the channel would get -- after EVERY fix."""
    f = Fields.from_data(draft.fields)

    def mark(name: str) -> str:
        return "⚠ " if name in f.uncertain else ""

    lines = [heading]
    if f.raw:
        lines += ["🎤 Eshitilgan matn:", f.raw[:1500], ""]
    lines += [
        f"{mark('flowers')}🌹 Gullar: {', '.join(f.flowers) or 'tanlanmagan'}",
        f"{mark('count')}🔢 Soni: {f.count or 'kiritilmagan'}",
        f"{mark('price')}💰 Narxi: {f.price or 'kiritilmagan'} so'm",
        f"{mark('colour')}🎨 Rang: {f.colour or 'tanlanmagan'}",
        f"✍ Tavsif: {f.description[:800]}",
    ]
    if f.uncertain:
        lines.append("⚠ — shu joylarni tekshiring: noto'g'ri eshitilgan bo'lishi mumkin.")
    lines += [f"⚠ {w}" for w in f.warnings]
    lines += [f"Imlo: {c}" for c in f.corrections[:10]]
    lines += [f"🧠 Avval o'rgangan tuzatish qo'llandi: {a}" for a in f.learned[:10]]
    lines += [f"🧠 Eslab qolindi: «{x.heard}» → «{x.corrected}»" for x in learned]
    text = escaped_fit("\n".join(lines), 2600)
    shop_name = await session.scalar(select(Shop.name).where(Shop.id == draft.shop_id)) or ""
    preview = await service.would_post(session, draft, shop_name)
    if preview is None:
        return text + "\n\n📝 Post ko'rinishi barcha maydonlar to'ldirilgach chiqadi."
    return f"{text}\n\n📝 Kanalga shunday chiqadi:\n<blockquote>{preview}</blockquote>"


async def show_review(
    message: Message,
    draft: AnnouncementDraft,
    session: AsyncSession,
    *,
    learned: Sequence[Learned] = (),
) -> None:
    await message.answer(
        await review_text(session, draft, learned=learned), reply_markup=review_keyboard(draft)
    )


LANG_LABELS = {"uz": "Lotin", "uz_cyrl": "Кирилл", "ru": "Русский"}


def template_label(template: str) -> str:
    theme, layout = split_template(template)
    return f"{theme.emoji[0]} {theme.names[0]} · {layout.label[0]}"


def style_keyboard(draft: AnnouncementDraft) -> InlineKeyboardMarkup:
    if draft.template is not None:
        # CP23: a flower template -- one choice covers caption and image.
        rows = [
            [button(draft, f"🌸 {template_label(draft.template)}", "templates")],
            [
                button(draft, f"🔤 {LANG_LABELS[draft.caption_lang]}", "lang"),
                button(draft, "📚 Boshqa shablonlar", "families"),
            ],
        ]
    else:
        rows = [
            [
                button(draft, f"📝 {CAPTION_LABELS.get(draft.caption_style, 'Matn')}", "captions"),
                button(draft, f"🖼 {IMAGE_LABELS.get(draft.image_style, 'Rasm')}", "images"),
            ],
            [button(draft, "🌸 Gul shablonlari", "templates")],
        ]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            *rows,
            [button(draft, "⭐ Do'kon uchun saqlash", "favourite")],
            [button(draft, f"🏷 Logo: {'✅ bor' if draft.logo_on else '❌ yo‘q'}", "logo")],
            [button(draft, "👁 Aniq ko'rinish", "preview")],
            [button(draft, "✏ Ma'lumotlarni qayta tekshirish", "review")],
            cancel_row(draft),
        ]
    )


def families_keyboard(draft: AnnouncementDraft) -> InlineKeyboardMarkup:
    """Every family: the fifteen flowers, then CP22's own styles."""
    current = service.draft_theme(draft)
    names = [
        button(
            draft,
            f"{'✓ ' if theme.id == current else ''}{theme.emoji[0]} {theme.names[0]}",
            "templates",
            theme.id,
        )
        for theme in THEMES.values()
    ]
    rows = [names[i : i + 2] for i in range(0, len(names), 2)]
    rows.append([button(draft, "📝 Oddiy uslublar (matn + rasm)", "legacy")])
    rows.append([button(draft, "↩ Orqaga", "styles")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def layouts_keyboard(draft: AnnouncementDraft, theme_id: str) -> InlineKeyboardMarkup:
    theme = THEMES[theme_id]
    rows = [
        [
            button(
                draft,
                f"{index}. {'✓ ' if draft.template == f'{theme.id}.{layout}' else ''}"
                f"{LAYOUTS[layout].label[0]}",
                "tpl",
                f"{theme.id}.{layout}",
            )
        ]
        for index, layout in enumerate(LAYOUT_IDS, 1)
    ]
    rows.append([button(draft, "📚 Boshqa shablonlar", "families")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def first_photo(bot: Bot, draft: AnnouncementDraft) -> bytes:
    buffer = io.BytesIO()
    await bot.download(draft.photos[0], destination=buffer)
    return buffer.getvalue()


def _previews(
    photo: bytes,
    theme_id: str,
    fields: Fields,
    shop_name: str,
    lang: str,
    logo: Image.Image | None = None,
) -> list[bytes]:
    return [
        render_post(
            photo,
            template=f"{theme_id}.{layout}",
            price=fields.price or 0,
            colour=fields.colour,
            shop_name=shop_name,
            lang=lang,
            longest=PREVIEW_LONGEST,
            logo=logo,
        ).jpeg
        for layout in LAYOUT_IDS
    ]


async def send_template_previews(
    bot: Bot, message: Message, session: AsyncSession, draft: AnnouncementDraft, theme_id: str
) -> None:
    """The theme's ten layouts on the owner's OWN photo, as one album."""
    shop_name = await session.scalar(select(Shop.name).where(Shop.id == draft.shop_id)) or ""
    fields = Fields.from_data(draft.fields)
    photo = await first_photo(bot, draft)
    logo = await shop_logo.logo_image(session, draft.shop_id) if draft.logo_on else None
    # Pillow is CPU work: off the event loop, so other shops' updates flow.
    images = await asyncio.to_thread(
        _previews, photo, theme_id, fields, shop_name, draft.caption_lang, logo
    )
    await bot.send_media_group(
        message.chat.id,
        media=[
            InputMediaPhoto(
                media=BufferedInputFile(image, filename=f"{theme_id}-{index}.jpg"),
                caption=f"{index}. {LAYOUTS[layout].label[0]}",
            )
            for index, (layout, image) in enumerate(zip(LAYOUT_IDS, images, strict=True), 1)
        ],
    )
    theme = THEMES[theme_id]
    await message.answer(
        f"{theme.emoji[0]} {theme.names[0]}: shablonni tanlang",
        reply_markup=layouts_keyboard(draft, theme_id),
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
        "So'ng guldastani ovoz yoki matn bilan tavsiflang.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[cancel_row(draft)]),
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
        await message.answer(
            f"Suratlar: {len(draft.photos)}/10. Endi ovoz yoki matn yuboring.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[cancel_row(draft)]),
        )
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
        await show_review(message, draft, session)
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


async def retext_text(
    message: Message, state: FSMContext, session: AsyncSession, shop_id: int
) -> None:
    """ "✏️ Matnni tuzatish": learn the short mishearings, extract again, and
    come back to the SAME confirmation screen with the new result."""
    try:
        data = await state.get_data()
        draft = await current(message, state, session, shop_id)
        if draft.revision != data.get("announcement_revision"):
            raise service.AnnouncementRefused("Bu tahrir eskirgan. Oxirgi tugmani bosing")
        if message.from_user is None:
            raise service.AnnouncementRefused("Ruxsat yo'q")
        learned = await service.retext(
            session, draft, actor=message.from_user.id, text=message.text or ""
        )
        await state.set_state(Announcement.review)
        await show_review(message, draft, session, learned=learned)
    except ValueError as exc:
        await message.answer(escape(str(exc)))


async def show_learned(message: Message, session: AsyncSession, draft: AnnouncementDraft) -> None:
    """The shop's learned corrections, each deletable."""
    rows = await announcement_learning.corrections(session, draft.shop_id)
    if not rows:
        text = "🧠 Hali hech narsa o'rganilmagan."
    else:
        text = "🧠 Bot shu do'kon uchun eslab qolgan tuzatishlar:\n" + "\n".join(
            f"• «{escape(r.heard)}» → «{escape(r.corrected)}» ({r.uses} marta)" for r in rows[:30]
        )
    keyboard = [[button(draft, f"🗑 «{r.heard[:24]}»", "unlearn", str(r.id))] for r in rows[:30]]
    keyboard.append([button(draft, "↩ Tekshiruvga qaytish", "review")])
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))


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
        await show_review(message, draft, session)
    except ValueError as exc:
        await message.answer(escape(str(exc)))


STORY_HELP = (
    "📸 Istoriyaga joylash:\n"
    "1. Yuqoridagi FAYLni oching va telefoningizga saqlang — u siqilmagan, "
    "sifati to'liq.\n"
    "2. Instagram → «+» → «Istoriya» → saqlangan rasmni tanlang → «Ulashish».\n"
    "Matn yuqori va pastki chetlardan uzoqda: Instagram tugmalari uni yopmaydi."
)


async def _story_inputs(
    bot: Bot, session: AsyncSession, draft: AnnouncementDraft
) -> tuple[bytes, str, Fields, str, Image.Image | None]:
    shop_name = await session.scalar(select(Shop.name).where(Shop.id == draft.shop_id)) or ""
    logo = await shop_logo.logo_image(session, draft.shop_id) if draft.logo_on else None
    return (
        await first_photo(bot, draft),
        shop_name,
        Fields.from_data(draft.fields),
        service.story_theme(draft),
        logo,
    )


def _story_previews(
    photo: bytes,
    theme: str,
    fields: Fields,
    shop_name: str,
    lang: str,
    logo: Image.Image | None,
) -> list[bytes]:
    image = story_photo(photo)  # decoded once for all ten
    return [
        render_story(
            image,
            theme=theme,
            layout=layout,
            price=fields.price or 0,
            colour=fields.colour,
            shop_name=shop_name,
            lang=lang,
            scale=STORY_PREVIEW_SCALE,
            logo=logo,
        ).jpeg
        for layout in STORY_LAYOUT_IDS
    ]


async def send_story_previews(
    bot: Bot, message: Message, session: AsyncSession, draft: AnnouncementDraft
) -> None:
    photo, shop_name, fields, theme, logo = await _story_inputs(bot, session, draft)
    images = await asyncio.to_thread(
        _story_previews, photo, theme, fields, shop_name, draft.caption_lang, logo
    )
    await bot.send_media_group(
        message.chat.id,
        media=[
            InputMediaPhoto(
                media=BufferedInputFile(image, filename=f"istoriya-{index}.jpg"),
                caption=f"{index}. {STORY_LAYOUTS[layout][0].label[0]}",
            )
            for index, (layout, image) in enumerate(zip(STORY_LAYOUT_IDS, images, strict=True), 1)
        ],
    )
    rows = [
        [button(draft, f"{index}. {STORY_LAYOUTS[layout][0].label[0]}", "storyl", layout)]
        for index, layout in enumerate(STORY_LAYOUT_IDS, 1)
    ]
    await message.answer(
        "Istoriya ko'rinishini tanlang:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )


async def send_story(
    bot: Bot, message: Message, session: AsyncSession, draft: AnnouncementDraft, layout: str
) -> None:
    """The 1080x1920 story: as a DOCUMENT (no recompression) and as a photo."""
    jpeg, name = await _rendered_story(bot, session, draft, layout)
    await bot.send_document(message.chat.id, BufferedInputFile(jpeg, filename=name))
    await bot.send_photo(message.chat.id, BufferedInputFile(jpeg, filename=name))
    if instagram.enabled() and await instagram.active_connection(session, draft.shop_id):
        # CP23 phase 3: only when switched on AND this shop is connected;
        # otherwise the owner shares the image themselves (phase 2).
        await message.answer(
            STORY_HELP,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[button(draft, "📲 Instagram'ga joylash", "igpub", layout)]]
            ),
        )
    else:
        await message.answer(STORY_HELP)


async def _rendered_story(
    bot: Bot, session: AsyncSession, draft: AnnouncementDraft, layout: str
) -> tuple[bytes, str]:
    photo, shop_name, fields, theme, logo = await _story_inputs(bot, session, draft)
    story = await asyncio.to_thread(
        render_story,
        photo,
        theme=theme,
        layout=layout,
        price=fields.price or 0,
        colour=fields.colour,
        shop_name=shop_name,
        lang=draft.caption_lang,
        logo=logo,
    )
    return story.jpeg, f"istoriya-{theme}-{layout}.jpg"


async def queue_instagram_story(
    bot: Bot, message: Message, session: AsyncSession, draft: AnnouncementDraft, layout: str
) -> str:
    """Store the story for Meta and queue the publishing task. Returns the
    owner's message; refusals arrive as InstagramRefused."""
    from gulbot.worker.instagram_tasks import enqueue_story

    jpeg, _ = await _rendered_story(bot, session, draft, layout)
    upload_id, token = await instagram.queue_story(
        session,
        shop_id=draft.shop_id,
        actor=draft.author_id,
        draft_id=draft.id,
        layout=layout,
        jpeg=jpeg,
    )
    await session.commit()  # the worker must see the upload before it runs
    await enqueue_story(upload_id, token)
    lang = await session.scalar(select(Shop.lang).where(Shop.id == draft.shop_id)) or "uz"
    return instagram.message("queued", lang)


async def exact_preview(
    bot: Bot, message: Message, session: AsyncSession, draft: AnnouncementDraft
) -> None:
    if draft.status not in {"confirmed", "preview"}:
        raise service.AnnouncementRefused("Avval tasdiqlang")
    shop_name = await session.scalar(select(Shop.name).where(Shop.id == draft.shop_id))
    f = Fields.from_data(draft.fields)
    media: list[str | BufferedInputFile] = list(draft.photos)
    # The shop's logo goes on EVERY photo of the post (the owner's request).
    logo = await shop_logo.logo_image(session, draft.shop_id) if draft.logo_on else None
    if draft.template is not None:
        # CP23: one flower template sets both the caption and the overlay.
        body = flower_caption(
            f, template=draft.template, shop_name=shop_name or "", lang=draft.caption_lang
        )
        photo = await first_photo(bot, draft)
        themed = await asyncio.to_thread(
            render_post,
            photo,
            template=draft.template,
            price=f.price or 0,
            colour=f.colour,
            shop_name=shop_name or "",
            lang=draft.caption_lang,
            logo=logo,
        )
        media[0] = BufferedInputFile(themed.jpeg, filename="bouquet.jpg")
    else:
        body = caption(f, style=draft.caption_style, shop_name=shop_name or "")
    if draft.template is None and draft.image_style != "none":
        buffer = io.BytesIO()
        await bot.download(draft.photos[0], destination=buffer)
        rendered = overlay(
            buffer.getvalue(),
            style=draft.image_style,
            price=f.price or 0,
            shop_name=shop_name or "",
        )
        if logo is not None:
            rendered = await asyncio.to_thread(stamp_logo, rendered, logo)
        media[0] = BufferedInputFile(rendered, filename="bouquet.jpg")
    if logo is not None:
        # Every photo not already rendered above carries the logo alone.
        for index, item in enumerate(media):
            if isinstance(item, str):
                buffer = io.BytesIO()
                await bot.download(item, destination=buffer)
                stamped = await asyncio.to_thread(stamp_logo, buffer.getvalue(), logo)
                media[index] = BufferedInputFile(stamped, filename=f"bouquet-{index}.jpg")
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
                cancel_row(draft),
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
            await message.answer(
                f"Joylandi: {link}",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[button(draft, "📸 Instagram istoriya", "story")]]
                ),
            )
            await state.clear()
        elif cb.action == "story":
            # CP23 phase 2: the ten story layouts, previewed on the post's photo.
            service.require_published(draft)
            await send_story_previews(bot, message, session, draft)
        elif cb.action == "storyl":
            service.require_published(draft)
            if cb.value not in STORY_LAYOUTS:
                raise service.AnnouncementRefused("Bunday istoriya yo'q")
            await send_story(bot, message, session, draft, cb.value)
        elif cb.action == "igpub":
            # CP23 phase 3: built, off by default; refused in the shop's language.
            service.require_published(draft)
            if cb.value not in STORY_LAYOUTS:
                raise service.AnnouncementRefused("Bunday istoriya yo'q")
            try:
                text = await queue_instagram_story(bot, message, session, draft, cb.value)
            except instagram.InstagramRefused as refused:
                lang = await session.scalar(select(Shop.lang).where(Shop.id == shop_id)) or "uz"
                await callback.answer(instagram.message(refused.code, lang)[:180], show_alert=True)
                return
            await message.answer(text)
        elif cb.action == "confirm":
            service.confirm(draft)
            await service.apply_default_template(session, draft)
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
            # CP23 addendum: a button that replaces a wrong GUESS teaches it.
            taught = (
                None
                if cb.action == "flower" and cb.value not in f.flowers
                else await service.learn_from_button(
                    session, draft, actor=callback.from_user.id, kind=cb.action, added=cb.value
                )
            )
            await state.set_state(Announcement.review)
            if cb.action == "flower":
                note = (
                    f"\n🧠 Eslab qolindi: «{taught.heard}» → «{taught.corrected}»" if taught else ""
                )
                await message.answer(
                    escape("Bir yoki bir nechta gul turini tanlang:" + note),
                    reply_markup=flower_keyboard(draft),
                )
            else:
                await show_review(message, draft, session, learned=[taught] if taught else [])
        elif cb.action == "retext":
            # CP23 addendum: the corrected transcript, extracted again.
            service.editable(draft)
            await state.set_state(Announcement.retext)
            await state.update_data(announcement_revision=draft.revision)
            await message.answer(
                "Tuzatilgan matnni yuboring. Eshitilganni nusxalab, xato so'zni almashtirsangiz "
                "bo'ladi — bot o'sha tuzatishni eslab qoladi.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[cancel_row(draft)]),
            )
        elif cb.action == "revoice":
            service.editable(draft)
            await state.set_state(Announcement.review)
            await message.answer(
                "Yangi ovozli xabar yuboring: oldingi natija butunlay almashtiriladi.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[cancel_row(draft)]),
            )
        elif cb.action == "cancel":
            await service.cancel(session, draft)
            await state.clear()
            await message.answer("❌ Bekor qilindi. Hech narsa saqlanmadi.")
        elif cb.action == "learned":
            await show_learned(message, session, draft)
        elif cb.action == "unlearn":
            if not cb.value.isdigit():
                raise service.AnnouncementRefused("Bunday yozuv yo'q")
            await announcement_learning.forget(
                session, shop_id=draft.shop_id, correction_id=int(cb.value)
            )
            await show_learned(message, session, draft)
        elif cb.action == "review":
            service.invalidate(draft)
            await state.set_state(Announcement.review)
            await show_review(message, draft, session)
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
            if draft.template:
                flower = THEMES[draft.template.partition(".")[0]].names[0]
                saved = f"{flower} uchun sevimli shablon saqlandi."
            else:
                saved = "Do'konning sevimli uslubi saqlandi."
            await message.answer(saved, reply_markup=style_keyboard(draft))
        elif cb.action == "templates":
            # The flower's own ten first; any other family by its id.
            service.editable(draft)
            if draft.status not in {"confirmed", "preview"}:
                raise service.AnnouncementRefused("Avval tasdiqlang")
            theme_id = cb.value or service.draft_theme(draft)
            if theme_id not in THEMES:
                raise service.AnnouncementRefused("Bunday shablon yo'q")
            await send_template_previews(bot, message, session, draft, theme_id)
        elif cb.action == "tpl":
            service.choose_template(draft, cb.value)
            await message.answer(
                f"Tanlandi: {template_label(cb.value)}", reply_markup=style_keyboard(draft)
            )
        elif cb.action == "logo":
            # The shop's logo on this post's photos, or not.
            if draft.status not in {"confirmed", "preview"}:
                raise service.AnnouncementRefused("Avval tasdiqlang")
            draft.logo_on = not draft.logo_on
            service.invalidate(draft, status="confirmed")
            has_logo = await shop_logo.logo_image(session, draft.shop_id) is not None
            note = "" if has_logo else "\nDo'konning logosi hali yo'q: egasi /logo bilan yuboradi."
            await message.answer(
                ("Logo yoqildi." if draft.logo_on else "Logo o'chirildi.") + note,
                reply_markup=style_keyboard(draft),
            )
        elif cb.action == "families":
            service.editable(draft)
            if draft.status not in {"confirmed", "preview"}:
                raise service.AnnouncementRefused("Avval tasdiqlang")
            await message.answer("Barcha shablonlar:", reply_markup=families_keyboard(draft))
        elif cb.action == "lang":
            service.next_caption_lang(draft)
            await message.answer(
                f"Matn tili: {LANG_LABELS[draft.caption_lang]}", reply_markup=style_keyboard(draft)
            )
        elif cb.action == "legacy":
            service.editable(draft)
            if draft.status not in {"confirmed", "preview"}:
                raise service.AnnouncementRefused("Avval tasdiqlang")
            service.choose_style(draft, kind="caption", value=draft.caption_style)
            await message.answer("Oddiy uslublar:", reply_markup=style_keyboard(draft))
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
    router.message.register(
        retext_text, StateFilter(Announcement.retext), F.text, flags={"catch_all": True}
    )
    return router
