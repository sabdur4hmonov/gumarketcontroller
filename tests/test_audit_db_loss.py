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
from sqlalchemy.exc import OperationalError
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


async def test_nothing_bounds_a_statement_that_never_returns() -> None:
    """MEASUREMENT. With the application's own engine, a statement that takes
    longer than we are willing to wait is still running when we stop waiting --
    Postgres statement_timeout is 0 and nothing in the engine sets one. In a
    solo Celery worker with no task time limit, that is the whole worker."""
    engine = build_engine(get_settings().postgres_test_db)
    started = time.monotonic()
    still_running = False
    try:
        async with engine.connect() as conn:
            setting = (await conn.execute(text("SHOW statement_timeout"))).scalar_one()
            try:
                await asyncio.wait_for(conn.execute(text("SELECT pg_sleep(5)")), timeout=1.5)
            except TimeoutError:
                still_running = True
    finally:
        await engine.dispose()

    print(f"\n  statement_timeout={setting!r}; gave up after {time.monotonic() - started:.1f}s")
    assert setting == "0", "a statement timeout is now configured; update this finding"
    assert still_running, "the statement was bounded by something"
