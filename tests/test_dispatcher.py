"""The beat tick: grouping, idempotency, failure handling."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker
from tests.bot_harness import bound_session_factory

from gulbot.models.message_log import CLAIM_TIMEOUT, MessageStatus
from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.sending.dispatcher import MAX_SEND_ATTEMPTS, run_tick, transition_key_for
from gulbot.sending.render import render_reminder
from gulbot.sending.transport import SendResult

NOW = datetime(2027, 3, 8, 6, 0, tzinfo=UTC)  # 11:00 Tashkent, inside the window


class FakeTransport:
    """Records calls instead of making them. Scripted outcomes per call."""

    def __init__(self, *outcomes: SendResult) -> None:
        self.calls: list[dict] = []
        self._outcomes = list(outcomes)
        self.default = SendResult.sent(1)

    async def send_text(self, *, chat_id: int, text: str) -> SendResult:
        self.calls.append({"chat_id": chat_id, "text": text})
        if self._outcomes:
            return self._outcomes.pop(0)
        return self.default


class ExplodingTransport:
    """Telegram accepts the message, then our process dies before committing."""

    def __init__(self, boom: bool = True) -> None:
        self.calls: list[dict] = []
        self.boom = boom

    async def send_text(self, *, chat_id: int, text: str) -> SendResult:
        self.calls.append({"chat_id": chat_id, "text": text})
        if self.boom:
            raise RuntimeError("process died after Telegram accepted")
        return SendResult.sent(1)


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
                "INSERT INTO customers (shop_id, telegram_user_id) VALUES (:s, 6001) RETURNING id"
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


async def add_due_row(
    db: AsyncConnection,
    world: dict,
    *,
    month: int = 3,
    day: int = 8,
    offset: int = 0,
    merge_key: str | None = None,
    due: datetime | None = None,
    recipient_id: int | None = None,
) -> int:
    recipient = recipient_id or world["recipient_id"]
    occasion_id = (
        await db.execute(
            text(
                "INSERT INTO occasions "
                "(shop_id, customer_id, recipient_id, label, type, month, day) "
                "VALUES (:s, :c, :r, 'Onam', 'mother', :m, :d) RETURNING id"
            ),
            {
                "s": world["shop_id"],
                "c": world["customer_id"],
                "r": recipient,
                "m": month,
                "d": day,
            },
        )
    ).scalar_one()
    await db.execute(
        text(
            "INSERT INTO scheduled_notifications "
            "(shop_id, customer_id, occasion_id, occurrence_year, offset_days, "
            " due_at_utc, channel, merge_key) "
            "VALUES (:s, :c, :o, 2027, :off, :due, 'telegram', :mk)"
        ),
        {
            "s": world["shop_id"],
            "c": world["customer_id"],
            "o": occasion_id,
            "off": offset,
            "due": due or (NOW - timedelta(minutes=1)),
            "mk": merge_key,
        },
    )
    return int(occasion_id)


async def rows(db: AsyncConnection) -> list[dict]:
    result = (
        await db.execute(
            text(
                "SELECT id, occasion_id, offset_days, state, sent_at, attempts, merge_key "
                "FROM scheduled_notifications ORDER BY id"
            )
        )
    ).mappings()
    return [dict(r) for r in result]


async def ledger(db: AsyncConnection) -> list[dict]:
    result = (
        await db.execute(
            text(
                "SELECT transition_key, status, error_code, attempts, resolved_at "
                "FROM message_log ORDER BY id"
            )
        )
    ).mappings()
    return [dict(r) for r in result]


async def tick(
    sessions: async_sessionmaker[AsyncSession],
    transport: object,
    *,
    now: datetime = NOW,
    limiter: object | None = None,
    limit: int = 100,
):
    async with sessions() as session:
        result = await run_tick(
            session,
            transport=transport,  # type: ignore[arg-type]
            render=render_reminder,
            now_utc=now,
            limit=limit,
            limiter=limiter,  # type: ignore[arg-type]
        )
        await session.commit()
    return result


# --- grouping --------------------------------------------------------------


@pytest.mark.infra
async def test_a_merged_group_sends_one_message_not_three(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    for day, offset in ((8, 0), (9, -1), (10, -2)):
        await add_due_row(db, world, day=day, offset=offset, merge_key="cluster-1")

    transport = FakeTransport()
    result = await tick(sessions, transport)

    assert len(transport.calls) == 1, "a merged cluster sent more than one message"
    assert result.sent == 1
    assert result.groups == 1
    assert all(r["state"] == "sent" for r in await rows(db))


@pytest.mark.infra
async def test_rows_without_a_merge_key_send_individually(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await add_due_row(db, world, day=8, offset=0, merge_key=None)
    await add_due_row(db, world, day=20, offset=0, merge_key=None)

    transport = FakeTransport()
    result = await tick(sessions, transport)

    assert len(transport.calls) == 2
    assert result.sent == 2


@pytest.mark.infra
async def test_every_row_in_a_group_shares_one_sent_at(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """One message, one timestamp. Different times would imply separate sends."""
    for day, offset in ((8, 0), (9, -1), (10, -2)):
        await add_due_row(db, world, day=day, offset=offset, merge_key="cluster-1")

    await tick(sessions, FakeTransport())
    timestamps = {r["sent_at"] for r in await rows(db)}
    assert len(timestamps) == 1
    assert None not in timestamps


@pytest.mark.infra
async def test_a_merged_message_names_every_occasion(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    second = (
        await db.execute(
            text(
                "INSERT INTO recipients (shop_id, customer_id, label, type) "
                "VALUES (:s, :c, 'Otam', 'father') RETURNING id"
            ),
            {"s": world["shop_id"], "c": world["customer_id"]},
        )
    ).scalar_one()
    await add_due_row(db, world, day=8, offset=0, merge_key="cluster-1")
    await add_due_row(db, world, day=10, offset=-2, merge_key="cluster-1", recipient_id=second)

    transport = FakeTransport()
    await tick(sessions, transport)

    body = transport.calls[0]["text"]
    assert "Onam" in body and "Otam" in body


# --- idempotency -----------------------------------------------------------


@pytest.mark.infra
async def test_the_claim_is_written_before_the_send(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """The ledger row must exist even when the send itself explodes."""
    await add_due_row(db, world, merge_key="cluster-1")

    transport = ExplodingTransport()
    with pytest.raises(RuntimeError):
        await tick(sessions, transport)

    assert len(transport.calls) == 1, "Telegram was not called"
    entries = await ledger(db)
    assert len(entries) == 1
    assert entries[0]["status"] == MessageStatus.CLAIMED.value


@pytest.mark.infra
async def test_a_retry_after_telegram_accepted_does_not_send_twice(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """THE case a "log after send" design cannot handle.

    Telegram accepted the message; our process died before recording it. The
    rows are still pending and look perfectly sendable. Only the claim stops
    the retry from telling the customer twice.
    """
    await add_due_row(db, world, merge_key="cluster-1")

    first = ExplodingTransport()
    with pytest.raises(RuntimeError):
        await tick(sessions, first)
    assert len(first.calls) == 1

    # The rows survived as pending: nothing marked them.
    assert [r["state"] for r in await rows(db)] == ["pending"]

    second = FakeTransport()
    result = await tick(sessions, second)

    assert second.calls == [], "the retry sent the message a second time"
    assert result.skipped_claimed == 1
    assert result.sent == 0


@pytest.mark.infra
async def test_reprocessing_the_same_batch_twice_sends_once(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await add_due_row(db, world, merge_key="cluster-1")

    transport = FakeTransport()
    await tick(sessions, transport)
    await tick(sessions, transport)

    assert len(transport.calls) == 1


@pytest.mark.infra
async def test_the_ledger_key_differs_from_the_notification_key(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """They guard different things and must not be conflated.

    scheduled_notifications' key stops a duplicate ROW; the ledger's key stops a
    duplicate CALL for rows that are legitimately still pending.
    """
    await add_due_row(db, world, merge_key="cluster-1")
    await tick(sessions, FakeTransport())

    entries = await ledger(db)
    assert entries[0]["transition_key"] == "cluster-1"
    assert entries[0]["status"] == MessageStatus.SENT.value


@pytest.mark.infra
async def test_a_lone_row_keys_the_ledger_on_its_own_identity(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await add_due_row(db, world, offset=-1, merge_key=None)
    await tick(sessions, FakeTransport())

    entry = (await ledger(db))[0]
    assert entry["transition_key"].startswith("occ:")
    assert ":-1" in entry["transition_key"]


# --- partial group sends are structurally impossible -----------------------


@pytest.mark.infra
async def test_a_crash_mid_group_leaves_no_partially_sent_group(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Kill the process between "row 1 marked" and "row 2 marked".

    There is no such moment: the group is marked in ONE statement inside the
    send transaction. The crash rolls the whole thing back, so recovery sees a
    complete group, never a remainder.
    """
    for day, offset in ((8, 0), (9, -1), (10, -2)):
        await add_due_row(db, world, day=day, offset=offset, merge_key="cluster-1")

    class DieAfterAccept:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        async def send_text(self, *, chat_id: int, text: str) -> SendResult:
            self.calls.append({"chat_id": chat_id})
            raise RuntimeError("killed mid-group")

    with pytest.raises(RuntimeError):
        await tick(sessions, DieAfterAccept())

    states = [r["state"] for r in await rows(db)]
    assert states == ["pending", "pending", "pending"], states
    assert len({r["sent_at"] for r in await rows(db)}) == 1  # all NULL


