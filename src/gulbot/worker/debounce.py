"""Collapsing an album's N arrivals into ONE finalize task.

THE PROBLEM. Five photos posted together arrive as five updates within
milliseconds. Naively scheduling a finalize per arrival gives five tasks doing
the same work, four of them on a row that is still incomplete. The brief asks
for the opposite: rescheduling should COLLAPSE, not stack.

THE MECHANISM. Two Redis keys per album:

  deadline  the instant the album is considered settled. EVERY arrival
            overwrites it with now + DEBOUNCE_SECONDS.
  lock      held by whichever arrival scheduled the one task in flight. Set
            with NX, so exactly one arrival gets it.

So five arrivals push the deadline out five times, and schedule ONE task. When
that task fires it compares the deadline to the clock. Later than now? Somebody
arrived after it was scheduled, so it reschedules ITSELF for the new deadline
and keeps the lock -- still one task. Not later? The album has settled; it
finalizes and only then releases the lock.

Re-reading the deadline AFTER finalizing closes the last window: a member that
arrives while finalize is running would otherwise be merged into the row and
never re-parsed, because the lock it needed to schedule a task was still held.

WHAT MAKES THIS SAFE IS NOT THIS FILE. `finalize_product` is idempotent on its
own, and an album arrival re-opens the row by nulling `finalized_at`. The
debounce is an efficiency measure over the top of that. If Redis lost every key
here, the indexer would do more work and still reach the same answer.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

#: Long enough to cover an album's arrival spread, short enough that a shop
#: posting a bouquet sees it in the catalogue immediately.
DEBOUNCE_SECONDS = 3.0

#: Both keys expire. A crash between touch and finalize must not leave an album
#: permanently locked out of ever being scheduled again.
KEY_TTL_SECONDS = 300

#: Guards against a busy reschedule loop if clocks disagree by a hair.
MIN_RESCHEDULE_SECONDS = 0.5


class Action(StrEnum):
    WAIT = "wait"
    RUN = "run"
    EXPIRED = "expired"


@dataclass(frozen=True)
class Decision:
    action: Action
    delay: float = 0.0


def decide(deadline: float | None, now: float) -> Decision:
    """Pure. What a fired finalize task should do, given the album's deadline.

    Split out from the Redis calls so the branch that actually matters -- "a
    photo arrived after I was scheduled" -- is testable without a clock, a
    broker or a database.
    """
    if deadline is None:
        # The keys expired (TTL) or somebody released them. The caller still
        # finalizes: leaving a row provisional forever is the worse failure.
        return Decision(Action.EXPIRED)
    if deadline > now:
        return Decision(Action.WAIT, delay=max(deadline - now, MIN_RESCHEDULE_SECONDS))
    return Decision(Action.RUN)


class RedisLike(Protocol):
    """Just the four calls used here, so tests may substitute a fake."""

    async def set(
        self, name: str, value: str, *, ex: int | None = ..., nx: bool = ...
    ) -> bool | None: ...

    async def get(self, name: str) -> bytes | str | None: ...

    async def delete(self, *names: str) -> int: ...


def album_keys(shop_id: int, media_group_id: str) -> tuple[str, str]:
    base = f"gulbot:album:{shop_id}:{media_group_id}"
    return f"{base}:deadline", f"{base}:lock"


class AlbumDebouncer:
    def __init__(
        self,
        redis: RedisLike,
        *,
        delay: float = DEBOUNCE_SECONDS,
        ttl: int = KEY_TTL_SECONDS,
        # WALL clock, not monotonic. The deadline is written by the BOT process
        # and read by a CELERY worker process, and time.monotonic has a
        # different origin in every process -- a monotonic deadline would be
        # meaningless across the two.
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.redis = redis
        self.delay = delay
        self.ttl = ttl
        # Injected so tests can step time instead of sleeping through it.
        self._clock = clock

    def now(self) -> float:
        return float(self._clock())

    async def touch(self, *, shop_id: int, media_group_id: str) -> bool:
        """Push the deadline out. True when THIS caller must schedule the task.

        Every arrival moves the deadline; only the one that wins the NX lock
        schedules anything. That is the whole collapse.
        """
        deadline_key, lock_key = album_keys(shop_id, media_group_id)
        await self.redis.set(deadline_key, repr(self.now() + self.delay), ex=self.ttl)
        acquired = await self.redis.set(lock_key, "1", ex=self.ttl, nx=True)
        return bool(acquired)

    async def deadline(self, *, shop_id: int, media_group_id: str) -> float | None:
        deadline_key, _ = album_keys(shop_id, media_group_id)
        raw = await self.redis.get(deadline_key)
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode()
        return float(raw)

    async def release(self, *, shop_id: int, media_group_id: str) -> None:
        await self.redis.delete(*album_keys(shop_id, media_group_id))


# --- production wiring -----------------------------------------------------
#
# Deliberately here rather than in `worker/tasks.py`. The bot process calls
# `schedule_album_finalize` on every album arrival, and `worker/tasks.py`
# imports the send path at module level -- importing it from the indexer would
# drag CP6 into CP8 and trip the scope fence. This module imports the Celery app
# and nothing else.


@asynccontextmanager
async def album_debouncer() -> AsyncIterator[AlbumDebouncer]:
    """A debouncer that owns its Redis client for the life of ONE call.

    NOT a cached module-level client, and the reason is worth stating because
    the cached version looked obviously correct and was fatal:

    A `redis.asyncio` connection is bound to the event loop that opened it.
    The Celery task wraps each run in `asyncio.run()`, which creates a loop and
    then CLOSES it. A cached client therefore hands the second task in a worker
    process a socket whose loop is dead, and it fails with
    `RuntimeError: Event loop is closed` -- not on the first album, on the
    second, which is exactly the shape of bug a green test suite misses. Every
    test in this repo runs inside one pytest event loop.

    Found by running a real Celery worker, not by reading the code. Guarded by
    `test_the_debounce_survives_a_fresh_event_loop_per_call`.

    One client per call rather than one per process is also what keeps the
    shadow sweep able to build a dispatcher with no Redis running: nothing here
    connects until an album actually arrives.
    """
    from redis.asyncio import Redis

    from gulbot.config import get_settings

    settings = get_settings()
    client = Redis.from_url(settings.redis_url(settings.redis_db_broker))
    try:
        yield AlbumDebouncer(client)
    finally:
        await client.aclose()


async def schedule_album_finalize(*, shop_id: int, media_group_id: str) -> None:
    """One task per album, however many photos it has."""
    from gulbot.worker.app import app

    async with album_debouncer() as debouncer:
        if await debouncer.touch(shop_id=shop_id, media_group_id=media_group_id):
            app.send_task(
                "gulbot.finalize_album",
                args=[shop_id, media_group_id],
                countdown=debouncer.delay,
            )
