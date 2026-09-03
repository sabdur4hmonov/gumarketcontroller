"""Migration integrity.

Two things must hold forever: migrations round-trip cleanly, and the models
never drift ahead of the migrations without anyone noticing.
"""

from __future__ import annotations

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect
from tests.conftest import alembic_config_for, create_database, drop_database

from gulbot.config import Settings
from gulbot.db.base import Base

ROUNDTRIP_DB = "gulbot_migration_roundtrip"
EXPECTED_TABLES = {"shops", "customers"}


@pytest.mark.infra
def test_migrations_round_trip_on_a_clean_database(settings: Settings) -> None:
    """upgrade -> downgrade -> upgrade, on a throwaway database.

    Uses its own database so a failed downgrade cannot damage the suite's
    test database.
    """
    drop_database(settings, ROUNDTRIP_DB)
    create_database(settings, ROUNDTRIP_DB)
    url = settings.database_url(database=ROUNDTRIP_DB, driver="psycopg")
    try:
        with alembic_config_for(ROUNDTRIP_DB) as cfg:
            command.upgrade(cfg, "head")
            engine = create_engine(url)
            with engine.connect() as conn:
                tables = set(inspect(conn).get_table_names())
            assert tables >= EXPECTED_TABLES, tables
            engine.dispose()

            command.downgrade(cfg, "base")
            engine = create_engine(url)
            with engine.connect() as conn:
                tables = set(inspect(conn).get_table_names())
            assert not (EXPECTED_TABLES & tables), f"downgrade left tables behind: {tables}"
            engine.dispose()

            # Must be re-appliable, not just droppable.
            command.upgrade(cfg, "head")
            engine = create_engine(url)
            with engine.connect() as conn:
                tables = set(inspect(conn).get_table_names())
            assert tables >= EXPECTED_TABLES, tables
            engine.dispose()
    finally:
        drop_database(settings, ROUNDTRIP_DB)


@pytest.mark.infra
def test_models_match_migrations(settings: Settings) -> None:
    """No un-migrated model changes.

    Catches the classic: someone edits a model, tests pass locally against a
    database that already has the column, and the migration is never written.
    """
    engine = create_engine(
        settings.database_url(database=settings.postgres_test_db, driver="psycopg")
    )
    try:
        with engine.connect() as conn:
            context = MigrationContext.configure(
                conn, opts={"compare_type": True, "compare_server_default": True}
            )
            diff = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()
    assert diff == [], f"models drifted from migrations: {diff}"
