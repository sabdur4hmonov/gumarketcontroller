"""Test harness.

Tests run against a REAL Postgres (the docker compose stack), never sqlite --
we depend on Postgres-specific behaviour (FOR UPDATE SKIP LOCKED, ON CONFLICT,
pg_trgm) and a fake would prove nothing.

Each test gets a connection inside an outer transaction that is always rolled
back, so tests cannot see each other's writes and the database needs no reset
between runs.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from gulbot.config import Settings, get_settings

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


def _admin_dsn(settings: Settings) -> str:
    return (
        f"host={settings.postgres_host} port={settings.postgres_port} "
        f"user={settings.postgres_user} password={settings.postgres_password} "
        f"dbname=postgres"
    )


def create_database(settings: Settings, name: str) -> None:
    with psycopg.connect(_admin_dsn(settings), autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
        if not exists:
            # Identifier cannot be parameterised; the value is our own config.
            conn.execute(f'CREATE DATABASE "{name}"')


def drop_database(settings: Settings, name: str) -> None:
    with psycopg.connect(_admin_dsn(settings), autocommit=True) as conn:
        conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
            (name,),
        )
        conn.execute(f'DROP DATABASE IF EXISTS "{name}"')


@contextmanager
def alembic_config_for(database: str) -> Iterator[Config]:
    """Point Alembic at a specific database via the env.py override."""
    previous = os.environ.get("GULBOT_MIGRATION_DATABASE")
    os.environ["GULBOT_MIGRATION_DATABASE"] = database
    try:
        cfg = Config(str(REPO_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
        yield cfg
    finally:
        if previous is None:
            os.environ.pop("GULBOT_MIGRATION_DATABASE", None)
        else:
            os.environ["GULBOT_MIGRATION_DATABASE"] = previous


@pytest.fixture(scope="session", autouse=True)
def migrated_test_database(settings: Settings) -> Iterator[None]:
    """Create the test database and bring it to head.

    Deliberately synchronous: it runs once, before any event loop exists, so it
    cannot get tangled in pytest-asyncio fixture loop scoping.
    """
    create_database(settings, settings.postgres_test_db)
    with alembic_config_for(settings.postgres_test_db) as cfg:
        command.upgrade(cfg, "head")
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


@pytest_asyncio.fixture
async def shop_id(db: AsyncConnection) -> int:
    """A shop inside the test's rolled-back transaction."""
    import json

    from sqlalchemy import text

    from gulbot.models.shop import DEFAULT_WORKING_HOURS

    result = await db.execute(
        text(
            "INSERT INTO shops (name, working_hours) "
            "VALUES (:name, CAST(:wh AS jsonb)) RETURNING id"
        ),
        {"name": "Test Shop", "wh": json.dumps(DEFAULT_WORKING_HOURS)},
    )
    return int(result.scalar_one())
