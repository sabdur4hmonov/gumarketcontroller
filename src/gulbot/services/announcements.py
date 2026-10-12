"""Author-scoped drafts, durable publication claims, SAME CP8 ingest/finalize."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from aiogram import Bot
from aiogram.types import InputMediaPhoto, Message
from sqlalchemy import any_, exists, literal, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.announcements.extraction import Fields, extract
from gulbot.announcements.flower_templates import ALL_TEMPLATES
from gulbot.announcements.flower_templates import caption as flower_caption
from gulbot.announcements.images import IMAGE_STYLES
from gulbot.announcements.learning import Learned, diff_corrections, from_button
from gulbot.announcements.templates import CAPTION_STYLES
from gulbot.announcements.templates import caption as legacy_caption
from gulbot.announcements.themes import LANGS, theme_for
from gulbot.bot.channel import as_channel_post
from gulbot.models.announcement import (
    AnnouncementDraft,
    AnnouncementPreference,
    AnnouncementThemeFavourite,
)
from gulbot.models.product import HashtagAlias
from gulbot.models.shop import Shop, ShopStatus
from gulbot.models.staff import ShopStaff
from gulbot.services import announcement_learning
from gulbot.services.indexer import ChannelPost, finalize_product, ingest_post


class AnnouncementRefused(ValueError):
    pass


async def may_publish(session: AsyncSession, *, shop_id: int, actor: int) -> bool:
    if actor <= 0:
        return False
    listed = exists(
        select(ShopStaff.telegram_id).where(
            ShopStaff.shop_id == shop_id, ShopStaff.telegram_id == actor
        )
    )
    return bool(
        await session.scalar(
            select(Shop.id).where(
                Shop.id == shop_id,
                Shop.status == ShopStatus.ACTIVE,
                or_(literal(actor) == any_(Shop.owner_telegram_ids), listed),
            )
        )
    )


async def require_author(session: AsyncSession, *, shop_id: int, actor: int) -> None:
    if not await may_publish(session, shop_id=shop_id, actor=actor):
        raise AnnouncementRefused("E'lon joylashga ruxsat yo'q")


async def draft_for(
    session: AsyncSession, *, shop_id: int, actor: int, draft_id: int, revision: int | None = None
) -> AnnouncementDraft:
    await require_author(session, shop_id=shop_id, actor=actor)
    draft = await session.scalar(
        select(AnnouncementDraft)
        .where(
            AnnouncementDraft.shop_id == shop_id,
            AnnouncementDraft.author_id == actor,
            AnnouncementDraft.id == draft_id,
        )
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if draft is None or (revision is not None and draft.revision != revision):
        raise AnnouncementRefused("Bu tugma eskirgan. Oxirgi xabardagi tugmani bosing")
    return draft


async def new_draft(session: AsyncSession, *, shop_id: int, actor: int) -> AnnouncementDraft:
    await require_author(session, shop_id=shop_id, actor=actor)
    shop = await session.scalar(select(Shop).where(Shop.id == shop_id))
    if shop is None or shop.channel_id is None:
        raise AnnouncementRefused("Avval do'kon kanalini ulang")
    pref = await session.scalar(
        select(AnnouncementPreference).where(AnnouncementPreference.shop_id == shop_id)
    )
    draft = AnnouncementDraft(
        shop_id=shop_id,
        author_id=actor,
        photos=[],
        fields={},
        preview_media=[],
        receipts=[],
        # CP23: a Russian-speaking shop's templates start in Russian.
        caption_lang="ru" if shop.lang == "ru" else "uz",
    )
    if pref:
        draft.caption_style, draft.image_style = pref.caption_style, pref.image_style
    session.add(draft)
    await session.flush()
    return draft


def editable(draft: AnnouncementDraft) -> None:
    if draft.status in {"transcribing", "publishing", "published", "ambiguous"}:
        raise AnnouncementRefused("Bu e'lonni hozir o'zgartirib bo'lmaydi")


def invalidate(draft: AnnouncementDraft, *, status: str = "review") -> None:
    editable(draft)
    draft.status = status
    draft.revision += 1
    draft.preview_media, draft.preview_caption = [], None


async def parse_description(session: AsyncSession, draft: AnnouncementDraft, text: str) -> None:
    editable(draft)
    rows = (
        await session.execute(
            select(HashtagAlias.alias_normalized, HashtagAlias.canonical_hashtag).where(
                HashtagAlias.shop_id == draft.shop_id
            )
        )
    ).all()
    # CP23 addendum: this shop's learned corrections, before the lexicon.
    learned = await announcement_learning.learned_for(session, draft.shop_id)
    fields = extract(
        text, aliases={r.alias_normalized: r.canonical_hashtag for r in rows}, learned=learned
    )
    await announcement_learning.mark_used(session, shop_id=draft.shop_id, applied=fields.learned)
    draft.fields = fields.data()
    invalidate(draft)


async def retext(
    session: AsyncSession, draft: AnnouncementDraft, *, actor: int, text: str
) -> list[Learned]:
    """ "✏️ Matnni tuzatish": learn the short mishearings the owner fixed, then
    run the SAME extraction on the corrected text. Returns what was learned."""
    editable(draft)
    heard = Fields.from_data(draft.fields).raw
    learned = diff_corrections(heard, text) if heard else []
    await announcement_learning.remember(
        session, shop_id=draft.shop_id, taught_by=actor, items=learned
    )
    await parse_description(session, draft, text)
    return learned


async def learn_from_button(
    session: AsyncSession, draft: AnnouncementDraft, *, actor: int, kind: str, added: str
) -> Learned | None:
    """A flower/colour fixed by button teaches only when it replaced a GUESS."""
    fields = Fields.from_data(draft.fields)
    current = fields.flowers if kind == "flower" else [fields.colour]
    removed = [
        entry[2]
        for entry in fields.heard
        if len(entry) == 4 and entry[0] == kind and entry[3] == "low" and entry[2] not in current
    ]
    if len(removed) != 1:
        return None
    learned = from_button(fields.heard, kind, removed[0], added)
    if learned is not None:
        await announcement_learning.remember(
            session, shop_id=draft.shop_id, taught_by=actor, items=[learned]
        )
    return learned


async def cancel(session: AsyncSession, draft: AnnouncementDraft) -> None:
    """ "❌ Bekor qilish": the draft goes, nothing of it is kept. Never after
    the post went out (or may have): that is "Mening e'lonlarim"'s delete."""
    if draft.status in {"publishing", "published", "ambiguous", "deleted"}:
        raise AnnouncementRefused("Joylangan e'lonni bu yerda bekor qilib bo'lmaydi")
    await session.delete(draft)
    await session.flush()


