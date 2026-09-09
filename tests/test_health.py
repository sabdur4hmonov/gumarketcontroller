"""Knowing when sending has stopped.

Built because nothing told anyone. Reminders could stop going out, the channel
indexer could stop receiving, a ping could exhaust its retries -- and the only
evidence was a log line nobody was reading. Three weeks before a launch that is
the gap worth closing first, because every other gap is visible to whoever is
watching and this one is visible to no one.

WHAT IT CANNOT DO, asserted here so nobody mistakes it for more than it is: all
of this runs inside the Celery worker, so a dead worker produces silence rather
than an alarm. The daily summary's ABSENCE is the signal in that case. A real
watchdog lives outside the process and needs an external service.

The two signals are tested apart because they mean different things: the
summary must arrive on a perfectly healthy day, and the alert must NOT.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import bound_session_factory

from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.sending.alerts import (
    KIND_PARKED,
    KIND_STALLED,
    check_and_alert,
    render_parked,
    render_stalled,
    render_summary,
    send_daily_summary,
)
from gulbot.sending.health import (
    ALERT_COOLDOWN,
    STALL_AFTER,
    DailyTotals,
    Health,
    read_daily_totals,
    read_health,
    tashkent_day_start,
)
from gulbot.sending.transport import SendResult

# --------------------------------------------------------------------------
# the wording and the day boundary: pure
# --------------------------------------------------------------------------


def test_a_clean_day_is_one_short_line() -> None:
    """Read at a glance every day. Anything longer stops being read."""
    body = render_summary(
        DailyTotals(reminders_sent=12, orders_placed=3, parked_reminders=0, parked_pings=0)
    )
    assert "12" in body and "3" in body
    assert "\n" not in body


def test_a_day_with_something_parked_says_so() -> None:
    body = render_summary(
        DailyTotals(reminders_sent=12, orders_placed=3, parked_reminders=1, parked_pings=2)
    )
    assert "3" in body
    assert "\n" in body, "the warning is a second line, not buried in the first"


def test_the_alarm_names_what_is_stuck_and_for_how_long() -> None:
    """ "Something is wrong" is not something a shop can act on."""
    body = render_stalled(
        Health(overdue_reminders=4, overdue_pings=1, parked_reminders=0, parked_pings=0)
    )
    assert "5" in body
    assert str(int(STALL_AFTER.total_seconds() // 60)) in body


def test_the_parked_alarm_counts_both_outboxes() -> None:
    body = render_parked(
        Health(overdue_reminders=0, overdue_pings=0, parked_reminders=2, parked_pings=3)
    )
    assert "5" in body


@pytest.mark.parametrize(
    ("utc", "expected_local_date"),
    [
        # 21:00 Tashkent is 16:00 UTC. A summary at that hour counting a UTC day
        # would drop the whole evening -- which is when a flower shop is busiest.
        (datetime(2026, 9, 7, 16, 0, tzinfo=UTC), "2026-09-07"),
        # 00:30 Tashkent on the 8th is 19:30 UTC on the 7th.
        (datetime(2026, 9, 7, 19, 30, tzinfo=UTC), "2026-09-08"),
    ],
)
def test_the_day_starts_at_tashkent_midnight(utc: datetime, expected_local_date: str) -> None:
    from gulbot.scheduling.occurrences import TASHKENT

    start = tashkent_day_start(utc)
    local = start.astimezone(TASHKENT)
    assert local.strftime("%Y-%m-%d") == expected_local_date
    assert (local.hour, local.minute) == (0, 0)


# --------------------------------------------------------------------------
# the counting, against real rows
# --------------------------------------------------------------------------

pytestmark = pytest.mark.infra

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


class FakeTransport:
    def __init__(self, ok: bool = True) -> None:
        self.texts: list[dict] = []
        self.ok = ok

    async def send_text(
        self, *, chat_id: int, text: str, reply_markup: object = None
    ) -> SendResult:
        self.texts.append({"chat_id": chat_id, "text": text})
        return SendResult.sent(1) if self.ok else SendResult.failed("boom")

    async def send_photo(self, **kwargs: object) -> SendResult:  # pragma: no cover
        raise AssertionError("health messages are text, never photos")


@pytest_asyncio.fixture
async def world(db: AsyncConnection) -> dict:
    shop = (
        await db.execute(
            text(
                "INSERT INTO shops (name, working_hours, group_chat_id) "
                "VALUES ('S', CAST(:wh AS jsonb), -1009999) RETURNING id"
            ),
            {"wh": json.dumps(DEFAULT_WORKING_HOURS)},
        )
    ).scalar_one()
    customer = (
        await db.execute(
            text(
                "INSERT INTO customers (shop_id, telegram_user_id) VALUES (:s, 8801) RETURNING id"
            ),
            {"s": shop},
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
    return {"db": db, "shop": shop, "customer": customer, "recipient": recipient, "day": 1}


async def add_reminder(
    world: dict, *, due: datetime, state: str, sent_at: datetime | None = None
) -> None:
    """One scheduled reminder in a given state. Each gets its own occasion,
    because the unique key is per (occasion, year, offset, channel)."""
    world["day"] += 1
    occasion = (
        await world["db"].execute(
            text(
                "INSERT INTO occasions (shop_id, customer_id, recipient_id, label, type, kind, "
                " month, day) VALUES (:s, :c, :r, 'Onam', 'mother', 'birthday', 3, :d) RETURNING id"
            ),
            {
                "s": world["shop"],
                "c": world["customer"],
                "r": world["recipient"],
                "d": world["day"],
            },
        )
    ).scalar_one()
    await world["db"].execute(
        text(
            "INSERT INTO scheduled_notifications (shop_id, customer_id, occasion_id, "
            " occurrence_year, offset_days, due_at_utc, channel, state, sent_at) "
            "VALUES (:s, :c, :o, 2027, 0, :due, 'telegram', :st, :sent)"
        ),
        {
            "s": world["shop"],
            "c": world["customer"],
            "o": occasion,
            "due": due,
            "st": state,
            "sent": sent_at,
        },
    )


async def health_of(world: dict, now: datetime = NOW) -> Health:
    async with bound_session_factory(world["db"])() as session:
        return await read_health(session, shop_id=world["shop"], now_utc=now)


async def test_a_quiet_healthy_outbox_reports_nothing(world: dict) -> None:
    assert await health_of(world) == Health(0, 0, 0, 0)


async def test_a_reminder_due_a_minute_ago_is_not_a_stall(world: dict) -> None:
    """A row a minute late is a tick that has not run yet. Alerting on that
    would cry wolf once a minute forever."""
    await add_reminder(world, due=NOW - timedelta(minutes=1), state="pending")
    assert (await health_of(world)).stalled is False


async def test_a_reminder_overdue_past_the_threshold_is_a_stall(world: dict) -> None:
    await add_reminder(world, due=NOW - STALL_AFTER - timedelta(minutes=1), state="pending")
    health = await health_of(world)
    assert health.overdue_reminders == 1
    assert health.stalled is True


async def test_the_threshold_boundary_is_not_off_by_one(world: dict) -> None:
    """Exactly at the threshold counts, one second inside it does not."""
    await add_reminder(world, due=NOW - STALL_AFTER, state="pending")
    assert (await health_of(world)).overdue_reminders == 1


async def test_a_sent_reminder_is_never_a_stall(world: dict) -> None:
    """Guards the guard: a query that ignored `state` would report every
    reminder the shop ever sent as overdue."""
    await add_reminder(
        world, due=NOW - timedelta(days=30), state="sent", sent_at=NOW - timedelta(days=30)
    )
    assert (await health_of(world)).stalled is False


async def test_a_parked_reminder_is_counted_separately(world: dict) -> None:
    """Dead-lettered is a different problem from overdue: it will never be sent
    at all, so it needs its own alert rather than sitting in the stall count."""
    await add_reminder(world, due=NOW - timedelta(days=1), state="dead_letter")
    health = await health_of(world)
    assert health.parked_reminders == 1
    assert health.stalled is False
    assert health.parked is True


async def test_another_shops_backlog_is_not_this_shops_problem(world: dict) -> None:
    """Every query is shop-scoped. It matters now for correctness and later for
    multi-tenancy."""
    other = (
        await world["db"].execute(
            text(
                "INSERT INTO shops (name, working_hours) "
                "VALUES ('other', CAST(:wh AS jsonb)) RETURNING id"
            ),
            {"wh": json.dumps(DEFAULT_WORKING_HOURS)},
        )
    ).scalar_one()
    theirs = dict(world, shop=other)
    theirs["customer"] = (
        await world["db"].execute(
            text(
                "INSERT INTO customers (shop_id, telegram_user_id) VALUES (:s, 8802) RETURNING id"
            ),
            {"s": other},
        )
    ).scalar_one()
    theirs["recipient"] = (
        await world["db"].execute(
            text(
                "INSERT INTO recipients (shop_id, customer_id, label, type) "
                "VALUES (:s, :c, 'Onam', 'mother') RETURNING id"
            ),
            {"s": other, "c": theirs["customer"]},
        )
    ).scalar_one()
    await add_reminder(theirs, due=NOW - timedelta(hours=2), state="pending")

    assert (await health_of(world)).stalled is False


async def test_the_daily_total_counts_todays_sends_only(world: dict) -> None:
    await add_reminder(world, due=NOW, state="sent", sent_at=NOW - timedelta(minutes=5))
    await add_reminder(world, due=NOW, state="sent", sent_at=NOW - timedelta(days=2))
    async with bound_session_factory(world["db"])() as session:
        totals = await read_daily_totals(session, shop_id=world["shop"], now_utc=NOW)
    assert totals.reminders_sent == 1


# --------------------------------------------------------------------------
# announcing
# --------------------------------------------------------------------------


async def test_the_summary_goes_to_the_group(world: dict) -> None:
    transport = FakeTransport()
    async with bound_session_factory(world["db"])() as session:
        assert await send_daily_summary(
            session, transport=transport, shop_id=world["shop"], now_utc=NOW
        )
    assert transport.texts[0]["chat_id"] == -1009999


async def test_a_healthy_shop_gets_no_alert(world: dict) -> None:
    """The most important negative in this file. An alert that fires on a good
    day teaches the shop to ignore alerts."""
    transport = FakeTransport()
    async with bound_session_factory(world["db"])() as session:
        assert (
            await check_and_alert(session, transport=transport, shop_id=world["shop"], now_utc=NOW)
            == []
        )
    assert transport.texts == []


@pytest.mark.parametrize(
    ("state", "expected"),
    [("pending", KIND_STALLED), ("dead_letter", KIND_PARKED)],
)
async def test_trouble_is_announced_once(world: dict, state: str, expected: str) -> None:
    """WOULD FAIL without the cooldown. The check runs every five minutes; an
    alert that repeated every run is one nobody reads."""
    await add_reminder(world, due=NOW - timedelta(hours=2), state=state)
    transport = FakeTransport()
    factory = bound_session_factory(world["db"])

    async with factory() as session:
        first = await check_and_alert(
            session, transport=transport, shop_id=world["shop"], now_utc=NOW
        )
    async with factory() as session:
        second = await check_and_alert(
            session, transport=transport, shop_id=world["shop"], now_utc=NOW
        )

    assert first == [expected]
    assert second == [], "the second check must stay quiet"
    assert len(transport.texts) == 1


async def test_the_cooldown_is_long_enough_to_be_worth_having() -> None:
    """Guards the constant. A cooldown of seconds would make the test above
    pass while the shop still got spammed."""
    assert ALERT_COOLDOWN.total_seconds() >= 1800


async def test_a_shop_with_nowhere_to_send_does_not_crash(world: dict) -> None:
    """The health check must be the most robust thing in the system: it is what
    runs when everything else is broken."""
    await world["db"].execute(
        text("UPDATE shops SET group_chat_id = NULL WHERE id = :s"), {"s": world["shop"]}
    )
    await add_reminder(world, due=NOW - timedelta(hours=2), state="pending")
    transport = FakeTransport()
    async with bound_session_factory(world["db"])() as session:
        announced = await check_and_alert(
            session, transport=transport, shop_id=world["shop"], now_utc=NOW
        )
    assert announced == [KIND_STALLED]
    assert transport.texts == []


async def test_a_failing_telegram_does_not_crash_the_check(world: dict) -> None:
    transport = FakeTransport(ok=False)
    async with bound_session_factory(world["db"])() as session:
        assert (
            await send_daily_summary(
                session, transport=transport, shop_id=world["shop"], now_utc=NOW
            )
            is False
        )
