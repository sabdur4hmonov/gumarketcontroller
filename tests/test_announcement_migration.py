"""The CP22 revision itself, round-tripped by NAME on a fresh database."""

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
from tests.conftest import alembic_config_for, create_database, drop_database


def test_cp22_revision_roundtrip(settings):
    database = "gulbot_cp22_roundtrip"
    drop_database(settings, database)
    create_database(settings, database)
    engine = create_engine(settings.database_url(database=database, driver="psycopg"))
    try:
        with alembic_config_for(database) as config:
            command.upgrade(config, "head")
            with engine.connect() as connection:
                assert {"announcement_drafts", "announcement_preferences"} <= set(
                    inspect(connection).get_table_names()
                )
            revision = ScriptDirectory.from_config(config).get_revision("9c22e4d87b10")
            command.downgrade(config, revision.down_revision)
            with engine.connect() as connection:
                assert "announcement_drafts" not in inspect(connection).get_table_names()
                assert "announcement_preferences" not in inspect(connection).get_table_names()
            command.upgrade(config, "head")
            with engine.connect() as connection:
                assert "announcement_drafts" in inspect(connection).get_table_names()
    finally:
        engine.dispose()
        drop_database(settings, database)
