"""Editing and deleting an announcement AFTER publication (CP23 addendum).

"Mening e'lonlarim": the shop's published posts, for its explicit owners and
staff (the CP22 publishing rule -- CP19's empty-list order rule never lets
anyone publish). Every operation re-checks shop and permission and works on
a post of THIS shop only.

THE CATALOGUE FOLLOWS THROUGH THE SAME PATH AS A CHANNEL EDIT. Telegram does
not reliably deliver the bot an `edited_channel_post` for its own edits (CP22
saw no own `channel_post` either), so after editing the post the bot calls
the indexer's `apply_edit` itself -- the very function the channel router
calls for an edited post -- with the message Telegram returned. If Telegram
also delivers the update later, `apply_edit` is idempotent. A deleted post
goes through `deactivate_post`, the same rule as a post stripped of its tags.
"""

from __future__ import annotations

import re
from dataclasses import replace
from html import unescape
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, InputMediaPhoto, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.announcements.extraction import Fields
from gulbot.announcements.flower_templates import ALL_TEMPLATES
from gulbot.announcements.flower_templates import caption as flower_caption
from gulbot.announcements.numbers import parse_number
from gulbot.announcements.templates import caption as legacy_caption
from gulbot.catalog.prices import MAX_PRICE_UZS, MIN_PRICE_UZS
from gulbot.models.announcement import AnnouncementDraft
from gulbot.models.shop import Shop, ShopStatus
from gulbot.services.announcements import AnnouncementRefused, may_publish
from gulbot.services.indexer import ChannelPost, FinalizeResult, apply_edit, deactivate_post

EDITABLE_FIELDS = ("price", "count", "description")
_TAG = re.compile(r"</?[a-z]+>")


def visible(caption_html: str) -> str:
    """What Telegram shows of an HTML caption -- what the indexer reads."""
    return unescape(_TAG.sub("", caption_html))


async def my_posts(
    session: AsyncSession, *, shop_id: int, actor: int, limit: int = 10
) -> list[AnnouncementDraft]:
    if not await may_publish(session, shop_id=shop_id, actor=actor):
        raise AnnouncementRefused("E'lonlarga ruxsat yo'q")
    rows = await session.scalars(
        select(AnnouncementDraft)
        .where(AnnouncementDraft.shop_id == shop_id, AnnouncementDraft.status == "published")
        .order_by(AnnouncementDraft.published_at.desc(), AnnouncementDraft.id.desc())
        .limit(limit)
    )
    return list(rows.all())


