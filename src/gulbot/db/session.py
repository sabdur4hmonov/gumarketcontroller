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


def build_engine(database: str | None = None) -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(settings.database_url(database=database), future=True)


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
