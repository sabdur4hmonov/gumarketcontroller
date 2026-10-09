"""Celery tasks. Thin wrappers: all logic lives in the services they call."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from gulbot.bot.registry import BotRegistry, registry_for
from gulbot.db.session import task_session_factory
from gulbot.models.shop import Shop
from gulbot.sending.dispatcher import run_tick
from gulbot.sending.rate_limit import RateLimiter
from gulbot.sending.render import render_reminder
from gulbot.sending.transport import TransportFor
from gulbot.services.indexer import finalize_product
from gulbot.services.materializer import materialize_shop
from gulbot.services.shop_health import heartbeat
from gulbot.worker.app import (
    ALBUM_HARD_LIMIT,
    ALBUM_SOFT_LIMIT,
    HEALTH_HARD_LIMIT,
    HEALTH_SOFT_LIMIT,
    MATERIALIZE_HARD_LIMIT,
    MATERIALIZE_SOFT_LIMIT,
    PAGE_NOTIFY_HARD_LIMIT,
    PAGE_NOTIFY_SOFT_LIMIT,
    PAGE_SCRUB_HARD_LIMIT,
    PAGE_SCRUB_SOFT_LIMIT,
    SNAPSHOT_HARD_LIMIT,
    SNAPSHOT_SOFT_LIMIT,
    SUMMARY_HARD_LIMIT,
    SUMMARY_SOFT_LIMIT,
    TICK_HARD_LIMIT,
    TICK_SOFT_LIMIT,
    app,
)
from gulbot.worker.debounce import AlbumDebouncer

if TYPE_CHECKING:
    from gulbot.sending.alerts import Job

log = logging.getLogger("gulbot.worker")


def _transports(registry: BotRegistry) -> TransportFor:
    """shop_id -> a transport over that shop's bot. C1/C2 of the audit: the
    outbox spans every shop, so the worker must never hand a tick one bot."""
    from gulbot.sending.telegram import TelegramTransport

    return lambda shop_id: TelegramTransport(registry.bot_for(shop_id))


async def _send_due_reminders() -> dict[str, int]:
    from functools import partial

    from gulbot.sending.attach import attach_bouquet

    # One limiter for the tick; its buckets are per shop's bot (H4).
    limiter = RateLimiter(clock=lambda: asyncio.get_event_loop().time())
    async with task_session_factory() as factory, factory() as session:
        # Each shop's own stored token (or the logged legacy fallback), loaded
        # once per call. Closed in the `finally`, exactly as the single bot
        # was: the registry caches bots for THIS call only.
        registry = await registry_for(session)
        try:
            result = await run_tick(
                session,
                transport_for=_transports(registry),
                render=render_reminder,
                now_utc=datetime.now(UTC),
                limiter=limiter,
                # CP9. Returns None for an empty catalogue or no match, and the
                # tick then sends bare text exactly as CP6 did.
                attach=partial(attach_bouquet, session, render=render_reminder),
            )
            await session.commit()
        finally:
            await registry.close()
    log.info(
        "tick: groups=%s sent=%s expired=%s failed=%s cancelled=%s handed_back=%s",
        result.groups,
        result.sent,
        result.expired,
        result.failed,
        result.cancelled,
        result.handed_back,
    )
    return {"groups": result.groups, "sent": result.sent}


async def _send_order_pings() -> dict[str, int]:
    """The shop-facing outbox. Same lifetime discipline as the reminder tick.

    The bots are built here and their sessions closed in a `finally` --
    `build_bot()` is uncached for exactly this reason. An aiohttp session that
    outlived the call would hand the NEXT task a client bound to a closed event
    loop, which is the defect CP8 spent a live run finding. The registry keeps
    that rule: it caches bots within this call and closes them all at its end.
    """
    from gulbot.sending.order_pings import run_order_ping_tick

    async with task_session_factory() as factory, factory() as session:
        registry = await registry_for(session)
        try:
            result = await run_order_ping_tick(
                session, transport_for=_transports(registry), now_utc=datetime.now(UTC)
            )
        finally:
            await registry.close()
    log.info(
        "order pings: claimed=%s sent=%s failed=%s dead=%s undeliverable=%s handed_back=%s",
        result.claimed,
        result.sent,
        result.failed,
        result.dead_lettered,
        result.undeliverable,
        result.handed_back,
    )
    return {"claimed": result.claimed, "sent": result.sent}


async def _for_every_shop(job: Job) -> dict[str, int]:
    """Run one health job for every shop. Shared by both CP11.5 tasks.

    Each shop's alert goes through ITS OWN bot -- see
    `alerts.announce_for_every_shop`, where the loop now lives. This used to
    build one global Bot for every shop's alerts, the last send path that did.

    The registry is built here and closed in a `finally`, the same lifetime
    rule as every other sending task: `build_bot()` is uncached, so the
    clients belong to this call's event loop and die with it.
    """
    from gulbot.sending import alerts

    now = datetime.now(UTC)
    async with task_session_factory() as factory, factory() as session:
        registry = await registry_for(session)
        try:
            counts = await alerts.announce_for_every_shop(
                session, job=job, transport_for=_transports(registry), now_utc=now
            )
            await session.commit()
        finally:
            await registry.close()
    return counts


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


@app.task(
    name="gulbot.send_due_reminders",
    soft_time_limit=TICK_SOFT_LIMIT,
    time_limit=TICK_HARD_LIMIT,
)
@heartbeat("send_due_reminders")
def send_due_reminders() -> dict[str, int]:
    return asyncio.run(_send_due_reminders())


@app.task(
    name="gulbot.send_order_pings",
    soft_time_limit=TICK_SOFT_LIMIT,
    time_limit=TICK_HARD_LIMIT,
)
@heartbeat("send_order_pings")
def send_order_pings() -> dict[str, int]:
    return asyncio.run(_send_order_pings())


@app.task(
    name="gulbot.check_health",
    soft_time_limit=HEALTH_SOFT_LIMIT,
    time_limit=HEALTH_HARD_LIMIT,
)
@heartbeat("check_health")
def check_health() -> dict[str, int]:
    result = asyncio.run(_for_every_shop("check"))
    log.info("health check: %s", result)
    return result


@app.task(
    name="gulbot.send_daily_summary",
    soft_time_limit=SUMMARY_SOFT_LIMIT,
    time_limit=SUMMARY_HARD_LIMIT,
)
@heartbeat("send_daily_summary")
def send_daily_summary_task() -> dict[str, int]:
    result = asyncio.run(_for_every_shop("summary"))
    log.info("daily summary: %s", result)
    return result


@app.task(
    name="gulbot.materialize_all_shops",
    soft_time_limit=MATERIALIZE_SOFT_LIMIT,
    time_limit=MATERIALIZE_HARD_LIMIT,
)
@heartbeat("materialize_all_shops")
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


@app.task(
    name="gulbot.finalize_album",
    soft_time_limit=ALBUM_SOFT_LIMIT,
    time_limit=ALBUM_HARD_LIMIT,
)
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


# --- Ha/Yo'q pages and taklifnomas -------------------------------------------


async def _notify_page_answer(page_id: int) -> str:
    from gulbot.sending.page_notify import notify_page_answer as notify

    async with task_session_factory() as factory:
        return await notify(page_id, session_factory=factory)


def _notify_retry() -> tuple[type[Exception], ...]:
    from gulbot.sending.page_notify import NotifyRetry

    return (NotifyRetry,)


@app.task(
    name="gulbot.notify_page_answer",
    soft_time_limit=PAGE_NOTIFY_SOFT_LIMIT,
    time_limit=PAGE_NOTIFY_HARD_LIMIT,
    autoretry_for=_notify_retry(),
    retry_backoff=60,
    max_retries=3,
)
def notify_page_answer(page_id: int) -> str:
    """Queued by the page server on a page's FIRST Ha. The claim in the
    database, not this task, is what makes the message go out at most once."""
    return asyncio.run(_notify_page_answer(page_id))


async def _scrub_expired_pages() -> int:
    from gulbot.services.share_pages import scrub_expired

    async with task_session_factory() as factory, factory() as session:
        scrubbed = await scrub_expired(session)
        await session.commit()
    log.info("share pages: scrubbed %s expired page(s)", scrubbed)
    return scrubbed


@app.task(
    name="gulbot.scrub_expired_pages",
    soft_time_limit=PAGE_SCRUB_SOFT_LIMIT,
    time_limit=PAGE_SCRUB_HARD_LIMIT,
)
@heartbeat("scrub_expired_pages")
def scrub_expired_pages() -> int:
    return asyncio.run(_scrub_expired_pages())


# --- CP18: bot-health snapshots for the platform admin panel -----------------


async def _snapshot_shop_health() -> int:
    from gulbot.services.shop_health import snapshot_all_shops

    async with task_session_factory() as factory, factory() as session:
        registry = await registry_for(session)
        try:
            snapshots = await snapshot_all_shops(session, registry.bot_for)
            await session.commit()
        finally:
            await registry.close()
    log.info("shop health: %s shop(s) checked", len(snapshots))
    return len(snapshots)


@app.task(
    name="gulbot.snapshot_shop_health",
    soft_time_limit=SNAPSHOT_SOFT_LIMIT,
    time_limit=SNAPSHOT_HARD_LIMIT,
)
@heartbeat("snapshot_shop_health")
def snapshot_shop_health() -> int:
    """Every 10 minutes: token, channel and group standing of every shop's bot,
    for the admin panel -- which never calls Telegram from a page request."""
    return asyncio.run(_snapshot_shop_health())
