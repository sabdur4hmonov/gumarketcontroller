"""Pacing, and honouring Telegram's own 429.

Two different mechanisms, deliberately kept apart:

* the token bucket is OUR pacing, so we stay under the published ceilings;
* `retry_after` is TELEGRAM'S instruction, and is obeyed to the second.

Both use an injected clock, so these assert actual waits rather than watching
the wall clock.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker
from tests.bot_harness import bound_session_factory
from tests.test_dispatcher import NOW, FakeTransport, add_due_row, rows, tick

from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.sending.rate_limit import (
    GLOBAL_RATE_PER_SECOND,
    PER_CHAT_RATE_PER_SECOND,
    RateLimiter,
    TokenBucket,
)
from gulbot.sending.transport import SendResult


class FakeClock:
    """A clock the test drives. Sleeping advances it, as a real one would."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


# --- the buckets -----------------------------------------------------------


def test_a_fresh_bucket_admits_immediately() -> None:
    bucket = TokenBucket(rate=1.0, burst=1.0)
    assert bucket.wait_time(0.0) == 0.0


def test_a_spent_bucket_makes_you_wait_for_a_whole_token() -> None:
    bucket = TokenBucket(rate=1.0, burst=1.0)
    bucket.consume(0.0)
    assert bucket.wait_time(0.0) == pytest.approx(1.0)
    assert bucket.wait_time(0.5) == pytest.approx(0.5)
    assert bucket.wait_time(1.0) == 0.0


def test_a_bucket_refills_no_further_than_its_burst() -> None:
    bucket = TokenBucket(rate=1.0, burst=1.0)
    bucket.consume(0.0)
    bucket.consume(100.0)  # a long idle period must not bank 100 tokens
    assert bucket.wait_time(100.0) == pytest.approx(1.0)


# --- the limiter -----------------------------------------------------------


async def test_the_first_send_to_a_chat_does_not_wait() -> None:
    clock = FakeClock()
    limiter = RateLimiter(clock=clock, sleeper=clock.sleep)
    assert await limiter.acquire(chat_id=1, shop_id=1) == 0.0
    assert clock.sleeps == []


async def test_a_second_send_to_the_same_chat_waits_a_second() -> None:
    """~1 message/second per chat is Telegram's published per-chat ceiling."""
    clock = FakeClock()
    limiter = RateLimiter(clock=clock, sleeper=clock.sleep)
    await limiter.acquire(chat_id=1, shop_id=1)
    waited = await limiter.acquire(chat_id=1, shop_id=1)
    assert waited == pytest.approx(1.0 / PER_CHAT_RATE_PER_SECOND, rel=1e-3)


async def test_different_chats_do_not_wait_on_each_other() -> None:
    """The per-chat limit is per chat; only the bot's global bucket is shared."""
    clock = FakeClock()
    limiter = RateLimiter(clock=clock, sleeper=clock.sleep)
    for chat_id in range(1, 11):
        assert await limiter.acquire(chat_id=chat_id, shop_id=1) == 0.0


async def test_the_global_ceiling_eventually_paces_a_burst() -> None:
    clock = FakeClock()
    limiter = RateLimiter(clock=clock, sleeper=clock.sleep)
    for chat_id in range(1, int(GLOBAL_RATE_PER_SECOND) + 1):
        await limiter.acquire(chat_id=chat_id, shop_id=1)

    # The global burst is spent; the next distinct chat must wait for a refill.
    waited = await limiter.acquire(chat_id=9999, shop_id=1)
    assert waited > 0.0
    assert waited == pytest.approx(1.0 / GLOBAL_RATE_PER_SECOND, rel=1e-2)


async def test_waiting_is_bounded_and_terminates() -> None:
    clock = FakeClock()
    limiter = RateLimiter(clock=clock, sleeper=clock.sleep)
    for _ in range(5):
        await limiter.acquire(chat_id=1, shop_id=1)
    assert clock.now == pytest.approx(4.0, rel=1e-3)


# --- Telegram's 429 --------------------------------------------------------


@pytest_asyncio.fixture
async def sessions(db: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    return bound_session_factory(db)


@pytest_asyncio.fixture
async def world(db: AsyncConnection) -> dict:
    shop_id = (
        await db.execute(
            text(
                "INSERT INTO shops (name, working_hours) "
                "VALUES ('S', CAST(:wh AS jsonb)) RETURNING id"
            ),
            {"wh": json.dumps(DEFAULT_WORKING_HOURS)},
        )
    ).scalar_one()
    customer_id = (
        await db.execute(
            text(
                "INSERT INTO customers (shop_id, telegram_user_id) VALUES (:s, 6501) RETURNING id"
            ),
            {"s": shop_id},
        )
    ).scalar_one()
    recipient_id = (
        await db.execute(
            text(
                "INSERT INTO recipients (shop_id, customer_id, label, type) "
                "VALUES (:s, :c, 'Onam', 'mother') RETURNING id"
            ),
            {"s": shop_id, "c": customer_id},
        )
    ).scalar_one()
    return {"shop_id": shop_id, "customer_id": customer_id, "recipient_id": recipient_id}


@pytest.mark.infra
@pytest.mark.parametrize("retry_after", [3.0, 17.0, 42.0])
async def test_retry_after_is_honoured_to_the_second(
    db: AsyncConnection,
    world: dict,
    sessions: async_sessionmaker[AsyncSession],
    retry_after: float,
) -> None:
    """Telegram stated the wait; the row moves by exactly that, not a guess."""
    await add_due_row(db, world, merge_key="cluster-1")

    result = await tick(sessions, FakeTransport(SendResult.rate_limited(retry_after)))
    assert result.rate_limited == 1

    due = (await rows(db))[0]
    deferred = (
        await db.execute(text("SELECT due_at_utc FROM scheduled_notifications LIMIT 1"))
    ).scalar_one()
    assert deferred == NOW + timedelta(seconds=retry_after)
    assert due["state"] == "pending"


@pytest.mark.infra
async def test_a_rate_limited_row_is_not_retried_before_its_deferral(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await add_due_row(db, world, merge_key="cluster-1")
    await tick(sessions, FakeTransport(SendResult.rate_limited(30.0)))

    early = FakeTransport()
    await tick(sessions, early, now=NOW + timedelta(seconds=29))
    assert early.calls == [], "sent before Telegram said we could"

    on_time = FakeTransport()
    await tick(sessions, on_time, now=NOW + timedelta(seconds=31))
    assert len(on_time.calls) == 1


@pytest.mark.infra
async def test_a_429_does_not_burn_the_attempt_budget_silently(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """It does count -- a permanently throttled row must not retry forever."""
    await add_due_row(db, world, merge_key="cluster-1")
    await tick(sessions, FakeTransport(SendResult.rate_limited(1.0)))
    assert (await rows(db))[0]["attempts"] == 1


@pytest.mark.infra
async def test_the_tick_paces_sends_through_the_limiter(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Two messages to the SAME chat in one tick must be a second apart."""
    await add_due_row(db, world, day=8, merge_key="a")
    await add_due_row(db, world, day=20, merge_key="b")

    clock = FakeClock()
    limiter = RateLimiter(clock=clock, sleeper=clock.sleep)
    transport = FakeTransport()
    result = await tick(sessions, transport, limiter=limiter)

    assert len(transport.calls) == 2
    assert result.waited_seconds == pytest.approx(1.0, rel=1e-3)
