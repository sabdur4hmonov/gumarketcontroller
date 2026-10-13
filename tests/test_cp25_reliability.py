"""Deadlines, cancellation cleanup, pacing and 429 behavior without benchmarks."""

from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import GetUpdates, SendMessage

from gulbot.bot.middlewares import DbSessionMiddleware
from gulbot.bot.reliability import HandlerDeadline, PollObserver, PollProgress, ReplyPolicy


async def test_stuck_handler_is_bounded_and_session_rolls_back() -> None:
    session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())

    class Context:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            pass

    db = DbSessionMiddleware(Context)
    deadline = HandlerDeadline(17, seconds=0.01)

    async def stuck(event, data):
        await asyncio.Event().wait()

    async def wrapped(event, data):
        return await db(stuck, event, data)

    returned = False
    try:
        await asyncio.wait_for(deadline(wrapped, None, {}), timeout=0.2)
        returned = True
    except TimeoutError:
        pass
    assert returned, "The shop deadline must finish before the outer harness deadline"
    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()


async def test_429_waits_then_retries_only_the_same_request() -> None:
    now = [0.0]
    sleeps = []

    async def sleep(delay):
        now[0] += delay
        sleeps.append(delay)

    policy = ReplyPolicy(clock=lambda: now[0], sleep=sleep)
    method = SendMessage(chat_id=1, text="fixture")
    request = AsyncMock(
        side_effect=[TelegramRetryAfter(method=method, message="fixture", retry_after=1), True]
    )
    accepted = False
    with contextlib.suppress(TelegramRetryAfter):
        accepted = await policy(request, SimpleNamespace(id=7), method)
    assert accepted is True, "A reply must recover from Telegram 429"
    assert request.await_count == 2 and sum(sleeps) >= 1


async def test_replies_in_one_chat_are_paced_without_delaying_another_bot() -> None:
    now = [0.0]

    async def sleep(delay):
        now[0] += delay

    policy = ReplyPolicy(clock=lambda: now[0], sleep=sleep)
    request = AsyncMock(return_value=True)
    method = SendMessage(chat_id=1, text="fixture")
    await policy(request, SimpleNamespace(id=7), method)
    await policy(request, SimpleNamespace(id=7), method)
    assert now[0] >= 1, "Pace sequential replies in the same bot/chat"
    previous = now[0]
    await policy(request, SimpleNamespace(id=8), method)
    assert now[0] == previous, "Rate buckets must be per bot"


async def test_permanent_429_is_bounded() -> None:
    now = [0.0]

    async def sleep(delay):
        now[0] += delay

    policy = ReplyPolicy(clock=lambda: now[0], sleep=sleep)
    method = SendMessage(chat_id=1, text="fixture")
    request = AsyncMock(
        side_effect=TelegramRetryAfter(method=method, message="fixture", retry_after=1)
    )
    with contextlib.suppress(TelegramRetryAfter):
        await policy(request, SimpleNamespace(id=7), method)
    assert 1 < request.await_count <= 3, "Retry replies, but never retry forever"


async def test_poll_failure_and_recovery_update_progress_without_reply_noise() -> None:
    progress = PollProgress(last_progress=0)
    observer = PollObserver(progress)
    request = AsyncMock(side_effect=RuntimeError("fixture"))
    with contextlib.suppress(RuntimeError):
        await observer(request, SimpleNamespace(id=7), GetUpdates())
    assert progress.consecutive_failures == 1 and progress.last_progress > 0
    request = AsyncMock(return_value=[])
    await observer(request, SimpleNamespace(id=7), GetUpdates())
    assert progress.consecutive_failures == 0


def test_handler_p95_uses_the_same_interpolated_quantile_as_capacity() -> None:
    deadline = HandlerDeadline(17)
    deadline.samples.extend(range(1, 21))
    assert deadline.snapshot()["p95_ms"] == pytest.approx(19.05)