def confirm(draft: AnnouncementDraft) -> None:
    if draft.status != "review":
        raise AnnouncementRefused("Avval ma'lumotlarni tekshiring")
    Fields.from_data(draft.fields).validate()
    invalidate(draft, status="confirmed")


def choose_style(draft: AnnouncementDraft, *, kind: str, value: str) -> None:
    if draft.status not in {"confirmed", "preview"}:
        raise AnnouncementRefused("Avval ma'lumotlarni tasdiqlang")
    if kind == "caption" and value in CAPTION_STYLES:
        draft.caption_style = value
    elif kind == "image" and value in {"none", *IMAGE_STYLES}:
        draft.image_style = value
    else:
        raise AnnouncementRefused("Bunday uslub yo'q")
    # A CP22 style is a choice of the CP22 family: the draft leaves the
    # flower templates until the owner picks one again.
    draft.template, draft.template_picked = None, True
    invalidate(draft, status="confirmed")


# --- CP23: flower templates ------------------------------------------------------


def draft_theme(draft: AnnouncementDraft) -> str:
    """The flower theme the draft's confirmed fields point to."""
    fields = Fields.from_data(draft.fields)
    return theme_for(fields.flowers, fields.raw)


async def apply_default_template(session: AsyncSession, draft: AnnouncementDraft) -> None:
    """After confirmation: the template the owner would expect, unless they chose.

    The shop's favourite layout FOR THIS FLOWER first; then a CP22 favourite
    saved before CP23 (its styles were copied onto the draft at creation, so
    the CP22 family is kept); else the flower's classic layout.
    """
    if draft.template_picked:
        return
    draft.template = await default_template(session, draft)


async def default_template(session: AsyncSession, draft: AnnouncementDraft) -> str | None:
    """The template a confirmation would give this draft now; changes nothing.
    None means the CP22 family (the shop saved a CP22 style)."""
    theme = draft_theme(draft)
    layout = await session.scalar(
        select(AnnouncementThemeFavourite.layout).where(
            AnnouncementThemeFavourite.shop_id == draft.shop_id,
            AnnouncementThemeFavourite.theme == theme,
        )
    )
    if layout is not None:
        return f"{theme}.{layout}"
    legacy = await session.scalar(
        select(AnnouncementPreference.shop_id).where(
            AnnouncementPreference.shop_id == draft.shop_id
        )
    )
    return None if legacy is not None else f"{theme}.classic"


async def would_post(session: AsyncSession, draft: AnnouncementDraft, shop_name: str) -> str | None:
    """CP23 addendum: the caption this draft would go out with, as it stands --
    the review screen shows it after every fix. None while a field is missing."""
    fields = Fields.from_data(draft.fields)
    try:
        fields.validate()
    except ValueError:
        return None
    template = draft.template if draft.template_picked else await default_template(session, draft)
    if template is not None:
        return flower_caption(
            fields, template=template, shop_name=shop_name, lang=draft.caption_lang
        )
    return legacy_caption(fields, style=draft.caption_style, shop_name=shop_name)


def require_published(draft: AnnouncementDraft) -> None:
    """Stories are made from what was actually posted, never from a draft."""
    if draft.status != "published" or not draft.receipts:
        raise AnnouncementRefused("Avval e'lonni kanalga joylang")


def story_theme(draft: AnnouncementDraft) -> str:
    """The story's flower theme: the post's template's, else the flowers'."""
    if draft.template is not None:
        return draft.template.partition(".")[0]
    return draft_theme(draft)


