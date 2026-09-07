"""Telling the shop when sending has stopped, and that it is still running.

WHAT THIS CAN AND CANNOT DO, stated first because the limit is the whole design.

Everything here runs INSIDE the Celery worker. If the worker itself dies, none
of it runs -- so a silent day is the signal, not an alarm. That is a real weak
spot and it is not fixable from inside the process that died: the reliable
version is an external service pinging a URL and mailing the owner when it stops
answering. This is the version that needs no third-party account, and it detects
the failures that actually happen more often than a dead worker: Telegram
refusing sends, the database rejecting writes, a shop whose group was deleted.

TWO SIGNALS, deliberately different in kind:

  the daily summary   proves the whole chain is alive end to end -- beat picked
                      the job up, the worker ran it, the database answered, the
                      Bot API accepted a message, it landed in the group. A
                      quiet, boring line once a day. Its ABSENCE is the alarm.

  the stall alert     something is due and has not gone out. Fires once and
                      then stays quiet, because an alert that repeats every
                      minute is one the shop learns to ignore.

WHY THE COOLDOWN IS IN REDIS. It has to survive the process, and it has to
expire on its own. A database column would need a migration and a nightly
sweep to reset it; a Redis key with a TTL is both halves for free. If Redis
loses the key the shop gets one duplicate alert, which is the right way for
this to fail.

The client is opened and closed inside each call, never cached -- the same rule
CP8's debouncer learned the hard way, because Celery closes the event loop
between tasks and a cached client hands the next task a dead socket.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.models.notification import NotificationState, ScheduledNotification
from gulbot.models.order import Order, OrderReminder, PingState
from gulbot.scheduling.occurrences import TASHKENT

log = logging.getLogger("gulbot.health")

#: How overdue a pending row has to be before it counts as a stall. Generous
#: against the one-minute tick: a row a minute late is a tick that has not run
#: yet, not an outage. Fifteen minutes is fifteen missed ticks.
STALL_AFTER = timedelta(minutes=15)

#: How long an alert stays quiet after firing. Long enough that a shop is not
#: pestered while someone is already fixing it; short enough that an outage
#: spanning a working day is mentioned more than once.
ALERT_COOLDOWN = timedelta(hours=1)

#: Redis key prefix. Namespaced by shop so a second shop cannot silence the
#: first one's alerts.
ALERT_KEY = "gulbot:alert"


@dataclass(frozen=True)
class Health:
    """One look at the outbox. Counts only -- no rendering, no sending."""

    overdue_reminders: int
    overdue_pings: int
    parked_reminders: int
    parked_pings: int

    @property
    def stalled(self) -> bool:
        return bool(self.overdue_reminders or self.overdue_pings)

    @property
    def parked(self) -> bool:
        return bool(self.parked_reminders or self.parked_pings)


@dataclass(frozen=True)
class DailyTotals:
    """What the shop did today, in its own timezone."""

    reminders_sent: int
    orders_placed: int
    parked_reminders: int
    parked_pings: int


def tashkent_day_start(now_utc: datetime) -> datetime:
    """Midnight in Tashkent, as a UTC instant.

    The shop's day, not UTC's. A summary at 21:00 local that counted a UTC day
    would drop the last five hours of every evening -- which is exactly when a
    flower shop is busiest.
    """
    local = now_utc.astimezone(TASHKENT)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(UTC)


async def read_health(session: AsyncSession, *, shop_id: int, now_utc: datetime) -> Health:
    """Count what is stuck. Cheap enough to run every few minutes."""
    cutoff = now_utc - STALL_AFTER

    overdue_reminders = await session.scalar(
        select(func.count())
        .select_from(ScheduledNotification)
        .where(
            ScheduledNotification.shop_id == shop_id,
            ScheduledNotification.state == NotificationState.PENDING.value,
            ScheduledNotification.due_at_utc <= cutoff,
        )
    )
    overdue_pings = await session.scalar(
        select(func.count())
        .select_from(OrderReminder)
        .where(
            OrderReminder.shop_id == shop_id,
            OrderReminder.state.in_([PingState.PENDING.value, PingState.FAILED.value]),
            OrderReminder.due_at_utc <= cutoff,
        )
    )
    parked_reminders = await session.scalar(
        select(func.count())
        .select_from(ScheduledNotification)
        .where(
            ScheduledNotification.shop_id == shop_id,
            ScheduledNotification.state == NotificationState.DEAD_LETTER.value,
        )
    )
    parked_pings = await session.scalar(
        select(func.count())
        .select_from(OrderReminder)
        .where(
            OrderReminder.shop_id == shop_id,
            OrderReminder.state == PingState.DEAD_LETTER.value,
        )
    )
    return Health(
        overdue_reminders=overdue_reminders or 0,
        overdue_pings=overdue_pings or 0,
        parked_reminders=parked_reminders or 0,
        parked_pings=parked_pings or 0,
    )


async def read_daily_totals(
    session: AsyncSession, *, shop_id: int, now_utc: datetime
) -> DailyTotals:
    """Today's numbers, counted from Tashkent midnight."""
    since = tashkent_day_start(now_utc)

    reminders_sent = await session.scalar(
        select(func.count())
        .select_from(ScheduledNotification)
        .where(
            ScheduledNotification.shop_id == shop_id,
            ScheduledNotification.state == NotificationState.SENT.value,
            ScheduledNotification.sent_at >= since,
        )
    )
    orders_placed = await session.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.shop_id == shop_id, Order.created_at >= since)
    )
    health = await read_health(session, shop_id=shop_id, now_utc=now_utc)
    return DailyTotals(
        reminders_sent=reminders_sent or 0,
        orders_placed=orders_placed or 0,
        parked_reminders=health.parked_reminders,
        parked_pings=health.parked_pings,
    )


@asynccontextmanager
async def alert_cooldown() -> AsyncIterator[AlertCooldown]:
    """A Redis client owned for the life of ONE call.

    Never cached. Celery wraps each task in `asyncio.run()`, which closes the
    loop afterwards, and a `redis.asyncio` client is bound to the loop that
    opened it -- so a cached one hands the NEXT task a dead socket and fails
    with `RuntimeError: Event loop is closed`, on the second run and never the
    first. CP8 found that the hard way; see `worker/debounce.py`.
    """
    from redis.asyncio import Redis

    from gulbot.config import get_settings

    settings = get_settings()
    client = Redis.from_url(settings.redis_url(settings.redis_db_broker))
    try:
        yield AlertCooldown(client)
    finally:
        await client.aclose()


class AlertCooldown:
    """Decides whether an alert of a given kind may be sent right now."""

    def __init__(self, client: object) -> None:
        self.client = client

    async def claim(self, *, shop_id: int, kind: str) -> bool:
        """True exactly once per cooldown window.

        SET NX EX, so two workers checking at the same instant produce ONE
        alert rather than two -- the same single-flight reasoning as everywhere
        else in this project, done with the tool that already expires keys.
        """
        key = f"{ALERT_KEY}:{shop_id}:{kind}"
        acquired = await self.client.set(  # type: ignore[attr-defined]
            key, "1", nx=True, ex=int(ALERT_COOLDOWN.total_seconds())
        )
        return bool(acquired)
