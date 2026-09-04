"""The channel indexer's router: `channel_post` and `edited_channel_post`.

Deliberately NOT in `gulbot/bot/routers/`. That package is the customer-facing
conversation, its registration order is load-bearing, and the shadow sweep walks
it. A channel post is a different update type entirely -- it can neither shadow
nor be shadowed by anything there -- so mixing it in would put an unrelated
concern inside an ordering that has to stay easy to reason about.

`tests/test_indexer_scope.py` fails the build if this file, or the service it
calls, reaches into the send path or the customer-facing routers.

WHAT LIVES HERE, AND WHAT DOES NOT

Only the edge: unwrap the aiogram `Message` into a plain `ChannelPost` and
decide whether the album debounce is needed. Everything else -- the upsert, the
merge, the gate, the parse -- is in `gulbot.services.indexer`, which knows
nothing about aiogram and can be tested without synthesising Telegram objects.

The debounce SCHEDULER is injected rather than imported. In production it is the
Redis-backed one from `gulbot.worker.debounce`; in tests it is a recorder, so
the handler wiring can be tested through the real dispatcher without a running
Celery worker.
"""

from __future__ import annotations

import logging
from typing import Protocol

from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.services.indexer import (
    ChannelPost,
    Finalize,
    Ingest,
    apply_edit,
    finalize_product,
    ingest_post,
)

log = logging.getLogger("gulbot.indexer")


class FinalizeScheduler(Protocol):
    """Ask for one album to be settled, shortly, once."""

    async def __call__(self, *, shop_id: int, media_group_id: str) -> None: ...


async def noop_scheduler(*, shop_id: int, media_group_id: str) -> None:
    """Default for contexts with no worker -- the shadow sweep builds a real
    dispatcher and must not need Redis to do it."""
    return None


def as_channel_post(message: Message, shop_id: int) -> ChannelPost:
    """The largest photo size is the one worth keeping: it is the same file on
    Telegram's side, and a thumbnail cannot be re-expanded later."""
    photo = message.photo[-1] if message.photo else None
    return ChannelPost(
        shop_id=shop_id,
        chat_id=message.chat.id,
        message_id=message.message_id,
        file_id=photo.file_id if photo else None,
        media_group_id=message.media_group_id,
        caption=message.caption,
    )


async def on_channel_post(
    message: Message,
    session: AsyncSession,
    shop_id: int,
    schedule_finalize: FinalizeScheduler,
) -> None:
    post = as_channel_post(message, shop_id)
    result = await ingest_post(session, post)

    if result.outcome is Ingest.IGNORED:
        # No row, no tracked skip. A text announcement or an untagged photo is
        # simply not a catalogue entry.
        return

    if result.needs_debounce and post.media_group_id is not None:
        await schedule_finalize(shop_id=shop_id, media_group_id=post.media_group_id)
        return

    outcome = await finalize_product(session, shop_id=shop_id, channel_message_id=post.message_id)
    log.info(
        "indexed message=%s outcome=%s tags=%s",
        post.message_id,
        outcome.outcome.value,
        len(outcome.hashtags),
    )


async def on_edited_channel_post(
    message: Message,
    session: AsyncSession,
    shop_id: int,
    schedule_finalize: FinalizeScheduler,
) -> None:
    post = as_channel_post(message, shop_id)
    outcome = await apply_edit(session, post)

    # An edit that ingested a not-yet-indexed album leaves it provisional on
    # purpose; the debounce settles it with its siblings.
    if outcome.outcome is Finalize.DEFERRED and post.media_group_id is not None:
        await schedule_finalize(shop_id=shop_id, media_group_id=post.media_group_id)
        return

    log.info(
        "edited message=%s outcome=%s tags=%s",
        post.message_id,
        outcome.outcome.value,
        len(outcome.hashtags),
    )


def build_channel_router() -> Router:
    """Same factory + explicit .register() convention as every other router.

    `F.photo` is half the gate and the cheapest half: a post with no photo is
    refused before a session is even used. The hashtag half cannot live in a
    filter, because for an album it is not decidable until the group settles.
    """
    router = Router(name="channel")
    router.channel_post.register(on_channel_post, F.photo)
    router.edited_channel_post.register(on_edited_channel_post, F.photo)
    return router