def choose_template(draft: AnnouncementDraft, template: str) -> None:
    if draft.status not in {"confirmed", "preview"}:
        raise AnnouncementRefused("Avval ma'lumotlarni tasdiqlang")
    if template not in ALL_TEMPLATES:
        raise AnnouncementRefused("Bunday shablon yo'q")
    draft.template, draft.template_picked = template, True
    invalidate(draft, status="confirmed")


def next_caption_lang(draft: AnnouncementDraft) -> None:
    """Lotin -> Кирилл -> Русский -> Lotin. Flower templates only."""
    if draft.status not in {"confirmed", "preview"}:
        raise AnnouncementRefused("Avval ma'lumotlarni tasdiqlang")
    order = list(LANGS)
    draft.caption_lang = order[(order.index(draft.caption_lang) + 1) % len(order)]
    invalidate(draft, status="confirmed")


async def save_favourite(
    session: AsyncSession, *, shop_id: int, actor: int, draft: AnnouncementDraft
) -> None:
    await require_author(session, shop_id=shop_id, actor=actor)
    if draft.shop_id != shop_id or draft.author_id != actor:
        raise AnnouncementRefused("Boshqa do'kon e'loni")
    if draft.template is not None:
        # CP23: remembered per flower -- roses may be premium, tulips festive.
        theme, _, layout = draft.template.partition(".")
        favourite = insert(AnnouncementThemeFavourite).values(
            shop_id=shop_id, theme=theme, layout=layout
        )
        await session.execute(
            favourite.on_conflict_do_update(
                index_elements=[
                    AnnouncementThemeFavourite.shop_id,
                    AnnouncementThemeFavourite.theme,
                ],
                set_={"layout": layout, "updated_at": datetime.now(UTC)},
            )
        )
        return
    statement = insert(AnnouncementPreference).values(
        shop_id=shop_id, caption_style=draft.caption_style, image_style=draft.image_style
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[AnnouncementPreference.shop_id],
            set_={
                "caption_style": draft.caption_style,
                "image_style": draft.image_style,
                "updated_at": datetime.now(UTC),
            },
        )
    )


def receipt(message: Message, shop_id: int) -> dict[str, Any]:
    post = as_channel_post(message, shop_id)
    return {
        "shop_id": post.shop_id,
        "chat_id": post.chat_id,
        "message_id": post.message_id,
        "file_id": post.file_id,
        "media_group_id": post.media_group_id,
        "caption": post.caption,
    }


async def index_receipts(session: AsyncSession, draft: AnnouncementDraft) -> None:
    for data in draft.receipts:
        post = ChannelPost(**data)
        if post.shop_id != draft.shop_id:
            raise AnnouncementRefused("Boshqa do'kon posti")
        await ingest_post(session, post)
    if draft.receipts:
        first = draft.receipts[0]
        await finalize_product(
            session,
            shop_id=draft.shop_id,
            **(
                {"media_group_id": first["media_group_id"]}
                if first["media_group_id"]
                else {"channel_message_id": first["message_id"]}
            ),
        )


async def publish(
    session: AsyncSession, *, bot: Bot, shop_id: int, actor: int, draft_id: int, revision: int
) -> str:
    draft = await draft_for(
        session, shop_id=shop_id, actor=actor, draft_id=draft_id, revision=revision
    )
    if draft.status == "published":
        await index_receipts(session, draft)
        return post_link(draft.receipts[0])
    if draft.status != "preview" or not draft.preview_media or not draft.preview_caption:
        raise AnnouncementRefused("Avval aniq ko'rinishni tekshiring va tasdiqlang")
    Fields.from_data(draft.fields).validate()
    channel = await session.scalar(
        select(Shop.channel_id).where(Shop.id == shop_id, Shop.status == ShopStatus.ACTIVE)
    )
    if channel is None:
        raise AnnouncementRefused("Kanal ulanmagan")
    media, body = list(draft.preview_media), draft.preview_caption
    draft.status = "publishing"
    # The claim survives a crash or an ambiguous network timeout. A second tap
    # cannot blindly resend. Sending and Postgres cannot be one transaction.
    await session.commit()
    try:
        if len(media) == 1:
            messages = [await bot.send_photo(channel, media[0], caption=body, parse_mode="HTML")]
        else:
            messages = await bot.send_media_group(
                channel,
                media=[
                    InputMediaPhoto(media=f, caption=body if i == 0 else None, parse_mode="HTML")
                    for i, f in enumerate(media)
                ],
            )
    except Exception:
        draft.status = "ambiguous"
        await session.commit()
        raise AnnouncementRefused(
            "Yuborish natijasi noma'lum. Qayta yuborishdan oldin kanalni tekshiring"
        ) from None
    draft.receipts = [receipt(message, shop_id) for message in messages]
    draft.status, draft.published_at = "published", datetime.now(UTC)
    await session.commit()  # Save returned Telegram messages BEFORE indexing.
    await index_receipts(session, draft)
    return post_link(draft.receipts[0])


def post_link(data: dict[str, Any]) -> str:
    return f"https://t.me/c/{str(data['chat_id']).removeprefix('-100')}/{data['message_id']}"
