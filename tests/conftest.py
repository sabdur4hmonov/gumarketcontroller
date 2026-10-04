"""Test harness.

Tests run against a REAL Postgres (the docker compose stack), never sqlite --
we depend on Postgres-specific behaviour (FOR UPDATE SKIP LOCKED, ON CONFLICT,
pg_trgm) and a fake would prove nothing.

Each test gets a connection inside an outer transaction that is always rolled
back, so tests cannot see each other's writes and the database needs no reset
between runs.
"""

from __future__ import annotations

import hashlib
import os
import secrets
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
        f"user={settings.postgres_user} password={settings.postgres_password.get_secret_value()} "
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


VERSIONS = REPO_ROOT / "migrations" / "versions"

#: The fingerprint is stored as the database's own COMMENT, not in a table.
#:
#: It has to travel with the DATABASE -- the database is the thing that can be
#: stale, so a file on disk would be wrong. But a table would be part of the
#: schema, and `test_models_match_migrations` would then report it as drift
#: forever: autogenerate compares the whole public schema against the models,
#: and it does not know this one is ours. A comment lives in `pg_shdescription`,
#: which is not schema at all, so nothing has to be taught to ignore it.
FINGERPRINT_PREFIX = "gulbot-migrations:"


def migration_fingerprint() -> str:
    """A digest of every migration file's CONTENTS, not just their names.

    Alembic identifies a migration by revision id, so editing an already applied
    one is a silent no-op on `upgrade head` -- the database keeps the old
    definition while `alembic current` still reports head, and every test then
    runs against a schema that no longer exists in the files. That cost an hour
    at CP10. Hashing the bytes turns it into a rebuild.
    """
    digest = hashlib.sha256()
    for path in sorted(VERSIONS.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return f"{FINGERPRINT_PREFIX}{digest.hexdigest()}"


def read_fingerprint(settings: Settings, name: str) -> str | None:
    """The fingerprint the given database was last built from, if any."""
    with psycopg.connect(_admin_dsn(settings), autocommit=True) as conn:
        row = conn.execute(
            "SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname = %s",
            (name,),
        ).fetchone()
    if row is None or row[0] is None or not str(row[0]).startswith(FINGERPRINT_PREFIX):
        return None
    return str(row[0])


def write_fingerprint(settings: Settings, name: str, digest: str) -> None:
    with psycopg.connect(_admin_dsn(settings), autocommit=True) as conn:
        # Neither identifier nor comment can be parameterised in COMMENT ON; the
        # database name is our own config and the digest is 64 hex characters.
        conn.execute(f"COMMENT ON DATABASE \"{name}\" IS '{digest}'")


@pytest.fixture(scope="session", autouse=True)
def migrated_test_database(settings: Settings) -> Iterator[None]:
    """Create the test database and bring it to head.

    Deliberately synchronous: it runs once, before any event loop exists, so it
    cannot get tangled in pytest-asyncio fixture loop scoping.
    """
    name = settings.postgres_test_db
    digest = migration_fingerprint()

    create_database(settings, name)
    if read_fingerprint(settings, name) != digest:
        # A migration file was added, removed, or EDITED. Only the last of those
        # is dangerous, and only that one is invisible: `upgrade head` would
        # happily do nothing and leave the old definition in place. Rebuilding is
        # the only correct response, and it is cheap.
        drop_database(settings, name)
        create_database(settings, name)

    with alembic_config_for(name) as cfg:
        command.upgrade(cfg, "head")
    write_fingerprint(settings, name, digest)
    yield


@pytest.fixture(scope="session", autouse=True)
def alert_cooldowns_of_this_session_only() -> Iterator[str]:
    """Health-alert cooldowns live in REDIS, keyed by shop id, for an hour.

    Shop ids come from the test database's sequence, and that database is
    rebuilt whenever a migration changes -- so a run within the hour after the
    previous one hands out the SAME ids, finds the previous run's cooldowns,
    and an alert test sees "already announced" (found 2026-10-05, CP17: five
    alert tests failed only on a run right after a rebuild). Each session
    therefore claims under its own prefix; the keys still expire on their own.
    """
    from gulbot.sending import health

    previous = health.ALERT_KEY
    health.ALERT_KEY = f"gulbot:test-alert:{secrets.token_hex(6)}"
    try:
        yield health.ALERT_KEY
    finally:
        health.ALERT_KEY = previous


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
