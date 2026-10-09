"""Photos on a page (CP17): the Foto design's frame, and an invitation's gallery.

Creation: choosing the Foto design asks for one photo, which may be skipped.
Only the photo's Telegram file id waits in the FSM -- the bytes are fetched
once the page exists, cleaned (services/share_page_photos.py: re-encoded, no
EXIF or GPS) and stored with it. A photo that will not clean does not cost the
page: the page is made, and the creator is told the photo was not kept.

Editing, at the same link: on an invitation "🖼 Suratlar" takes photos one
message at a time, up to six (the first is the Foto frame), with "clear all"
and "done"; on a Foto Ha/Yo'q page "🖼 Rasm" takes one, replacing the old.

Only a PHOTO is taken. A file sent as a document is refused with a hint:
Telegram's own photo path is what keeps the upload small.
"""

from __future__ import annotations

import io
import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.bot.callbacks import PhotoCB
from gulbot.bot.keyboards import main_menu_keyboard
from gulbot.bot.states import EditPage, InvitePage, YesNoPage
from gulbot.i18n import t
from gulbot.models.customer import Customer
from gulbot.models.share_page import GALLERY_MAX, PageKind, SharePage
from gulbot.services import share_page_photos
from gulbot.services.premium import PremiumLocked
from gulbot.services.share_page_photos import MAX_INPUT_BYTES, GalleryFull, PhotoRefused
from gulbot.utils.render import escape
from gulbot.web import links

log = logging.getLogger("gulbot.bot.share_page_photo")


async def download_photo(bot: Bot, file_id: str) -> bytes:
    """The photo's bytes from Telegram. A seam: tests replace it."""
    buffer = io.BytesIO()
    await bot.download(file_id, destination=buffer)
    return buffer.getvalue()


def skip_photo_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("ibtn.pages.photo_skip", lang),
                    callback_data=PhotoCB(action="skip").pack(),
                )
            ]
        ]
    )


async def ask_photo(target: Message, state: FSMContext, lang: str, next_state: object) -> None:
    await state.set_state(next_state)  # type: ignore[arg-type]
    await target.answer(t("pages.ask_photo", lang), reply_markup=skip_photo_keyboard(lang))


def largest(message: Message) -> tuple[str, int] | None:
    if not message.photo:
        return None
    size = message.photo[-1]
    return size.file_id, int(size.file_size or 0)


async def creation_photo(message: Message, state: FSMContext, lang: str) -> None:
    """A photo during creation: remember it, then carry on with the flow."""
    found = largest(message)
    if found is None:
        return
    file_id, size = found
    if size > MAX_INPUT_BYTES:
        await message.answer(t("pages.photo_too_big", lang))
        return
    await state.update_data(photo_file_id=file_id)
    await message.answer(t("pages.photo_received", lang))
    await _continue(message, state, lang)


async def creation_not_a_photo(message: Message, lang: str) -> None:
    await message.answer(t("pages.photo_send_as_photo", lang))


async def _continue(target: Message, state: FSMContext, lang: str) -> None:
    from gulbot.bot.routers import share_pages

    current = await state.get_state()
    if current == YesNoPage.sending_photo.state:
        await share_pages.ask_notify(target, state, lang)
    elif current == InvitePage.sending_photo.state:
        await share_pages.invite_summary(target, state, lang)


async def store_after_create(
    bot: Bot | None,
    target: Message,
    session: AsyncSession,
    customer: Customer,
    page_id: int,
    file_id: str | None,
    lang: str,
) -> None:
    """Called once the page is committed. A failure here never undoes it."""
    if not file_id or bot is None:
        return
    try:
        raw = await download_photo(bot, file_id)
        stored = await share_page_photos.store_photo(
            session, shop_id=customer.shop_id, customer_id=customer.id, page_id=page_id, raw=raw
        )
    except PremiumLocked:
        await session.rollback()
        await target.answer(t("premium.locked", lang))
        return
    except PhotoRefused:
        await session.rollback()
        await target.answer(t("pages.photo_refused", lang))
        return
    except Exception:  # a Telegram download that failed
        await session.rollback()
        log.exception("page %s: could not fetch its photo", page_id)
        await target.answer(t("pages.photo_refused", lang))
        return
    if stored is not None:
        await session.commit()


def gallery_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("ibtn.pages.photo_clear", lang),
                    callback_data=PhotoCB(action="clear").pack(),
                ),
                InlineKeyboardButton(
                    text=t("ibtn.pages.photo_done", lang),
                    callback_data=PhotoCB(action="done").pack(),
                ),
            ]
        ]
    )


async def start_photo_edit(
    target: Message, state: FSMContext, session: AsyncSession, page: SharePage, lang: str
) -> None:
    await state.clear()
    await state.update_data(edit_page_id=page.id, edit_field="photo")
    await state.set_state(EditPage.sending_photo)
    if page.kind == PageKind.INVITE:
        count = await share_page_photos.photo_count(session, page_id=page.id)
        await target.answer(
            t("pages.ask_gallery", lang, n=count, max=GALLERY_MAX),
            reply_markup=gallery_keyboard(lang),
        )
    else:
        await target.answer(t("pages.ask_photo", lang))


