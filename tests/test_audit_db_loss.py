# ruff: noqa: F811, F401  -- fixtures are imported by name; pytest injects them into
# the same-named test parameters, which ruff reads as a redefinition.
"""PASS 5: the database goes away mid-tick, and a statement that never ends.

1. LOST AFTER TELEGRAM ACCEPTED. The reminder tick commits its claims before
   sending (phase 1), then per group: send, resolve, commit (phase 2). The
   window that matters is AFTER a successful send and BEFORE its resolution
   commits. `test_a_retry_after_telegram_accepted_does_not_send_twice` covers the
   process dying INSIDE the send; this covers the database failing just after.

2. A HUNG STATEMENT. Carried from pass 4: the per-shop-per-day lock is now
   released before any Telegram call, but nothing bounds a statement that never
   returns -- Postgres `statement_timeout` is 0 and the Celery tasks have no time
   limit.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker
from tests.test_dispatcher import (
    NOW,
    FakeTransport,
    add_due_row,
    ledger,
    rows,
    sessions,
    tick,
    world,
)

from gulbot.config import get_settings
from gulbot.db.session import build_engine
from gulbot.models.message_log import CLAIM_TIMEOUT, MessageStatus
from gulbot.sending import dispatcher

pytestmark = pytest.mark.infra


async def test_losing_the_database_after_a_send_loses_nothing_and_waits_before_resending(
    db: AsyncConnection,
    world: dict,
    sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Telegram accepted; the connection drops before the outcome is recorded.

    CONFIRMATION IF THIS PASSES, with one stated trade:
      * nothing is LOST -- the notification rows are still pending;
      * nothing is resent SOONER than CLAIM_TIMEOUT -- the claim committed in
        phase 1 holds, so the next ticks skip the group;
      * after CLAIM_TIMEOUT the claim is treated as abandoned and the reminder is
        sent AGAIN. That duplicate is CP6's documented choice: a genuinely dead
        worker must never silently drop a reminder, and from the database's side
        a lost connection is indistinguishable from one.
    """
    await add_due_row(db, world, merge_key="db-loss")

    async def connection_lost(*a: object, **kw: object) -> None:
        raise OperationalError("UPDATE", {}, Exception("server closed the connection"))

    monkeypatch.setattr(dispatcher, "mark_group", connection_lost)
    first = FakeTransport()
    with pytest.raises(OperationalError):
        await tick(sessions, first)
    monkeypatch.undo()

    assert len(first.calls) == 1, "precondition: Telegram accepted the message"
    assert [r["state"] for r in await rows(db)] == ["pending"], "the reminder was lost"
    assert [e["status"] for e in await ledger(db)] == [MessageStatus.CLAIMED.value]

    soon = FakeTransport()
    await tick(sessions, soon, now=NOW + CLAIM_TIMEOUT / 2)
    assert soon.calls == [], "resent before the claim timed out"

    late = FakeTransport()
    await tick(sessions, late, now=NOW + CLAIM_TIMEOUT * 2)
    assert len(late.calls) == 1, "an abandoned claim was never retried"


async def _show(engine_database: str, setting: str) -> str:
    engine = build_engine(engine_database)
    try:
        async with engine.connect() as conn:
            return str((await conn.execute(text(f"SHOW {setting}"))).scalar_one())
    finally:
        await engine.dispose()


async def test_application_connections_carry_a_thirty_second_statement_timeout() -> None:
    """DEFECT IF THIS FAILS. Measured in pass 5 as '0': a statement that never
    returned held its worker forever. Asked of a real connection from the
    application's own engine, not read back from the constant."""
    assert await _show(get_settings().postgres_test_db, "statement_timeout") == "30s"


async def test_idle_in_transaction_timeout_is_left_alone() -> None:
    """GUARDS THE CAUTION. Several paths hold a transaction open across a
    Telegram call, and CP6 relies on it. A limit here shorter than the request
    timeout would kill them mid-send. Deliberately unset; this fails if someone
    sets it alongside statement_timeout."""
    setting = await _show(get_settings().postgres_test_db, "idle_in_transaction_session_timeout")
    assert setting == "0"


async def test_a_hung_statement_is_cancelled_by_the_engine_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DEFECT IF THIS FAILS. The same statement pass 5 measured running past
    every wait now raises. The timeout is shortened so the suite does not sit
    for 30 s; the mechanism -- set by the engine at connect, enforced by
    Postgres -- is the production one."""
    import gulbot.db.session as session_module

    monkeypatch.setattr(session_module, "STATEMENT_TIMEOUT_MS", 300)
    engine = build_engine(get_settings().postgres_test_db)
    started = time.monotonic()
    try:
        async with engine.connect() as conn:
            with pytest.raises(DBAPIError, match="statement timeout"):
                await asyncio.wait_for(conn.execute(text("SELECT pg_sleep(5)")), timeout=4)
    finally:
        await engine.dispose()

    took = time.monotonic() - started
    print(f"\n  pg_sleep(5) cancelled after {took:.1f}s")
    assert took < 3
