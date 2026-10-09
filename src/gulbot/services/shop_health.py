"""Bot-health snapshots and job heartbeats: what the admin panel reads instead
of calling Telegram from a web request (CP18).

SNAPSHOTS. Every 10 minutes the worker asks, per shop, through that shop's own
bot: is the token accepted (getMe), is the bot an admin of the shop's channel,
is it an admin of the shop's group (getChat + getChatMember -- NEVER a test
post: this runs 144 times a day). One row per shop per run; rows older than a
week are pruned by the same job.

HEARTBEATS. Every periodic task records when it last started and finished, and
whether it succeeded, in `job_runs`. The panel's "stalled job" alert and the
page server's `/healthz/jobs` read it -- both from the WEB process, so a dead
beat or worker is visible even though the health check (itself a beat task)
would have died with it. That endpoint is the hook for an external
dead-man's-switch monitor (docs/DEPLOY.md).
"""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

from aiogram import Bot
from aiogram.exceptions import TelegramUnauthorizedError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger("gulbot.services.shop_health")

#: Snapshots are kept this long.
SNAPSHOT_RETENTION = timedelta(days=7)
#: The jobs whose silence means beat or the worker is dead -- the ones
#: /healthz/jobs answers for. The nightly jobs are watched in the panel only.
LIVENESS_JOBS: dict[str, timedelta] = {
    "send_due_reminders": timedelta(minutes=1),
    "send_order_pings": timedelta(minutes=1),
    "check_health": timedelta(minutes=5),
}

T = TypeVar("T")


@dataclass(frozen=True)
class Snapshot:
    shop_id: int
    token_valid: bool | None
    bot_username: str | None
    channel_ok: bool | None
    group_ok: bool | None
    detail: dict[str, Any]


async def check_shop(
    bot: Bot | None, *, shop_id: int, channel_id: int | None, group_chat_id: int | None
) -> Snapshot:
    """One shop, through its own bot. `None` for a part that was not checked."""
    from gulbot.bot.chat_checks import check_channel, check_group_standing

    if bot is None:
        return Snapshot(shop_id, None, None, None, None, {"bot": "no usable bot"})
    try:
        me = await bot.get_me()
    except TelegramUnauthorizedError:
        return Snapshot(shop_id, False, None, None, None, {"token": "rejected"})
    except Exception as exc:  # noqa: BLE001 - Telegram unreachable: not the token's fault
        return Snapshot(shop_id, None, None, None, None, {"token": type(exc).__name__})
    detail: dict[str, Any] = {}
    channel_ok = group_ok = None
    if channel_id is not None:
        channel = await check_channel(bot, channel_id)
        channel_ok = channel.ok
        if channel.problem is not None:
            detail["channel"] = channel.problem.value
    if group_chat_id is not None:
        group = await check_group_standing(bot, group_chat_id)
        group_ok = group.ok
        if group.problem is not None:
            detail["group"] = group.problem.value
    return Snapshot(shop_id, True, me.username, channel_ok, group_ok, detail)


async def store_snapshots(
    session: AsyncSession, snapshots: list[Snapshot], *, now: datetime | None = None
) -> None:
    now = now or datetime.now(UTC)
    for s in snapshots:
        await session.execute(
            text(
                "INSERT INTO shop_health_snapshots "
                "(shop_id, checked_at, token_valid, bot_username, channel_ok, group_ok, detail) "
                "VALUES (:s, :at, :t, :u, :c, :g, CAST(:d AS jsonb))"
            ),
            {
                "s": s.shop_id,
                "at": now,
                "t": s.token_valid,
                "u": s.bot_username,
                "c": s.channel_ok,
                "g": s.group_ok,
                "d": _json(s.detail),
            },
        )
    await session.execute(
        text("DELETE FROM shop_health_snapshots WHERE checked_at < :cut"),
        {"cut": now - SNAPSHOT_RETENTION},
    )


