"""Test harness.

Tests run against a REAL Postgres (the docker compose stack), never sqlite --
we depend on Postgres-specific behaviour (FOR UPDATE SKIP LOCKED, ON CONFLICT,
pg_trgm) and a fake would prove nothing.

Each test gets a connection inside an outer transaction that is always rolled
back, so tests cannot see each other's writes and the database needs no reset
between runs.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import psycopg
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from gulbot.config import Settings, get_settings


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest.fixture(scope="session", autouse=True)
def ensure_test_database(settings: Settings) -> Iterator[None]:
    """Create the test database if it does not exist.

    Deliberately synchronous: it runs once, before any event loop exists, so
    it cannot get tangled in pytest-asyncio fixture loop scoping.
    """
    admin_dsn = (
        f"host={settings.postgres_host} port={settings.postgres_port} "
        f"user={settings.postgres_user} password={settings.postgres_password} "
        f"dbname=postgres"
    )
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (settings.postgres_test_db,)
        ).fetchone()
        if not exists:
            # Identifier cannot be parameterised; the value is our own config.
            conn.execute(f'CREATE DATABASE "{settings.postgres_test_db}"')
    yield


@pytest_asyncio.fixture
async def db(settings: Settings) -> AsyncIterator[AsyncConnection]:
    """A connection wrapped in a transaction that is always rolled back."""
    engine = create_async_engine(
        settings.database_url(database=settings.postgres_test_db), future=True
    )
    try:
        async with engine.connect() as conn:
            transaction = await conn.begin()
            try:
                yield conn
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
