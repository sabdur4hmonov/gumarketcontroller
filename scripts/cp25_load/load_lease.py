"""One capacity run owns its scratch DB for the entire measurement."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

LEASE_SQL = "SELECT pg_try_advisory_lock(hashtextextended('gulbot-cp25-capacity', 0))"


def acquire(connection: Any) -> None:
    """Refuse a competing run before it can reset the owned fixture database."""
    if connection.execute(LEASE_SQL).fetchone() != (True,):
        raise RuntimeError("Another capacity run already owns the scratch database")


@asynccontextmanager
async def database_lease() -> AsyncIterator[None]:
    import psycopg

    from gulbot.config import get_settings

    dsn = (
        get_settings()
        .database_url(database="postgres", driver="psycopg")
        .replace("postgresql+psycopg://", "postgresql://")
    )

    def connect() -> psycopg.Connection[tuple[Any, ...]]:
        return psycopg.connect(dsn, autocommit=True, connect_timeout=5)

    connection = await asyncio.to_thread(connect)
    try:
        await asyncio.to_thread(acquire, connection)
        yield
    finally:
        # Session-owned advisory locks are released by closing this connection.
        await asyncio.to_thread(connection.close)