@pytest.mark.infra
async def test_recovery_reprocesses_the_whole_group_as_one_unit(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Not the remainder as a new, smaller group."""
    for day, offset in ((8, 0), (9, -1), (10, -2)):
        await add_due_row(db, world, day=day, offset=offset, merge_key="cluster-1")

    # A worker claimed and died long ago; the claim has since expired.
    await tick(sessions, ExplodingTransport(), now=NOW - CLAIM_TIMEOUT - timedelta(minutes=5))

    transport = FakeTransport()
    result = await tick(sessions, transport)

    assert result.sent == 1
    assert len(transport.calls) == 1, "the group was split into several messages"
    assert all(r["state"] == "sent" for r in await rows(db))
    assert len({r["sent_at"] for r in await rows(db)}) == 1


# --- claimed-row timeout ---------------------------------------------------


@pytest.mark.infra
async def test_a_stuck_claim_is_not_retried_before_the_timeout(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await add_due_row(db, world, merge_key="cluster-1")
    with pytest.raises(RuntimeError):
        await tick(sessions, ExplodingTransport())

    transport = FakeTransport()
    result = await tick(sessions, transport, now=NOW + CLAIM_TIMEOUT - timedelta(minutes=1))

    assert transport.calls == []
    assert result.skipped_claimed == 1


@pytest.mark.infra
async def test_a_stuck_claim_is_retried_after_the_timeout(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """A worker that died mid-call must not park a reminder forever."""
    await add_due_row(db, world, merge_key="cluster-1")
    with pytest.raises(RuntimeError):
        await tick(sessions, ExplodingTransport())

    transport = FakeTransport()
    result = await tick(sessions, transport, now=NOW + CLAIM_TIMEOUT + timedelta(minutes=1))

    assert len(transport.calls) == 1
    assert result.sent == 1
    entry = (await ledger(db))[0]
    assert entry["status"] == MessageStatus.SENT.value
    assert entry["attempts"] == 2, "the retake did not record a second attempt"


# --- 403 -------------------------------------------------------------------


@pytest.mark.infra
async def test_403_marks_the_customer_blocked_and_cancels_their_rows(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await add_due_row(db, world, day=8, merge_key="cluster-1")
    await add_due_row(db, world, day=20, offset=0, merge_key=None)

    result = await tick(sessions, FakeTransport(SendResult.forbidden()))

    status = (
        await db.execute(
            text("SELECT status FROM customers WHERE id = :c"), {"c": world["customer_id"]}
        )
    ).scalar_one()
    assert status == "blocked"
    assert result.cancelled == 1
    assert {r["state"] for r in await rows(db)} == {"cancelled"}


@pytest.mark.infra
async def test_403_is_not_recorded_as_a_failure(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """A block is a decision by the customer, not an error to retry."""
    await add_due_row(db, world, merge_key="cluster-1")
    result = await tick(sessions, FakeTransport(SendResult.forbidden()))

    assert result.failed == 0
    entry = (await ledger(db))[0]
    assert entry["status"] == MessageStatus.CANCELLED.value
    assert entry["error_code"] == "bot_blocked"


@pytest.mark.infra
async def test_a_blocked_customer_is_not_retried_on_the_next_tick(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await add_due_row(db, world, merge_key="cluster-1")
    await tick(sessions, FakeTransport(SendResult.forbidden()))

    transport = FakeTransport()
    await tick(sessions, transport, now=NOW + timedelta(minutes=1))
    assert transport.calls == []


# --- 429 -------------------------------------------------------------------


@pytest.mark.infra
async def test_429_leaves_the_rows_pending_for_a_later_tick(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await add_due_row(db, world, merge_key="cluster-1")

    result = await tick(sessions, FakeTransport(SendResult.rate_limited(7.0)))

    assert result.rate_limited == 1
    assert [r["state"] for r in await rows(db)] == ["pending"]
    assert await ledger(db) == [], "a rate-limited claim was left blocking the retry"


@pytest.mark.infra
async def test_a_429_is_retried_and_succeeds(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await add_due_row(db, world, merge_key="cluster-1")
    await tick(sessions, FakeTransport(SendResult.rate_limited(3.0)))

    transport = FakeTransport()
    result = await tick(sessions, transport, now=NOW + timedelta(minutes=1))

    assert result.sent == 1
    assert len(transport.calls) == 1


# --- attempts and the dead letter -----------------------------------------


@pytest.mark.infra
async def test_attempts_increments_on_every_claim(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await add_due_row(db, world, merge_key="cluster-1")
    await tick(sessions, FakeTransport(SendResult.rate_limited(1.0)))
    assert [r["attempts"] for r in await rows(db)] == [1]

    await tick(
        sessions, FakeTransport(SendResult.rate_limited(1.0)), now=NOW + timedelta(minutes=1)
    )
    assert [r["attempts"] for r in await rows(db)] == [2]


@pytest.mark.infra
async def test_a_row_stops_retrying_at_the_attempt_limit(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """It parks in dead_letter, inspectable, rather than retrying forever."""
    await add_due_row(db, world, merge_key="cluster-1")

    now = NOW
    for _ in range(MAX_SEND_ATTEMPTS + 1):
        await tick(sessions, FakeTransport(SendResult.rate_limited(1.0)), now=now)
        now += timedelta(minutes=1)

    state = (await rows(db))[0]
    assert state["state"] == "dead_letter"
    assert state["attempts"] > MAX_SEND_ATTEMPTS

    transport = FakeTransport()
    await tick(sessions, transport, now=now)
    assert transport.calls == [], "a dead-lettered row was retried"


@pytest.mark.infra
async def test_the_dead_letter_state_is_queryable(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await add_due_row(db, world, merge_key="cluster-1")
    now = NOW
    for _ in range(MAX_SEND_ATTEMPTS + 1):
        await tick(sessions, FakeTransport(SendResult.rate_limited(1.0)), now=now)
        now += timedelta(minutes=1)

    parked = (
        await db.execute(
            text("SELECT count(*) FROM scheduled_notifications WHERE state = 'dead_letter'")
        )
    ).scalar_one()
    assert parked == 1


# --- staleness backstop ----------------------------------------------------


@pytest.mark.infra
async def test_a_row_past_its_grace_window_is_expired_not_sent(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await add_due_row(db, world, due=NOW - timedelta(hours=9), merge_key="cluster-1")

    transport = FakeTransport()
    result = await tick(sessions, transport)

    assert transport.calls == []
    assert result.expired == 1
    assert [r["state"] for r in await rows(db)] == ["expired"]


@pytest.mark.infra
async def test_a_row_whose_occasion_has_passed_is_expired(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """ "Your wife's birthday is tomorrow" must never arrive the day after."""
    yesterday_evening = datetime(2027, 3, 7, 15, 0, tzinfo=UTC)  # 20:00 Tashkent
    await add_due_row(db, world, offset=-1, due=yesterday_evening, merge_key="cluster-1")

    # Now is the 9th in Tashkent: the occasion (the 8th) has passed.
    result = await tick(sessions, FakeTransport(), now=datetime(2027, 3, 9, 6, 0, tzinfo=UTC))
    assert result.expired == 1


@pytest.mark.infra
async def test_a_fresh_row_is_not_expired(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await add_due_row(db, world, merge_key="cluster-1")
    result = await tick(sessions, FakeTransport())
    assert result.expired == 0
    assert result.sent == 1


# --- selection -------------------------------------------------------------


@pytest.mark.infra
async def test_rows_that_are_not_yet_due_are_left_alone(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await add_due_row(db, world, due=NOW + timedelta(hours=2), merge_key="cluster-1")
    transport = FakeTransport()
    result = await tick(sessions, transport)
    assert (transport.calls, result.groups) == ([], 0)


@pytest.mark.infra
async def test_only_pending_rows_are_picked_up(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await add_due_row(db, world, merge_key="cluster-1")
    await db.execute(text("UPDATE scheduled_notifications SET state = 'sent', sent_at = now()"))
    transport = FakeTransport()
    result = await tick(sessions, transport)
    assert (transport.calls, result.groups) == ([], 0)


def test_transition_key_shape_is_stable() -> None:
    """CP9 must not change this: the ledger keys are already in the database."""

    class Row:
        merge_key = None
        occasion_id = 42
        occurrence_year = 2027
        offset_days = -7

    assert transition_key_for(Row()) == "occ:42:2027:-7"  # type: ignore[arg-type]


# --- a block survives across ticks, not just within one batch ---------------


@pytest.mark.infra
async def test_a_403_cancels_rows_that_were_not_even_in_this_batch(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """The window between the block and the next nightly materialization.

    The materializer stops generating NEW rows for a blocked customer, but it
    only runs nightly. Rows already materialized for later dates must be
    cancelled at once, not left to trickle through one tick at a time until
    they exhaust MAX_SEND_ATTEMPTS.
    """
    await add_due_row(db, world, day=8, offset=0, merge_key="today")
    # Due in three days: not selected by this tick at all.
    await add_due_row(db, world, day=20, offset=0, merge_key="later", due=NOW + timedelta(days=3))
    await add_due_row(
        db, world, day=25, offset=0, merge_key="later-still", due=NOW + timedelta(days=6)
    )

    result = await tick(sessions, FakeTransport(SendResult.forbidden()))

    assert result.groups == 1, "only the due row should have been selected"
    states = {r["state"] for r in await rows(db)}
    assert states == {"cancelled"}, f"future rows survived the block: {states}"


@pytest.mark.infra
async def test_a_blocked_customer_gets_nothing_on_a_later_days_tick(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Monday's block must still hold on Tuesday, before any materializer run."""
    await add_due_row(db, world, day=8, offset=0, merge_key="monday")
    await add_due_row(db, world, day=20, offset=0, merge_key="tuesday", due=NOW + timedelta(days=1))

    await tick(sessions, FakeTransport(SendResult.forbidden()))

    tuesday = FakeTransport()
    result = await tick(sessions, tuesday, now=NOW + timedelta(days=1, minutes=5))

    assert tuesday.calls == [], "a blocked customer was contacted the next day"
    assert result.groups == 0, "cancelled rows were re-selected as due"


@pytest.mark.infra
async def test_a_block_does_not_burn_attempts_one_tick_at_a_time(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Cancelled immediately, rather than retried up to the attempt limit."""
    await add_due_row(db, world, day=8, offset=0, merge_key="a")
    await add_due_row(db, world, day=20, offset=0, merge_key="b")

    await tick(sessions, FakeTransport(SendResult.forbidden()))

    for row in await rows(db):
        assert row["state"] == "cancelled"
        assert row["attempts"] <= 1, "a blocked customer's rows accrued retries"


@pytest.mark.infra
async def test_a_block_cancels_more_rows_than_one_batch_holds(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """The cancel is a single scoped UPDATE, so BATCH_SIZE does not bound it."""
    for day in range(1, 12):
        await add_due_row(
            db, world, day=day, offset=0, merge_key=f"m{day}", due=NOW + timedelta(days=day)
        )
    await add_due_row(db, world, day=28, offset=0, merge_key="due-now")

    await tick(sessions, FakeTransport(SendResult.forbidden()), limit=2)

    remaining = [r["state"] for r in await rows(db)]
    assert set(remaining) == {"cancelled"}, remaining
    assert len(remaining) == 12


@pytest.mark.infra
async def test_blocking_one_customer_does_not_touch_another(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """The cancel is scoped by customer_id, not global."""
    other_customer = (
        await db.execute(
            text(
                "INSERT INTO customers (shop_id, telegram_user_id) VALUES (:s, 6099) RETURNING id"
            ),
            {"s": world["shop_id"]},
        )
    ).scalar_one()
    other_recipient = (
        await db.execute(
            text(
                "INSERT INTO recipients (shop_id, customer_id, label, type) "
                "VALUES (:s, :c, 'Otam', 'father') RETURNING id"
            ),
            {"s": world["shop_id"], "c": other_customer},
        )
    ).scalar_one()
    other_world = {
        "shop_id": world["shop_id"],
        "customer_id": other_customer,
        "recipient_id": other_recipient,
    }

    await add_due_row(db, world, day=8, offset=0, merge_key="blocked-one")
    await add_due_row(db, other_world, day=9, offset=0, merge_key="innocent")

    transport = FakeTransport(SendResult.forbidden())  # first group only
    await tick(sessions, transport)

    by_customer = {r["occasion_id"]: r["state"] for r in await rows(db)}
    assert "cancelled" in by_customer.values()
    assert "sent" in by_customer.values(), "an unrelated customer was cancelled too"

    statuses = dict((await db.execute(text("SELECT id, status FROM customers ORDER BY id"))).all())
    assert statuses[world["customer_id"]] == "blocked"
    assert statuses[other_customer] == "active"
