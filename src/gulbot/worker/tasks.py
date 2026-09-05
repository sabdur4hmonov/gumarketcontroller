"""Celery tasks. Thin wrappers: all logic lives in the services they call."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select

from gulbot.db.session import task_session_factory
from gulbot.models.shop import Shop
from gulbot.sending.dispatcher import run_tick
from gulbot.sending.rate_limit import RateLimiter
from gulbot.sending.render import render_reminder
from gulbot.services.indexer import finalize_product
from gulbot.services.materializer import materialize_shop
from gulbot.worker.app import app
from gulbot.worker.debounce import AlbumDebouncer

log = logging.getLogger("gulbot.worker")


async def _send_due_reminders() -> dict[str, int]:
    from functools import partial

    from gulbot.bot.factory import build_bot
    from gulbot.sending.attach import attach_bouquet
    from gulbot.sending.telegram import TelegramTransport

    bot = build_bot()
    limiter = RateLimiter(clock=lambda: asyncio.get_event_loop().time())
    try:
        async with task_session_factory() as factory, factory() as session:
            result = await run_tick(
                session,
                transport=TelegramTransport(bot),
                render=render_reminder,
                now_utc=datetime.now(UTC),
                limiter=limiter,
                # CP9. Returns None for an empty catalogue or no match, and the
                # tick then sends bare text exactly as CP6 did.
                attach=partial(attach_bouquet, session, render=render_reminder),
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
    totals = {"inserted": 0, "pruned": 0}
    async with task_session_factory() as factory, factory() as session:
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


async def _finalize_album(shop_id: int, media_group_id: str) -> dict[str, object]:
    """Settle one album, or hand back how long to wait.

    Two deadline reads, and both matter:

    * BEFORE finalizing -- a photo may have arrived after this task was
      scheduled, in which case the album has not settled and this run defers
      instead of parsing a half-built row;
    * AFTER finalizing -- a photo may have arrived WHILE it was finalizing. It
      could not schedule a task of its own, because this run still holds the
      lock, so the responsibility to reschedule is this run's.

    The lock is released only when neither is true.
    """
    from gulbot.worker.debounce import album_debouncer

    # The client is created and closed inside this call. Celery gives every task
    # a fresh event loop and then closes it, so a client that outlives the call
    # hands the NEXT task a dead socket. See album_debouncer's docstring.
    async with album_debouncer() as debouncer:
        return await _settle_album(debouncer, shop_id, media_group_id)


async def _settle_album(
    debouncer: AlbumDebouncer, shop_id: int, media_group_id: str
) -> dict[str, object]:
    from gulbot.worker.debounce import MIN_RESCHEDULE_SECONDS, Action, decide

    started = debouncer.now()

    decision = decide(
        await debouncer.deadline(shop_id=shop_id, media_group_id=media_group_id), started
    )
    if decision.action is Action.WAIT:
        return {"action": "wait", "reschedule_in": decision.delay}

    async with task_session_factory() as factory, factory() as session:
        result = await finalize_product(session, shop_id=shop_id, media_group_id=media_group_id)
        await session.commit()

    arrived_while_working = await debouncer.deadline(shop_id=shop_id, media_group_id=media_group_id)
    if arrived_while_working is not None and arrived_while_working > started:
        delay = max(arrived_while_working - debouncer.now(), MIN_RESCHEDULE_SECONDS)
        return {"action": "again", "outcome": result.outcome.value, "reschedule_in": delay}

    await debouncer.release(shop_id=shop_id, media_group_id=media_group_id)
    log.info(
        "album %s: outcome=%s tags=%s", media_group_id, result.outcome.value, len(result.hashtags)
    )
    return {"action": "done", "outcome": result.outcome.value}


@app.task(name="gulbot.finalize_album")
def finalize_album(shop_id: int, media_group_id: str) -> dict[str, object]:
    result = asyncio.run(_finalize_album(shop_id, media_group_id))
    delay = result.pop("reschedule_in", None)
    if delay is not None:
        # Re-sends itself rather than spawning a sibling: there is still exactly
        # one task in flight for this album, which is the point of the lock.
        app.send_task(
            "gulbot.finalize_album",
            args=[shop_id, media_group_id],
            countdown=float(delay),  # type: ignore[arg-type]
        )
    return result