def _json(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


#: At most this many shops are checked at once: a slow or dead bot costs one
#: slot for up to the 15 s request timeout, never the whole run.
CHECK_CONCURRENCY = 10


async def snapshot_all_shops(
    session: AsyncSession,
    bot_for: Callable[[int], Bot],
    *,
    now: datetime | None = None,
) -> list[Snapshot]:
    """Check every shop through its own bot and store one snapshot each.
    `bot_for` raises for a shop with no usable bot; that shop is recorded as
    such rather than skipped, so the panel can say so."""
    from gulbot.sending.transport import ShopBotUnavailable

    shops = (
        await session.execute(text("SELECT id, channel_id, group_chat_id FROM shops ORDER BY id"))
    ).all()
    gate = asyncio.Semaphore(CHECK_CONCURRENCY)

    async def one(shop_id: int, channel_id: int | None, group_chat_id: int | None) -> Snapshot:
        try:
            bot: Bot | None = bot_for(shop_id)
        except (ShopBotUnavailable, LookupError):
            bot = None
        async with gate:
            return await check_shop(
                bot, shop_id=shop_id, channel_id=channel_id, group_chat_id=group_chat_id
            )

    snapshots = list(await asyncio.gather(*(one(*row) for row in shops)))
    await store_snapshots(session, snapshots, now=now)
    return snapshots


# --- heartbeats -------------------------------------------------------------------


async def record_run(
    session: AsyncSession,
    *,
    name: str,
    started_at: datetime,
    finished_at: datetime | None,
    ok: bool | None,
    error: str | None = None,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO job_runs (name, last_started_at, last_finished_at, last_ok, last_error)
            VALUES (:n, :s, :f, :ok, :e)
            ON CONFLICT (name) DO UPDATE SET
              last_started_at = EXCLUDED.last_started_at,
              last_finished_at = coalesce(EXCLUDED.last_finished_at, job_runs.last_finished_at),
              last_ok = coalesce(EXCLUDED.last_ok, job_runs.last_ok),
              last_error = EXCLUDED.last_error
            """
        ),
        {"n": name, "s": started_at, "f": finished_at, "ok": ok, "e": error},
    )


async def _record_with_own_engine(**values: Any) -> None:
    from gulbot.db.session import task_session_factory

    async with task_session_factory() as factory, factory() as session:
        await record_run(session, **values)
        await session.commit()


def heartbeat(name: str) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Wrap a SYNCHRONOUS Celery task body: record its start, then its finish
    and outcome. A failure to RECORD is logged and swallowed -- the heartbeat
    must never be what breaks a tick. A failure of the TASK is recorded and
    re-raised unchanged."""

    def wrap(fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def run(*args: Any, **kwargs: Any) -> T:
            started = datetime.now(UTC)
            _quietly(name=name, started_at=started, finished_at=None, ok=None)
            try:
                result = fn(*args, **kwargs)
            except BaseException as exc:
                _quietly(
                    name=name,
                    started_at=started,
                    finished_at=None,
                    ok=False,
                    error=type(exc).__name__,
                )
                raise
            _quietly(name=name, started_at=started, finished_at=datetime.now(UTC), ok=True)
            return result

        return run

    return wrap


def _quietly(**values: Any) -> None:
    try:
        asyncio.run(_record_with_own_engine(**values))
    except Exception:  # noqa: BLE001 - see heartbeat()
        log.exception("could not record a heartbeat for %s", values.get("name"))


async def stale_jobs(session: AsyncSession, *, now: datetime | None = None) -> list[str]:
    """The liveness jobs not finished within twice their interval, by name."""
    now = now or datetime.now(UTC)
    finished: dict[str, datetime | None] = dict(
        (await session.execute(text("SELECT name, last_finished_at FROM job_runs"))).all()
    )
    stale = []
    for name, interval in LIVENESS_JOBS.items():
        last = finished.get(name)
        if last is None or last < now - 2 * interval:
            stale.append(name)
    return stale