async def _finish_edit(
    target: Message, state: FSMContext, session: AsyncSession, customer: Customer, lang: str
) -> None:
    from gulbot.bot.routers.share_page_edit import edit_menu_keyboard
    from gulbot.services.share_pages import get_own_page

    data = await state.get_data()
    await state.clear()
    page_id = data.get("edit_page_id")
    page = (
        await get_own_page(
            session, shop_id=customer.shop_id, customer_id=customer.id, page_id=page_id
        )
        if isinstance(page_id, int)
        else None
    )
    if page is None:
        await target.answer(t("pages.gone", lang), reply_markup=main_menu_keyboard(lang))
        return
    await target.answer(
        t("pages.edit_saved", lang, url=escape(links.page_url(page.token))),
        reply_markup=main_menu_keyboard(lang),
        disable_web_page_preview=True,
    )
    await target.answer(t("pages.edit_menu", lang), reply_markup=edit_menu_keyboard(lang, page))


async def edit_photo(
    message: Message, state: FSMContext, session: AsyncSession, customer: Customer, lang: str
) -> None:
    """A photo while editing: added to an invitation's gallery, or replacing a
    Ha/Yo'q page's one photo (which also ends the edit)."""
    data = await state.get_data()
    page_id = data.get("edit_page_id")
    found = largest(message)
    if not isinstance(page_id, int) or found is None or message.bot is None:
        return
    file_id, size = found
    if size > MAX_INPUT_BYTES:
        await message.answer(t("pages.photo_too_big", lang))
        return
    try:
        raw = await download_photo(message.bot, file_id)
        stored = await share_page_photos.store_photo(
            session, shop_id=customer.shop_id, customer_id=customer.id, page_id=page_id, raw=raw
        )
    except GalleryFull:
        await session.rollback()
        await message.answer(
            t("pages.gallery_full", lang, max=GALLERY_MAX), reply_markup=gallery_keyboard(lang)
        )
        return
    except PremiumLocked:
        await session.rollback()
        await state.clear()
        await message.answer(t("premium.locked", lang), reply_markup=main_menu_keyboard(lang))
        return
    except PhotoRefused:
        await session.rollback()
        await message.answer(t("pages.photo_unreadable", lang))
        return
    if stored is None:
        await state.clear()
        await message.answer(t("pages.gone", lang), reply_markup=main_menu_keyboard(lang))
        return
    await session.commit()
    page = await session.get(SharePage, page_id)
    if page is not None and page.kind != PageKind.INVITE:
        await _finish_edit(message, state, session, customer, lang)
        return
    count = await share_page_photos.photo_count(session, page_id=page_id)
    await message.answer(
        t("pages.gallery_added", lang, n=count, max=GALLERY_MAX),
        reply_markup=gallery_keyboard(lang),
    )


async def clear_gallery(
    target: Message, state: FSMContext, session: AsyncSession, customer: Customer, lang: str
) -> None:
    data = await state.get_data()
    page_id = data.get("edit_page_id")
    if not isinstance(page_id, int):
        return
    cleared = await share_page_photos.clear_photos(
        session, shop_id=customer.shop_id, customer_id=customer.id, page_id=page_id
    )
    if not cleared:
        await state.clear()
        await target.answer(t("pages.gone", lang), reply_markup=main_menu_keyboard(lang))
        return
    await session.commit()
    await target.answer(
        t("pages.gallery_cleared", lang, max=GALLERY_MAX), reply_markup=gallery_keyboard(lang)
    )


async def skip_photo(callback_message: Message, state: FSMContext, lang: str) -> None:
    await state.update_data(photo_file_id=None)
    await _continue(callback_message, state, lang)


def build_share_page_photo_router() -> Router:
    from aiogram.types import CallbackQuery

    async def on_photo_button(
        callback: CallbackQuery,
        callback_data: PhotoCB,
        state: FSMContext,
        session: AsyncSession,
        customer: Customer,
        lang: str,
    ) -> None:
        await callback.answer()
        if callback.message is None:  # pragma: no cover
            return
        target: Message = callback.message  # type: ignore[assignment]
        current = await state.get_state()
        if callback_data.action == "skip" and current in (
            YesNoPage.sending_photo.state,
            InvitePage.sending_photo.state,
        ):
            await skip_photo(target, state, lang)
        elif callback_data.action == "clear" and current == EditPage.sending_photo.state:
            await clear_gallery(target, state, session, customer, lang)
        elif callback_data.action == "done" and current == EditPage.sending_photo.state:
            await _finish_edit(target, state, session, customer, lang)

    router = Router(name="share_page_photo")
    router.callback_query.register(on_photo_button, PhotoCB.filter())
    for photo_state in (YesNoPage.sending_photo, InvitePage.sending_photo):
        router.message.register(creation_photo, photo_state, F.photo)
        router.message.register(
            creation_not_a_photo, photo_state, ~F.photo, flags={"catch_all": True}
        )
    router.message.register(edit_photo, EditPage.sending_photo, F.photo)
    router.message.register(
        creation_not_a_photo, EditPage.sending_photo, ~F.photo, flags={"catch_all": True}
    )
    return router
