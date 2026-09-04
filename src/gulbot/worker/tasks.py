"""Celery tasks. Thin wrappers: all logic lives in the services they call."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select

from gulbot.db.session import build_session_factory
from gulbot.models.shop import Shop
from gulbot.sending.dispatcher import run_tick
from gulbot.sending.rate_limit import RateLimiter
from gulbot.sending.render import render_reminder
from gulbot.services.materializer import materialize_shop
from gulbot.worker.app import app

log = logging.getLogger("gulbot.worker")


async def _send_due_reminders() -> dict[str, int]:
    from gulbot.bot.factory import build_bot
    from gulbot.sending.telegram import TelegramTransport

    factory = build_session_factory()
    bot = build_bot()
    limiter = RateLimiter(clock=lambda: asyncio.get_event_loop().time())
    try:
        async with factory() as session:
            result = await run_tick(
                session,
                transport=TelegramTransport(bot),
                render=render_reminder,
                now_utc=datetime.now(UTC),
                limiter=limiter,
            )
            await session.commit()
    finally:
        await bot.session.close()
    log.info(
        "tick: groups=%s sent=%s expired=%s failed=%s cancelled=%s",
        result.groups,
        result.sent,
        result.expired,
        result.failed,
        result.cancelled,
    )
    return {"groups": result.groups, "sent": result.sent}


async def _materialize_all_shops() -> dict[str, int]:
    factory = build_session_factory()
    totals = {"inserted": 0, "pruned": 0}
    async with factory() as session:
        shop_ids = list(await session.scalars(select(Shop.id)))
        for shop_id in shop_ids:
            result = await materialize_shop(session, shop_id=shop_id, now_utc=datetime.now(UTC))
            totals["inserted"] += result.inserted
            totals["pruned"] += result.pruned
        await session.commit()
    log.info("materialize: %s", totals)
    return totals


@app.task(name="gulbot.send_due_reminders")
def send_due_reminders() -> dict[str, int]:
    return asyncio.run(_send_due_reminders())


@app.task(name="gulbot.materialize_all_shops")
def materialize_all_shops() -> dict[str, int]:
    return asyncio.run(_materialize_all_shops())
