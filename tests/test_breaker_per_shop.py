# ruff: noqa: F811, F401  -- fixtures are imported by name; pytest injects them into
# the same-named test parameters, which ruff reads as a redefinition.
"""H5 of AUDIT_MULTI_TENANT.md: one shop's outage does not stop the fleet.

THE DEFECT. Both send ticks drain an outbox that spans every shop, and each
built ONE `CircuitBreaker` per tick. Three consecutive network failures from
one shop's bot opened it, and the tick handed back every row it still held --
every OTHER shop's rows included. A shop whose bot keeps timing out delayed
everyone behind it by a full tick, every tick, for as long as it stayed broken.

THE FIX. A breaker per shop: the failing shop's remaining rows go back
untouched, and the other shops keep sending. A fleet-wide trip is kept for a
real Telegram outage, where every shop fails at once -- see `ShopBreakers`.

HOW THE OUTAGE IS SIMULATED. As in `test_audit_outage.py`: real `Bot`s from
`build_bot()`, the real `TelegramTransport`, and for the failing shop a real TCP
listener that accepts and never answers. The healthy shop talks to a real HTTP
stub. Two real shops, one tick, one rolled-back database.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import bound_session_factory
from tests.telegram_stub import FakeTelegram
from tests.test_audit_outage import Blackhole, CountingTransport, blackhole, production_bot
from tests.test_dispatcher import NOW
from tests.test_order_pings import _make_order, _ping

import gulbot.sending.transport as transport_module
from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.sending.dispatcher import run_tick
from gulbot.sending.order_card import ANNOUNCEMENT
from gulbot.sending.order_pings import run_order_ping_tick
from gulbot.sending.render import render_reminder
from gulbot.sending.telegram import TelegramTransport
from gulbot.sending.transport import BREAKER_THRESHOLD, SendResult

pytestmark = pytest.mark.infra

#: More than BREAKER_THRESHOLD, so the failing shop has rows left to hand back.
FAILING_DUE = 5
HEALTHY_DUE = 3


async def _shop(db: AsyncConnection, label: str, *, group: int) -> dict[str, int]:
    shop = (
        await db.execute(
            text(
                "INSERT INTO shops (name, working_hours, group_chat_id) "
                "VALUES (:n, CAST(:wh AS jsonb), :g) RETURNING id"
            ),
            {"n": f"Shop {label}", "wh": json.dumps(DEFAULT_WORKING_HOURS), "g": group},
        )
    ).scalar_one()
    customer = (
        await db.execute(
            text(
                "INSERT INTO customers (shop_id, telegram_user_id, phone, phone_verified) "
                "VALUES (:s, :t, '+998901234567', true) RETURNING id"
            ),
            {"s": shop, "t": 9_000 + abs(group) % 1000},
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
    return {"shop": shop, "customer": customer, "recipient": recipient}


async def _due_reminder(db: AsyncConnection, w: dict[str, int], *, day: int, due: datetime) -> None:
    occasion = (
        await db.execute(
            text(
                "INSERT INTO occasions "
                "(shop_id, customer_id, recipient_id, label, type, kind, month, day) "
                "VALUES (:s, :c, :r, 'Onam', 'mother', 'birthday', 3, :d) RETURNING id"
            ),
            {"s": w["shop"], "c": w["customer"], "r": w["recipient"], "d": day},
        )
    ).scalar_one()
    await db.execute(
        text(
            "INSERT INTO scheduled_notifications "
            "(shop_id, customer_id, occasion_id, occurrence_year, offset_days, "
            " due_at_utc, channel, merge_key) "
            "VALUES (:s, :c, :o, 2027, 0, :due, 'telegram', :mk)"
        ),
        {
            "s": w["shop"],
            "c": w["customer"],
            "o": occasion,
            "due": due,
            "mk": f"shop{w['shop']}-day{day}",
        },
    )


async def _reminders_of(db: AsyncConnection, shop: int) -> list[tuple[str, int]]:
    result = await db.execute(
        text("SELECT state, attempts FROM scheduled_notifications WHERE shop_id = :s ORDER BY id"),
        {"s": shop},
    )
    return [(r.state, r.attempts) for r in result]


async def _claims_of(db: AsyncConnection, shop: int) -> list[str]:
    result = await db.execute(
        text("SELECT status FROM message_log WHERE shop_id = :s ORDER BY id"), {"s": shop}
    )
    return list(result.scalars())


# --------------------------------------------------------------------------
# the reminder tick
# --------------------------------------------------------------------------


async def test_one_shops_outage_does_not_stop_another_shops_reminders(
    db: AsyncConnection, production_bot: Any, blackhole: Blackhole
) -> None:
    """DEFECT IF THIS FAILS. Shop A's bot gets no answer; shop B's is fine.

    A's rows are due FIRST, so under one breaker per tick A's three failures
    handed back all of B's rows. Now: A puts exactly BREAKER_THRESHOLD requests
    on the wire and hands the rest back with no attempt counted and no claim
    held; B sends every row."""
    a = await _shop(db, "A", group=-1_001_111)
    b = await _shop(db, "B", group=-1_002_222)
    for day in range(1, FAILING_DUE + 1):
        await _due_reminder(
            db, a, day=day, due=NOW - timedelta(minutes=30) + timedelta(seconds=day)
        )
    for day in range(1, HEALTHY_DUE + 1):
        await _due_reminder(db, b, day=day, due=NOW - timedelta(minutes=5) + timedelta(seconds=day))

    with FakeTelegram() as telegram:
        down = production_bot(blackhole.base_url)
        up = production_bot(telegram.base_url)
        transports = {
            a["shop"]: CountingTransport(TelegramTransport(down)),
            b["shop"]: CountingTransport(TelegramTransport(up)),
        }
        try:
            async with bound_session_factory(db)() as session:
                result = await run_tick(
                    session,
                    transport_for=transports.__getitem__,  # type: ignore[arg-type]
                    render=render_reminder,
                    now_utc=NOW,
                )
                await session.commit()
        finally:
            await down.session.close()
            await up.session.close()

    # The healthy shop: every row sent, through its own bot.
    assert telegram.calls == ["sendMessage"] * HEALTHY_DUE
    assert await _reminders_of(db, b["shop"]) == [("sent", 1)] * HEALTHY_DUE
    assert await _claims_of(db, b["shop"]) == ["sent"] * HEALTHY_DUE

    # The failing shop: three tries, then the rest handed back untouched.
    assert len(transports[a["shop"]].outcomes) == BREAKER_THRESHOLD
    assert blackhole.requests == BREAKER_THRESHOLD
    assert await _reminders_of(db, a["shop"]) == [("failed", 1)] * BREAKER_THRESHOLD + [
        ("pending", 0)
    ] * (FAILING_DUE - BREAKER_THRESHOLD)
    assert await _claims_of(db, a["shop"]) == [], "a claim was left behind"

    assert (result.sent, result.failed, result.handed_back) == (
        HEALTHY_DUE,
        BREAKER_THRESHOLD,
        FAILING_DUE - BREAKER_THRESHOLD,
    )


async def test_a_real_telegram_outage_still_ends_the_tick_quickly(
    db: AsyncConnection, production_bot: Any, blackhole: Blackhole
) -> None:
    """GUARDS THE FIX. Per-shop breakers alone would make a whole-Telegram
    outage cost BREAKER_THRESHOLD timeouts PER SHOP -- at 1000 shops, hours,
    where pass 5 of the pre-deployment audit bounded it at about 45 s.

    When FLEET_BREAKER_SHOPS different shops fail in a row with nothing
    answering in between, it is Telegram (or our network), not a shop: the tick
    stops and hands everything back. Three shops, two rows each, interleaved so
    no single shop ever reaches its own threshold."""
    shops = [await _shop(db, label, group=-1_000_000 - n) for n, label in enumerate("ABC")]
    for day in (1, 2):
        for n, w in enumerate(shops):
            due = NOW - timedelta(minutes=30) + timedelta(seconds=day * 10 + n)
            await _due_reminder(db, w, day=day, due=due)

    bot = production_bot(blackhole.base_url)
    try:
        async with bound_session_factory(db)() as session:
            result = await run_tick(
                session,
                transport_for=lambda shop_id: TelegramTransport(bot),
                render=render_reminder,
                now_utc=NOW,
            )
            await session.commit()
    finally:
        await bot.session.close()

    fleet = transport_module.FLEET_BREAKER_SHOPS
    assert fleet == 3
    assert blackhole.requests == fleet
    assert (result.failed, result.handed_back) == (fleet, 6 - fleet)
    remaining = [row for w in shops for row in await _reminders_of(db, w["shop"])]
    assert sorted(remaining) == [("failed", 1)] * 3 + [("pending", 0)] * 3


# --------------------------------------------------------------------------
# the order-ping tick
# --------------------------------------------------------------------------


async def _pings_of(db: AsyncConnection, shop: int) -> list[tuple[str, int, bool]]:
    result = await db.execute(
        text(
            "SELECT state, attempts, claimed_at IS NULL AS unclaimed FROM order_reminders "
            "WHERE shop_id = :s ORDER BY id"
        ),
        {"s": shop},
    )
    return [(r.state, r.attempts, r.unclaimed) for r in result]


async def test_one_shops_outage_does_not_stop_another_shops_order_pings(
    db: AsyncConnection, production_bot: Any, blackhole: Blackhole
) -> None:
    """DEFECT IF THIS FAILS. The same claim for the shop-facing outbox, where a
    delayed ping is a shop that does not know an order was placed."""
    a = await _shop(db, "A", group=-1_001_111)
    b = await _shop(db, "B", group=-1_002_222)
    now = datetime.now(UTC)
    for n in range(FAILING_DUE):
        order = await _make_order(db, a["shop"], a["customer"], token=f"a-{n}")
        await _ping(db, a["shop"], order, number=ANNOUNCEMENT, due=now - timedelta(minutes=30 - n))
    for n in range(HEALTHY_DUE):
        order = await _make_order(db, b["shop"], b["customer"], token=f"b-{n}")
        await _ping(db, b["shop"], order, number=ANNOUNCEMENT, due=now - timedelta(minutes=5 - n))

    with FakeTelegram() as telegram:
        down = production_bot(blackhole.base_url)
        up = production_bot(telegram.base_url)
        transports = {a["shop"]: TelegramTransport(down), b["shop"]: TelegramTransport(up)}
        try:
            async with bound_session_factory(db)() as session:
                result = await run_order_ping_tick(
                    session,
                    transport_for=transports.__getitem__,  # type: ignore[arg-type]
                    now_utc=now,
                )
        finally:
            await down.session.close()
            await up.session.close()

    assert telegram.calls == ["sendPhoto"] * HEALTHY_DUE
    assert await _pings_of(db, b["shop"]) == [("sent", 1, True)] * HEALTHY_DUE

    assert blackhole.requests == BREAKER_THRESHOLD
    assert await _pings_of(db, a["shop"]) == [("failed", 1, True)] * BREAKER_THRESHOLD + [
        ("pending", 0, True)
    ] * (FAILING_DUE - BREAKER_THRESHOLD)
    assert (result.sent, result.failed, result.handed_back) == (
        HEALTHY_DUE,
        BREAKER_THRESHOLD,
        FAILING_DUE - BREAKER_THRESHOLD,
    )


# --------------------------------------------------------------------------
# the counting rules, without a database
# --------------------------------------------------------------------------

DOWN = SendResult.unreachable("TelegramNetworkError")
UP = SendResult.sent(1)


def test_a_shop_trips_only_its_own_breaker() -> None:
    breakers = transport_module.ShopBreakers()
    for _ in range(BREAKER_THRESHOLD):
        breakers.record(1, DOWN)
    assert breakers.open_for(1)
    assert not breakers.open_for(2)
    assert not breakers.fleet_open


def test_another_shop_answering_resets_the_fleet_streak() -> None:
    """Two shops down, then a third answers: that is two broken shops, not a
    broken Telegram. The fleet stays open for business."""
    breakers = transport_module.ShopBreakers()
    breakers.record(1, DOWN)
    breakers.record(2, DOWN)
    breakers.record(3, UP)
    breakers.record(4, DOWN)
    breakers.record(5, DOWN)
    assert not breakers.fleet_open
    breakers.record(6, DOWN)
    assert breakers.fleet_open
    assert breakers.open_for(3), "a fleet trip stops every shop"


def test_one_shop_failing_many_times_is_not_a_fleet_outage() -> None:
    breakers = transport_module.ShopBreakers()
    for _ in range(10):
        breakers.record(1, DOWN)
    assert not breakers.fleet_open
