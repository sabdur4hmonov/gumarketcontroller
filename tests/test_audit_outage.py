# ruff: noqa: F811, F401  -- fixtures are imported by name; pytest injects them into
# the same-named test parameters, which ruff reads as a redefinition.
"""PASS 5: what a Telegram OUTAGE does to a tick -- not a 429, not a 403.

In a real outage nothing answers, so every send waits out aiogram's request
timeout (60 s) and then raises TelegramNetworkError, a TelegramAPIError subclass
that `TelegramTransport._attempt` turns into SendResult.failed. So the tick does
not crash and does not error-loop -- each failure is handled.

The question is how LONG a tick takes, because the worker runs `--pool=solo`:
one task at a time, so everything behind a slow tick waits, including the
five-minute health check that exists to say sending has stopped.

Telegram's 60 s is scaled down to SLOW here; the tick's duration is measured, and
the report extrapolates with the real numbers.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from tests.bot_harness import bound_session_factory
from tests.test_order_pings import _make_order, _ping, world

from gulbot.sending.order_card import ANNOUNCEMENT
from gulbot.sending.order_pings import BATCH_SIZE, run_order_ping_tick
from gulbot.sending.transport import SendResult

pytestmark = pytest.mark.infra

SLOW = 0.5  # stands in for aiogram's 60-second request timeout
ORDERS = 5


class OutageTransport:
    """Nothing answers: every send waits, then fails the way the real transport
    reports a TelegramNetworkError."""

    def __init__(self) -> None:
        self.calls = 0

    async def _outage(self) -> SendResult:
        self.calls += 1
        await asyncio.sleep(SLOW)
        return SendResult.failed("TelegramNetworkError")

    async def send_photo(self, **kw: object) -> SendResult:
        return await self._outage()

    async def send_text(self, **kw: object) -> SendResult:
        return await self._outage()


async def test_an_outage_makes_one_tick_last_every_row_times_the_timeout(world: dict) -> None:
    """MEASUREMENT. The tick handles each failure -- no crash, no retry loop
    inside the tick -- but it attempts EVERY due row, each waiting out the
    timeout, one after another."""
    db, shop, customer = world["db"], world["shop"], world["customer"]
    await _ping(db, shop, world["order"], number=ANNOUNCEMENT)
    for n in range(ORDERS - 1):
        order = await _make_order(db, shop, customer, token=f"outage-{n}")
        await _ping(db, shop, order, number=ANNOUNCEMENT)

    transport = OutageTransport()
    started = time.monotonic()
    async with bound_session_factory(db)() as session:
        result = await run_order_ping_tick(session, transport=transport, now_utc=datetime.now(UTC))
    took = time.monotonic() - started

    print(
        f"\n  {ORDERS} due pings, {SLOW}s per send -> tick took {took:.1f}s"
        f"\n  real numbers: BATCH_SIZE={BATCH_SIZE} x 60s timeout = up to "
        f"{BATCH_SIZE * 60 / 60:.0f} minutes for ONE tick, on a solo worker"
    )
    assert transport.calls == ORDERS, "every due row was attempted"
    assert took >= ORDERS * SLOW * 0.9, "the sends ran one after another"
    assert result.failed == ORDERS


async def test_an_outage_loses_nothing(world: dict) -> None:
    """CONFIRMATION IF THIS PASSES. After an outage tick every ping is FAILED
    with one attempt, which the ping tick treats as sendable -- so it is retried
    once Telegram is back, and parks in dead_letter (and alerts) only after
    MAX_PING_ATTEMPTS. Nothing is dropped; nothing piles up inside the database."""
    db, shop = world["db"], world["shop"]
    await _ping(db, shop, world["order"], number=ANNOUNCEMENT)

    async with bound_session_factory(db)() as session:
        await run_order_ping_tick(session, transport=OutageTransport(), now_utc=datetime.now(UTC))

    state, attempts = (
        await db.execute(
            text("SELECT state, attempts FROM order_reminders WHERE order_id = :o"),
            {"o": world["order"]},
        )
    ).one()
    assert (state, attempts) == ("failed", 1)