async def post_for(
    session: AsyncSession, *, shop_id: int, actor: int, draft_id: int
) -> AnnouncementDraft:
    """A PUBLISHED post of THIS shop, locked, for an owner or staff member."""
    if not await may_publish(session, shop_id=shop_id, actor=actor):
        raise AnnouncementRefused("E'lonlarga ruxsat yo'q")
    draft = await session.scalar(
        select(AnnouncementDraft)
        .where(
            AnnouncementDraft.id == draft_id,
            AnnouncementDraft.shop_id == shop_id,
            AnnouncementDraft.status == "published",
        )
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if draft is None or not draft.receipts:
        raise AnnouncementRefused("Bu e'lon topilmadi")
    return draft


async def _channel_and_name(session: AsyncSession, shop_id: int) -> tuple[int, str]:
    shop = await session.scalar(
        select(Shop).where(Shop.id == shop_id, Shop.status == ShopStatus.ACTIVE)
    )
    if shop is None or shop.channel_id is None:
        raise AnnouncementRefused("Kanal ulanmagan")
    return shop.channel_id, shop.name


def render_caption(draft: AnnouncementDraft, fields: Fields, shop_name: str) -> str:
    if draft.template is not None:
        return flower_caption(
            fields, template=draft.template, shop_name=shop_name, lang=draft.caption_lang
        )
    return legacy_caption(fields, style=draft.caption_style, shop_name=shop_name)


def changed_fields(draft: AnnouncementDraft, field: str, value: str) -> Fields:
    """The post's fields with one changed, validated as at publication."""
    fields = Fields.from_data(draft.fields)
    if field == "price":
        price = parse_number(value)
        if not MIN_PRICE_UZS <= price <= MAX_PRICE_UZS:
            raise AnnouncementRefused("Narxi 10 000–50 000 000 so'm bo'lishi kerak")
        fields = replace(fields, price=price)
    elif field == "count":
        count = parse_number(value)
        if not 1 <= count <= 9999:
            raise AnnouncementRefused("Soni 1–9999 bo'lishi kerak")
        fields = replace(fields, count=count)
    elif field == "description":
        if not 1 <= len(value) <= 4096:
            raise AnnouncementRefused("Tavsif 1–4096 belgi bo'lishi kerak")
        fields = replace(fields, description=value)
    else:
        raise AnnouncementRefused("Bunday maydon yo'q")
    fields.validate()
    return fields


async def _reindex(
    session: AsyncSession, draft: AnnouncementDraft, message: Message | bool, caption: str
) -> FinalizeResult:
    """The SAME path as an edited channel post, with what Telegram returned."""
    first = dict(draft.receipts[0])
    if isinstance(message, Message) and message.photo:
        first["file_id"] = message.photo[-1].file_id
    first["caption"] = (
        message.caption if isinstance(message, Message) and message.caption else (visible(caption))
    )
    draft.receipts = [first, *draft.receipts[1:]]
    post = ChannelPost(**first)
    if post.shop_id != draft.shop_id:
        raise AnnouncementRefused("Boshqa do'kon posti")
    return await apply_edit(session, post)


def _not_modified(error: TelegramBadRequest) -> bool:
    return "not modified" in str(error).lower()


async def edit_field(
    session: AsyncSession,
    bot: Bot,
    *,
    shop_id: int,
    actor: int,
    draft_id: int,
    field: str,
    value: str,
) -> FinalizeResult:
    """Change one field of a published post: the channel caption, then the
    catalogue through the edited-post path."""
    draft = await post_for(session, shop_id=shop_id, actor=actor, draft_id=draft_id)
    channel, shop_name = await _channel_and_name(session, shop_id)
    fields = changed_fields(draft, field, value)
    body = render_caption(draft, fields, shop_name)
    first = draft.receipts[0]
    try:
        message: Message | bool = await bot.edit_message_caption(
            chat_id=channel, message_id=first["message_id"], caption=body, parse_mode="HTML"
        )
    except TelegramBadRequest as error:
        if not _not_modified(error):
            raise AnnouncementRefused("Telegram postni o'zgartirmadi") from None
        message = True  # already this caption: the catalogue still re-syncs
    draft.fields, draft.preview_caption = fields.data(), body
    draft.revision += 1
    return await _reindex(session, draft, message, body)


async def switch_template(
    session: AsyncSession,
    bot: Bot,
    *,
    shop_id: int,
    actor: int,
    draft_id: int,
    template: str,
    image: bytes,
) -> FinalizeResult:
    """Put the post in another flower template: new overlay AND caption, in
    one editMessageMedia. `image` is the new first photo, already rendered."""
    if template not in ALL_TEMPLATES:
        raise AnnouncementRefused("Bunday shablon yo'q")
    draft = await post_for(session, shop_id=shop_id, actor=actor, draft_id=draft_id)
    channel, shop_name = await _channel_and_name(session, shop_id)
    draft.template, draft.template_picked = template, True
    fields = Fields.from_data(draft.fields)
    body = render_caption(draft, fields, shop_name)
    first = draft.receipts[0]
    try:
        message: Message | bool = await bot.edit_message_media(
            chat_id=channel,
            message_id=first["message_id"],
            media=InputMediaPhoto(
                media=BufferedInputFile(image, filename="bouquet.jpg"),
                caption=body,
                parse_mode="HTML",
            ),
        )
    except TelegramBadRequest:
        raise AnnouncementRefused("Telegram postni o'zgartirmadi") from None
    draft.preview_caption = body
    draft.revision += 1
    return await _reindex(session, draft, message, body)


async def delete_post(
    session: AsyncSession, bot: Bot, *, shop_id: int, actor: int, draft_id: int
) -> FinalizeResult:
    """Delete the post from the channel; its product is deactivated."""
    draft = await post_for(session, shop_id=shop_id, actor=actor, draft_id=draft_id)
    channel, _ = await _channel_and_name(session, shop_id)
    for receipt in draft.receipts:
        try:
            await bot.delete_message(chat_id=channel, message_id=receipt["message_id"])
        except TelegramBadRequest as error:
            # Already gone (deleted by hand in Telegram) is the outcome we want.
            if "not found" not in str(error).lower():
                raise AnnouncementRefused("Telegram postni o'chirmadi") from None
    draft.status = "deleted"
    draft.revision += 1
    first: dict[str, Any] = dict(draft.receipts[0])
    return await deactivate_post(session, ChannelPost(**first))
