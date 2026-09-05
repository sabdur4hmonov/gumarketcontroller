"""The debounce collapses N arrivals into ONE finalize task.

Two halves, tested separately on purpose:

* `decide` is pure -- it answers "should this fired task run, wait, or give
  up?" from a deadline and a clock. The branch that matters (a photo arrived
  after the task was scheduled) is a two-line function, not a timing puzzle.
* `AlbumDebouncer` is tested against REAL Redis, because the whole mechanism is
  `SET NX` semantics and a fake would just re-implement the thing under test.
  The clock is injected so the tests step time instead of sleeping through it.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
import redis.asyncio as aioredis

from gulbot.config import Settings
from gulbot.worker.debounce import (
    DEBOUNCE_SECONDS,
    MIN_RESCHEDULE_SECONDS,
    Action,
    AlbumDebouncer,
    album_debouncer,
    album_keys,
    decide,
)

ALBUM = "debounce-album"
SHOP = 4242


# --- the pure half ---------------------------------------------------------


def test_a_deadline_still_in_the_future_means_wait() -> None:
    """Somebody arrived after this task was scheduled."""
    decision = decide(deadline=110.0, now=100.0)
    assert decision.action is Action.WAIT
    assert decision.delay == 10.0


def test_a_deadline_in_the_past_means_run() -> None:
    assert decide(deadline=99.0, now=100.0).action is Action.RUN


def test_a_deadline_exactly_now_means_run() -> None:
    """Not WAIT: a zero-delay reschedule is a busy loop, not a wait."""
    assert decide(deadline=100.0, now=100.0).action is Action.RUN


def test_a_missing_deadline_means_the_keys_expired() -> None:
    assert decide(deadline=None, now=100.0).action is Action.EXPIRED


def test_a_wait_is_never_shorter_than_the_floor() -> None:
    """Clocks disagree by fractions; a 1ms reschedule would spin."""
    decision = decide(deadline=100.001, now=100.0)
    assert decision.delay == MIN_RESCHEDULE_SECONDS


# --- the Redis half --------------------------------------------------------


class StepClock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


@pytest_asyncio.fixture
async def debouncer(settings: Settings) -> AsyncIterator[AlbumDebouncer]:
    client = aioredis.from_url(settings.redis_url(settings.redis_db_test))
    await client.delete(*album_keys(SHOP, ALBUM))
    try:
        yield AlbumDebouncer(client, clock=StepClock())
    finally:
        await client.delete(*album_keys(SHOP, ALBUM))
        await client.aclose()


@pytest.mark.infra
async def test_five_arrivals_schedule_exactly_one_task(debouncer: AlbumDebouncer) -> None:
    """The collapse, stated as plainly as it can be stated."""
    scheduled = [await debouncer.touch(shop_id=SHOP, media_group_id=ALBUM) for _ in range(5)]
    assert scheduled == [True, False, False, False, False]


@pytest.mark.infra
async def test_every_arrival_pushes_the_deadline_out(debouncer: AlbumDebouncer) -> None:
    """Even the four that schedule nothing. That is how a late photo makes the
    already-scheduled task wait for it instead of parsing without it."""
    clock: StepClock = debouncer._clock  # type: ignore[assignment]

    await debouncer.touch(shop_id=SHOP, media_group_id=ALBUM)
    first = await debouncer.deadline(shop_id=SHOP, media_group_id=ALBUM)

    clock.advance(1.0)
    await debouncer.touch(shop_id=SHOP, media_group_id=ALBUM)
    second = await debouncer.deadline(shop_id=SHOP, media_group_id=ALBUM)

    assert first is not None and second is not None
    assert second == pytest.approx(first + 1.0)


@pytest.mark.infra
async def test_the_scheduled_task_defers_when_a_later_photo_moved_the_deadline(
    debouncer: AlbumDebouncer,
) -> None:
    """The two halves together: this is the album race as the task sees it."""
    clock: StepClock = debouncer._clock  # type: ignore[assignment]

    await debouncer.touch(shop_id=SHOP, media_group_id=ALBUM)  # photo 1 schedules
    clock.advance(1.0)
    await debouncer.touch(shop_id=SHOP, media_group_id=ALBUM)  # photo 2 defers it

    # The task fires when photo 1 asked it to, one second early.
    clock.advance(DEBOUNCE_SECONDS - 1.0)
    deadline = await debouncer.deadline(shop_id=SHOP, media_group_id=ALBUM)
    assert decide(deadline, clock()).action is Action.WAIT

    clock.advance(1.0)
    deadline = await debouncer.deadline(shop_id=SHOP, media_group_id=ALBUM)
    assert decide(deadline, clock()).action is Action.RUN


@pytest.mark.infra
async def test_releasing_lets_the_next_album_burst_schedule_again(
    debouncer: AlbumDebouncer,
) -> None:
    """Otherwise an edit hours later could never be settled."""
    assert await debouncer.touch(shop_id=SHOP, media_group_id=ALBUM) is True
    assert await debouncer.touch(shop_id=SHOP, media_group_id=ALBUM) is False

    await debouncer.release(shop_id=SHOP, media_group_id=ALBUM)

    assert await debouncer.deadline(shop_id=SHOP, media_group_id=ALBUM) is None
    assert await debouncer.touch(shop_id=SHOP, media_group_id=ALBUM) is True


@pytest.mark.infra
async def test_two_albums_do_not_share_a_lock(debouncer: AlbumDebouncer) -> None:
    """The key is per album. A busy shop posts several at once."""
    other = "debounce-album-other"
    try:
        assert await debouncer.touch(shop_id=SHOP, media_group_id=ALBUM) is True
        assert await debouncer.touch(shop_id=SHOP, media_group_id=other) is True
    finally:
        await debouncer.release(shop_id=SHOP, media_group_id=other)


def test_the_keys_are_namespaced_per_shop() -> None:
    """Two shops posting the same media_group_id is vanishingly unlikely and
    would be silent if it happened, which is exactly when to be explicit."""
    assert album_keys(1, ALBUM) != album_keys(2, ALBUM)
    for key in album_keys(1, ALBUM):
        assert key.startswith("gulbot:album:1:")


# --- the loop-lifetime regression ------------------------------------------


@pytest.mark.infra
def test_the_debounce_survives_a_fresh_event_loop_per_call() -> None:
    """Celery gives every task its own event loop and then CLOSES it.

    NOT an async test, deliberately, and that is the entire point. A
    `redis.asyncio` connection is bound to the loop that opened it, so a client
    cached at module level hands the SECOND task in a worker process a socket
    whose loop is dead: `RuntimeError: Event loop is closed`. Every other test
    in this repo runs inside one pytest event loop and cannot see it. This one
    calls `asyncio.run` twice, which is exactly the worker's shape.

    Found by running a real Celery worker against a real album, after the whole
    suite was green.
    """
    group = "loop-lifetime-album"

    async def one_task() -> bool:
        async with album_debouncer() as debouncer:
            return await debouncer.touch(shop_id=SHOP, media_group_id=group)

    async def cleanup() -> None:
        async with album_debouncer() as debouncer:
            await debouncer.release(shop_id=SHOP, media_group_id=group)

    try:
        first = asyncio.run(one_task())
        # The call that used to die. If it raises, the fix has regressed.
        second = asyncio.run(one_task())
    finally:
        asyncio.run(cleanup())

    assert first is True
    assert second is False, "the lock should still be held across the two loops"


@pytest.mark.infra
def test_a_second_loop_can_still_read_what_the_first_one_wrote() -> None:
    """The bot process writes the deadline; a worker process reads it. Proving
    the value crosses a loop boundary is the other half of the same claim."""
    group = "loop-lifetime-album-2"

    async def write() -> float | None:
        async with album_debouncer() as debouncer:
            await debouncer.touch(shop_id=SHOP, media_group_id=group)
            return await debouncer.deadline(shop_id=SHOP, media_group_id=group)

    async def read() -> float | None:
        async with album_debouncer() as debouncer:
            return await debouncer.deadline(shop_id=SHOP, media_group_id=group)

    async def cleanup() -> None:
        async with album_debouncer() as debouncer:
            await debouncer.release(shop_id=SHOP, media_group_id=group)

    try:
        written = asyncio.run(write())
        read_back = asyncio.run(read())
    finally:
        asyncio.run(cleanup())

    assert written is not None
    assert read_back == written
