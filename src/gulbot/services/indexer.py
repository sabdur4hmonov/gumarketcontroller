"""Indexing channel posts into the catalogue CP7 built.

This is the first genuinely event-driven part of the bot, and the difficulty is
not the parsing -- CP7 already did that, and this module reuses those pure
functions unchanged. The difficulty is that AN ALBUM IS NOT ONE UPDATE.

Five photos posted together arrive as five separate `channel_post` updates
sharing a `media_group_id`, milliseconds apart, possibly on different workers.
Only ONE of them carries the caption, and it is the first POSTED, not
necessarily the first PROCESSED. There is no moment at which a handler holds
all five, so "collect them, then decide" is not an available strategy.

WHAT THIS MODULE DOES INSTEAD

1. Every album arrival UPSERTS onto `(shop_id, media_group_id)` -- CP7's
   partial unique index. Five arrivals conflict onto one row instead of racing
   to create five. The merge fills `caption_raw` only if it is still empty, and
   keeps the EARLIEST `channel_message_id` as the anchor photo, with
   `telegram_file_id` following the anchor.

2. The row is PROVISIONAL until `finalized_at` is set. A row created by the
   second photo genuinely does not know its own name, price or tags yet.

3. A debounced `finalize_product` settles it: re-read, parse, sync hashtags,
   stamp `finalized_at`. It is IDEMPOTENT, and that -- not the debounce -- is
   what makes this safe. Debounce collapsing is an optimisation; finalize's own
   idempotency is the correctness argument.

THE GATE, AND WHY IT MOVES FOR ALBUMS

The rule is "index a post only if it has BOTH a photo and a usable hashtag".
For a SINGLE post that is decidable on arrival, so it is decided there and no
row is ever created for a post that fails it.

For an ALBUM it is not decidable on arrival: a captionless member cannot know
whether the album has a caption, because the caption may not have arrived yet.
So the gate moves to finalize, and a group that turns out to have no usable
hashtag is DELETED. That has a useful consequence -- a caption arriving after
its own album was dropped simply re-creates the row and finalizes correctly.

ONLY THE SHOP'S OWN CHANNEL

A post is indexed only when its chat IS `shops.channel_id` (H3 of
AUDIT_MULTI_TENANT.md). The bot can be added to any channel, and products are
keyed on `(shop_id, channel_message_id)` -- message ids are per channel -- so
without the check a second channel's posts became this shop's products, and an
edit there could re-price a real one. A shop with no channel recorded indexes
nothing: not connected yet is not "any channel".

WHAT THIS MODULE DOES NOT DO

* No alias resolution. Tags are stored exactly as `normalize_hashtag` returns
  them; CP9 resolves the QUERY through `hashtag_aliases` instead. Resolving at
  index time would bake one version of the alias table into stored rows and
  make editing that table a re-index.
* No deletion sweep, no monitoring -- Phase 2, per docs/CHECKPOINTS.md.
* No searching, no `copyMessage`, no customer-facing text -- that is CP9.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import Boolean, case, delete, func, literal_column, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.catalog.hashtags import extract_hashtags
from gulbot.catalog.naming import product_name
from gulbot.catalog.prices import PriceConfidence, parse_price
from gulbot.models.product import Product, ProductHashtag, ProductSource
from gulbot.models.shop import Shop

log = logging.getLogger("gulbot.indexer")

#: IngestResult.reason for a post from a chat that is not the shop's channel.
NOT_THE_SHOPS_CHANNEL = "not_the_shops_channel"

#: Rendered into the partial unique index inference. It has to match
#: `uq_products_shop_media_group` exactly or Postgres refuses to use the index.
MEDIA_GROUP_INDEX_WHERE = "media_group_id IS NOT NULL"


@dataclass(frozen=True)
class ChannelPost:
    """One `channel_post` update, reduced to what indexing needs.

    A plain value, deliberately: the aiogram `Message` stays at the edge in
    `gulbot.bot.channel`, so everything below here is testable without
    synthesising Telegram objects.
    """

    shop_id: int
    chat_id: int
    message_id: int
    file_id: str | None
    media_group_id: str | None = None
    caption: str | None = None

    @property
    def has_photo(self) -> bool:
        return bool(self.file_id)

    @property
    def is_album_member(self) -> bool:
        return self.media_group_id is not None


class Ingest(StrEnum):
    IGNORED = "ignored"
    INSERTED = "inserted"
    MERGED = "merged"


class Finalize(StrEnum):
    MISSING = "missing"
    NOOP = "noop"
    FINALIZED = "finalized"
    DROPPED = "dropped"
    DEACTIVATED = "deactivated"
    #: Ingested, but deliberately left for the debounce to settle. Only an edit
    #: on an album that was not indexed yet lands here.
    DEFERRED = "deferred"


@dataclass(frozen=True)
class IngestResult:
    outcome: Ingest
    product_id: int | None = None
    #: Album arrivals need the debounce; a single settles immediately.
    needs_debounce: bool = False
    #: Why an IGNORED post was ignored, when it is not the obvious gate.
    reason: str | None = None


@dataclass(frozen=True)
class FinalizeResult:
    outcome: Finalize
    product_id: int | None = None
    hashtags: tuple[str, ...] = ()
    price_uzs: int | None = None
    price_confidence: str = PriceConfidence.NONE.value


def _provisional_name(caption: str | None) -> str:
    """Best effort at insert time. "" is legitimate and expected for an album
    member that arrived before the caption did; finalize replaces it."""
    return product_name(caption)


async def from_the_shops_channel(session: AsyncSession, post: ChannelPost) -> bool:
    """Is this post from the channel the shop registered as its catalogue?

    Logged when not, with the chat id, so an operator can tell a stray channel
    from a shop whose `channel_id` was never set -- and copy the id if it is the
    latter. See the module docstring.
    """
    channel_id = await session.scalar(select(Shop.channel_id).where(Shop.id == post.shop_id))
    if channel_id is None:
        log.warning(
            "shop %s has no channel_id, so it indexes nothing: ignored message=%s from "
            "chat %s. If that chat is its catalogue, set shops.channel_id = %s",
            post.shop_id,
            post.message_id,
            post.chat_id,
            post.chat_id,
        )
        return False
    if channel_id != post.chat_id:
        log.warning(
            "ignored message=%s from chat %s: shop %s's catalogue is channel %s",
            post.message_id,
            post.chat_id,
            post.shop_id,
            channel_id,
        )
        return False
    return True


async def ingest_post(session: AsyncSession, post: ChannelPost) -> IngestResult:
    """Record one channel post. Returns what happened and whether to debounce."""
    if not post.has_photo:
        return IngestResult(Ingest.IGNORED)
    if not await from_the_shops_channel(session, post):
        return IngestResult(Ingest.IGNORED, reason=NOT_THE_SHOPS_CHANNEL)

    if post.is_album_member:
        return await _ingest_album_member(session, post)
    return await _ingest_single(session, post)


async def _ingest_single(session: AsyncSession, post: ChannelPost) -> IngestResult:
    # Decidable right here: no caption hashtag, no product. Nothing is written,
    # not even a tracked skip -- an announcement is not a half-product.
    if not extract_hashtags(post.caption or ""):
        return IngestResult(Ingest.IGNORED)

    stmt = insert(Product).values(
        shop_id=post.shop_id,
        name=_provisional_name(post.caption),
        telegram_file_id=post.file_id,
        source=ProductSource.CHANNEL.value,
        channel_message_id=post.message_id,
        channel_chat_id=post.chat_id,
        media_group_id=None,
        caption_raw=post.caption,
    )
    # Redelivery of the same message: Telegram may send a channel_post twice.
    # The second one is identical, so refreshing these columns is a no-op in
    # practice and keeps the row honest if the caption really did change.
    upsert = stmt.on_conflict_do_update(
        index_elements=["shop_id", "channel_message_id"],
        set_={
            "caption_raw": stmt.excluded.caption_raw,
            "telegram_file_id": stmt.excluded.telegram_file_id,
            "channel_chat_id": stmt.excluded.channel_chat_id,
        },
    ).returning(Product.id)

    product_id = (await session.execute(upsert)).scalar_one()
    return IngestResult(Ingest.INSERTED, product_id=product_id, needs_debounce=False)


async def _ingest_album_member(session: AsyncSession, post: ChannelPost) -> IngestResult:
    """Upsert onto the album anchor. No hashtag gate: it is not decidable yet."""
    stmt = insert(Product).values(
        shop_id=post.shop_id,
        name=_provisional_name(post.caption),
        telegram_file_id=post.file_id,
        source=ProductSource.CHANNEL.value,
        channel_message_id=post.message_id,
        channel_chat_id=post.chat_id,
        media_group_id=post.media_group_id,
        caption_raw=post.caption,
    )
    excluded = stmt.excluded
    #: Every expression below reads the PRE-UPDATE row, which is what makes
    #: "fill only if empty" and "keep the earliest" expressible in one
    #: statement rather than a read-then-write race.
    arrival_is_earlier = excluded.channel_message_id < Product.channel_message_id
    upsert = stmt.on_conflict_do_update(
        index_elements=["shop_id", "media_group_id"],
        index_where=Product.__table__.c.media_group_id.isnot(None),
        set_={
            # The caption belongs to whichever member carried one. A later
            # captionless photo must not blank it.
            "caption_raw": func.coalesce(Product.caption_raw, excluded.caption_raw),
            "name": func.coalesce(func.nullif(Product.name, ""), excluded.name),
            # The anchor is the earliest message in the album, whatever order
            # the updates actually arrived in.
            "channel_message_id": func.least(
                Product.channel_message_id, excluded.channel_message_id
            ),
            "telegram_file_id": case(
                (arrival_is_earlier, excluded.telegram_file_id),
                else_=Product.telegram_file_id,
            ),
            "channel_chat_id": func.coalesce(Product.channel_chat_id, excluded.channel_chat_id),
            # New album information invalidates any parse already done. This is
            # what lets a member arriving AFTER finalize still be picked up:
            # the row re-opens and the debounce settles it again.
            "finalized_at": None,
            # ON CONFLICT DO UPDATE is a Core construct, so the mapper's
            # onupdate never fires; without this the row would keep claiming it
            # had not changed since it was created.
            "updated_at": func.now(),
        },
    ).returning(Product.id, literal_column("xmax = 0", Boolean).label("was_inserted"))

    # `xmax = 0` is the standard way to tell an upsert's two branches apart:
    # a freshly inserted tuple has no deleting transaction, an updated one does.
    # Timestamps cannot answer this -- now() is fixed for a whole transaction,
    # so inside one test transaction every row looks equally new.
    row = (await session.execute(upsert)).one()
    return IngestResult(
        Ingest.INSERTED if row.was_inserted else Ingest.MERGED,
        product_id=row.id,
        needs_debounce=True,
    )


async def finalize_product(
    session: AsyncSession,
    *,
    shop_id: int,
    media_group_id: str | None = None,
    channel_message_id: int | None = None,
    force: bool = False,
    now_utc: datetime | None = None,
) -> FinalizeResult:
    """Settle one product: parse the caption, sync its tags, stamp it.

    Idempotent. Calling it twice in a row is a verified no-op the second time:
    the row is already stamped, so it returns NOOP without touching a column or
    writing a hashtag. `force=True` is for edits, where the caption really did
    change and the parse has to be redone.
    """
    if (media_group_id is None) == (channel_message_id is None):
        raise ValueError(
            "finalize_product needs exactly one of media_group_id / channel_message_id"
        )

    now = now_utc or datetime.now(UTC)

    query = select(Product).where(Product.shop_id == shop_id)
    if media_group_id is not None:
        query = query.where(Product.media_group_id == media_group_id)
    else:
        query = query.where(Product.channel_message_id == channel_message_id)
    # Two workers may reach the same group; the loser waits and then sees a
    # finalized row, which is exactly the NOOP branch below.
    product = await session.scalar(query.with_for_update())

    if product is None:
        return FinalizeResult(Finalize.MISSING)
    if product.finalized_at is not None and not force:
        return FinalizeResult(
            Finalize.NOOP,
            product_id=product.id,
            price_uzs=product.price_uzs,
            price_confidence=product.price_confidence,
        )

    tags = tuple(extract_hashtags(product.caption_raw or ""))
    if not tags:
        return await _drop_untagged(session, product)

    price, confidence = parse_price(product.caption_raw or "")
    await _sync_hashtags(session, product, tags)

    product.name = product_name(product.caption_raw) or tags[0]
    product.price_uzs = price
    product.price_confidence = confidence.value
    product.finalized_at = now
    await session.flush()

    return FinalizeResult(
        Finalize.FINALIZED,
        product_id=product.id,
        hashtags=tags,
        price_uzs=price,
        price_confidence=confidence.value,
    )


async def _drop_untagged(session: AsyncSession, product: Product) -> FinalizeResult:
    """A group with no usable hashtag is not a product.

    Never finalized: DELETE it. It failed the gate, and leaving it would put a
    row into the catalogue that no search can reach. Deleting is also what makes
    a very late caption self-healing -- it re-inserts the row from scratch.

    Already finalized: DEACTIVATE it instead. An edit that strips every hashtag
    off a live product is the shop hiding it, not a post that never qualified,
    and deleting a row something may already reference is a bigger action than
    is warranted here.
    """
    product_id = product.id
    if product.finalized_at is None:
        await session.delete(product)
        await session.flush()
        return FinalizeResult(Finalize.DROPPED, product_id=product_id)

    product.active = False
    await session.flush()
    return FinalizeResult(Finalize.DEACTIVATED, product_id=product_id)


async def _sync_hashtags(session: AsyncSession, product: Product, tags: tuple[str, ...]) -> None:
    """Make the stored tags equal `tags`. Safe to repeat, safe after an edit."""
    await session.execute(
        insert(ProductHashtag)
        .values(
            [
                {
                    "shop_id": product.shop_id,
                    "product_id": product.id,
                    "hashtag_normalized": tag,
                }
                for tag in tags
            ]
        )
        # Re-running finalize must not double the rows.
        .on_conflict_do_nothing(index_elements=["product_id", "hashtag_normalized"])
    )
    # An edit can REMOVE a tag, so the sync has to be two-sided.
    await session.execute(
        delete(ProductHashtag).where(
            ProductHashtag.product_id == product.id,
            ProductHashtag.hashtag_normalized.notin_(tags),
        )
    )
    await session.flush()


async def apply_edit(
    session: AsyncSession, post: ChannelPost, *, now_utc: datetime | None = None
) -> FinalizeResult:
    """Re-parse an edited post against the row it already has.

    Finds the existing row by the SAME unique keys the insert used, so an edit
    can never create a second product. An album edit is looked up by
    `media_group_id`, because Telegram sends the edit for the specific message
    that changed and that need not be the anchor.

    An edit on a post that was never indexed -- typically a photo whose caption
    only NOW got its first hashtag -- is ingested as if it had just been posted.
    That is the same gate, applied at the moment it first passes.
    """
    if not post.has_photo:
        return FinalizeResult(Finalize.MISSING)
    # BEFORE the lookup: message ids are per channel, so another channel's
    # message 101 would find this shop's product 101 and rewrite it.
    if not await from_the_shops_channel(session, post):
        return FinalizeResult(Finalize.MISSING)

    query = select(Product).where(Product.shop_id == post.shop_id)
    if post.media_group_id is not None:
        query = query.where(Product.media_group_id == post.media_group_id)
    else:
        query = query.where(Product.channel_message_id == post.message_id)
    product = await session.scalar(query.with_for_update())

    if product is None:
        result = await ingest_post(session, post)
        if result.outcome is Ingest.IGNORED:
            return FinalizeResult(Finalize.MISSING)
        if post.is_album_member:
            # Do NOT finalize here. The other members of this album may still
            # be in flight, and finalizing now would drop the group for having
            # no caption yet. The debounce is the right instrument.
            return FinalizeResult(Finalize.DEFERRED, product_id=result.product_id)
        return await finalize_product(
            session,
            shop_id=post.shop_id,
            channel_message_id=post.message_id,
            force=True,
            now_utc=now_utc,
        )

    if post.caption is not None:
        product.caption_raw = post.caption
        await session.flush()

    return await finalize_product(
        session,
        shop_id=post.shop_id,
        media_group_id=post.media_group_id,
        channel_message_id=None if post.media_group_id else post.message_id,
        force=True,
        now_utc=now_utc,
    )
