"""H4 of AUDIT_MULTI_TENANT.md: Telegram's ceilings are per BOT, so ours are too.

THE DEFECT. `RateLimiter` held ONE global bucket -- "~30 messages/second across
the whole bot" -- and the worker builds one limiter per tick. Since CP-MT that
tick sends for every shop, each through its own bot, so the whole fleet shared
one bot's 28 msg/s: at 1000 shops, about 0.03 msg/s each, and the evening send
window would not clear. The per-chat bucket had the same shape: a person who is
a customer of two shops was paced as one chat, though each shop's bot is a
separate sender to Telegram.

THE FIX. Both buckets are keyed by the shop, whose bot is the sender: a global
bucket per shop, and a per-chat bucket per (shop, chat). One shop is still held
to its own bot's ceiling -- that half is asserted here too, so the fix cannot
pass by simply removing the limit.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import bound_session_factory
from tests.test_dispatcher import NOW, FakeTransport
from tests.test_rate_limit import FakeClock

from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.sending.dispatcher import run_tick
from gulbot.sending.rate_limit import GLOBAL_BURST, GLOBAL_RATE_PER_SECOND, RateLimiter
from gulbot.sending.render import render_reminder

#: One more than a single bot's burst, split across two shops. Under one shared
#: bucket the last send waits; under one bucket per bot nobody does.
PER_SHOP = int(GLOBAL_BURST) // 2 + 1


async def _shop(db: AsyncConnection, name: str) -> int:
    return int(
        (
            await db.execute(
                text(
                    "INSERT INTO shops (name, working_hours) "
                    "VALUES (:n, CAST(:wh AS jsonb)) RETURNING id"
                ),
                {"n": name, "wh": json.dumps(DEFAULT_WORKING_HOURS)},
            )
        ).scalar_one()
    )


async def _due_reminder_for(db: AsyncConnection, shop: int, telegram_user_id: int) -> None:
    """A new customer of `shop`, with one reminder due now."""
    customer = (
        await db.execute(
            text("INSERT INTO customers (shop_id, telegram_user_id) VALUES (:s, :t) RETURNING id"),
            {"s": shop, "t": telegram_user_id},
        )
    ).scalar_one()
    recipient = (
        await db.execute(
            text(
                "INSERT INTO recipients (shop_id, customer_id, label, type) "
                "VALUES (:s, :c, 'Onam', 'mother') RETURNING id"
            ),
            {"s": shop, "c": customer},
        )
    ).scalar_one()
    occasion = (
        await db.execute(
            text(
                "INSERT INTO occasions "
                "(shop_id, customer_id, recipient_id, label, type, kind, month, day) "
                "VALUES (:s, :c, :r, 'Onam', 'mother', 'birthday', 3, 8) RETURNING id"
            ),
            {"s": shop, "c": customer, "r": recipient},
        )
    ).scalar_one()
    await db.execute(
        text(
            "INSERT INTO scheduled_notifications "
            "(shop_id, customer_id, occasion_id, occurrence_year, offset_days, "
            " due_at_utc, channel) "
            "VALUES (:s, :c, :o, 2027, 0, :due, 'telegram')"
        ),
        {"s": shop, "c": customer, "o": occasion, "due": NOW - timedelta(minutes=1)},
    )


async def _tick(db: AsyncConnection, limiter: RateLimiter) -> tuple[int, float]:
    transport = FakeTransport()
    async with bound_session_factory(db)() as session:
        result = await run_tick(
            session, transport=transport, render=render_reminder, now_utc=NOW, limiter=limiter
        )
        await session.commit()
    return len(transport.calls), result.waited_seconds


# --- through the real tick -------------------------------------------------


@pytest.mark.infra
async def test_two_shops_do_not_share_one_bots_budget(db: AsyncConnection) -> None:
    """DEFECT IF THIS FAILS. 2 x PER_SHOP sends is more than one bot's burst
    and well inside two bots'. Nobody should wait."""
    for n, name in enumerate(("A", "B")):
        shop = await _shop(db, name)
        for k in range(PER_SHOP):
            await _due_reminder_for(db, shop, 10_000 * (n + 1) + k)

    clock = FakeClock()
    sent, waited = await _tick(db, RateLimiter(clock=clock, sleeper=clock.sleep))

    assert sent == 2 * PER_SHOP > GLOBAL_BURST
    assert clock.sleeps == [], "one shop's sends were paced by another shop's"
    assert waited == 0.0


@pytest.mark.infra
async def test_one_shop_is_still_held_to_its_own_bots_ceiling(db: AsyncConnection) -> None:
    """GUARDS THE FIX. The same number of sends from ONE shop must still wait:
    the bucket moved, it did not go away."""
    shop = await _shop(db, "A")
    for k in range(2 * PER_SHOP):
        await _due_reminder_for(db, shop, 10_000 + k)

    clock = FakeClock()
    sent, waited = await _tick(db, RateLimiter(clock=clock, sleeper=clock.sleep))

    overflow = 2 * PER_SHOP - int(GLOBAL_BURST)
    assert sent == 2 * PER_SHOP
    assert waited == pytest.approx(overflow / GLOBAL_RATE_PER_SECOND, rel=1e-3)


@pytest.mark.infra
async def test_one_person_in_two_shops_is_two_chats(db: AsyncConnection) -> None:
    """DEFECT IF THIS FAILS. The same Telegram user is a customer of shop A and
    of shop B, and each shop's reminder is due. Two different bots, so two
    different senders to Telegram: the second must not wait out a per-chat
    second that belongs to the first bot."""
    for name in ("A", "B"):
        await _due_reminder_for(db, await _shop(db, name), 777_777)

    clock = FakeClock()
    sent, waited = await _tick(db, RateLimiter(clock=clock, sleeper=clock.sleep))

    assert sent == 2
    assert waited == 0.0


# --- the limiter alone -----------------------------------------------------


async def test_a_spent_bot_does_not_hold_up_another_bot() -> None:
    clock = FakeClock()
    limiter = RateLimiter(clock=clock, sleeper=clock.sleep)
    for chat_id in range(1, int(GLOBAL_BURST) + 1):
        await limiter.acquire(chat_id, shop_id=1)
    assert await limiter.acquire(999, shop_id=2) == 0.0
    assert await limiter.acquire(999, shop_id=1) == pytest.approx(1.0 / GLOBAL_RATE_PER_SECOND)
