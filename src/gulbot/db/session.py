"""Async engine and session factory for application code.

Migrations deliberately use the SYNC psycopg driver instead (see migrations/env.py):
Alembic's own machinery is synchronous, and running it that way avoids an entire
class of event-loop problems for zero benefit.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from gulbot.config import get_settings

#: Milliseconds before Postgres cancels one statement on an application
#: connection. Postgres's own default is 0: never.
#:
#: Found in the pre-deployment audit, pass 5. With no bound, one statement that
#: never returns -- a lock wait behind a stuck transaction, a runaway query --
#: holds its worker forever, and the worker runs one task at a time. Thirty
#: seconds is orders of magnitude above anything the bot or the ticks run, and a
#: waiter on the per-shop-per-day advisory lock is cancelled by it too.
#:
#: `idle_in_transaction_session_timeout` is DELIBERATELY NOT SET. Several paths
#: hold a transaction open across a Telegram call, correctly, and CP6's claim
#: design depends on that; a limit below the request timeout would kill those
#: mid-send and turn them into the duplicates CP6 only accepts for dead workers.
#:
#: Migrations do not come through here -- they use the sync driver
#: (migrations/env.py) -- so a long backfill is not cut off by this.
STATEMENT_TIMEOUT_MS = 30_000


def build_engine(database: str | None = None) -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        settings.database_url(database=database),
        future=True,
        # Set per connection at connect time, so every pooled connection has it
        # and nothing needs to remember a SET.
        connect_args={"server_settings": {"statement_timeout": str(STATEMENT_TIMEOUT_MS)}},
    )


def build_session_factory(database: str | None = None) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(build_engine(database), expire_on_commit=False)


@asynccontextmanager
async def task_session_factory(
    database: str | None = None,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A session factory whose ENGINE is disposed when the caller is done.

    For Celery tasks specifically. `build_session_factory()` creates a new
    engine per call and never disposes it, which is fine for `bot.run` -- one
    engine for the life of one long-running process -- and wrong for a task,
    which runs `asyncio.run()` and then abandons a connection pool bound to a
    loop that no longer exists. One leaked pool per tick, every minute, forever.

    Same shape and the same reason as `album_debouncer()` and the Bot session's
    `finally: await bot.session.close()`: **a task owns its clients for its own
    lifetime.** See CONTRIBUTING for the rule and the running status table.

    `bot.run` must NOT use this. Disposing the engine after one update would
    throw away the pool between every message.
    """
    engine = build_engine(database)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
