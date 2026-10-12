"""CP23 phase 3: Instagram story publishing and token upkeep. Thin wrappers.

Each task owns its clients for its own run -- database engine, the shop's
bot, the aiohttp session to Meta -- and closes them (CONTRIBUTING: no I/O
client outlives one task). Both do nothing unless publishing is enabled.

The URL token travels as a task argument: Redis is bound to the server's
loopback, the token lives 15 minutes, and only its hash is stored.
"""

from __future__ import annotations

import asyncio
import logging

import aiohttp

from gulbot.bot.registry import registry_for
from gulbot.db.session import task_session_factory
from gulbot.sending.transport import ShopBotUnavailable
from gulbot.services import instagram
from gulbot.services.instagram_graph import Graph
from gulbot.worker.app import (
    INSTAGRAM_PUBLISH_HARD_LIMIT,
    INSTAGRAM_PUBLISH_SOFT_LIMIT,
    INSTAGRAM_REFRESH_HARD_LIMIT,
    INSTAGRAM_REFRESH_SOFT_LIMIT,
    app,
)

log = logging.getLogger("gulbot.instagram")


async def _publish(upload_id: int, token: str) -> str:
    async with task_session_factory() as sessions, aiohttp.ClientSession() as http:
        async with sessions() as session:
            registry = await registry_for(session)
        try:

            async def notify(shop_id: int, chat_id: int, text: str) -> None:
                try:
                    await registry.bot_for(shop_id).send_message(chat_id, text)
                except ShopBotUnavailable:
                    log.warning("instagram: shop %s has no bot to report the outcome", shop_id)

            status = await instagram.publish_upload(
                sessions,
                Graph(instagram.graph_config(), http),
                upload_id=upload_id,
                token=token,
                notify=notify,
            )
        finally:
            await registry.close()
    # The id and the outcome only: never the token.
    log.info("instagram: upload %s %s", upload_id, status)
    return status


@app.task(
    name="gulbot.publish_instagram_story",
    soft_time_limit=INSTAGRAM_PUBLISH_SOFT_LIMIT,
    time_limit=INSTAGRAM_PUBLISH_HARD_LIMIT,
)
def publish_instagram_story(upload_id: int, token: str) -> str:
    return asyncio.run(_publish(upload_id, token))


async def enqueue_story(upload_id: int, token: str) -> None:
    await asyncio.to_thread(
        publish_instagram_story.apply_async, args=[upload_id, token], expires=600
    )


async def _refresh() -> dict[str, int]:
    if not instagram.enabled():
        return {}
    async with (
        task_session_factory() as sessions,
        aiohttp.ClientSession() as http,
        sessions() as session,
    ):
        counts = await instagram.refresh_tokens(session, Graph(instagram.graph_config(), http))
        await session.commit()
    log.info("instagram upkeep: %s", counts)
    return counts


@app.task(
    name="gulbot.refresh_instagram_tokens",
    soft_time_limit=INSTAGRAM_REFRESH_SOFT_LIMIT,
    time_limit=INSTAGRAM_REFRESH_HARD_LIMIT,
)
def refresh_instagram_tokens() -> dict[str, int]:
    return asyncio.run(_refresh())
