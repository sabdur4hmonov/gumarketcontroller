"""The CP23 revision itself, round-tripped by NAME on a fresh database."""

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
from tests.conftest import alembic_config_for, create_database, drop_database

REVISION = "c23a1f5e7b90"
COLUMNS = {"template", "template_picked", "caption_lang"}


def test_cp23_flower_template_revision_roundtrip(settings):
    database = "gulbot_cp23_roundtrip"
    drop_database(settings, database)
    create_database(settings, database)
    engine = create_engine(settings.database_url(database=database, driver="psycopg"))

    def state() -> tuple[bool, set[str]]:
        with engine.connect() as connection:
            inspector = inspect(connection)
            columns = {c["name"] for c in inspector.get_columns("announcement_drafts")}
            return "announcement_theme_favourites" in inspector.get_table_names(), columns

    try:
        with alembic_config_for(database) as config:
            command.upgrade(config, "head")
            table, columns = state()
            assert table and columns >= COLUMNS
            revision = ScriptDirectory.from_config(config).get_revision(REVISION)
            command.downgrade(config, revision.down_revision)
            table, columns = state()
            assert not table and not COLUMNS & columns
            # CP22's own draft table survives the downgrade untouched.
            assert {"caption_style", "image_style"} <= columns
            command.upgrade(config, "head")
            table, columns = state()
            assert table and columns >= COLUMNS
    finally:
        engine.dispose()
        drop_database(settings, database)


def test_cp23_instagram_revision_roundtrip(settings):
    database = "gulbot_cp23_ig_roundtrip"
    tables = {"instagram_connections", "instagram_oauth_states", "instagram_story_uploads"}
    drop_database(settings, database)
    create_database(settings, database)
    engine = create_engine(settings.database_url(database=database, driver="psycopg"))

    def present() -> tuple[set[str], bool]:
        with engine.connect() as connection:
            inspector = inspect(connection)
            unique = {
                tuple(c["column_names"])
                for c in inspector.get_unique_constraints("announcement_drafts")
            }
            return set(inspector.get_table_names()) & tables, ("id", "shop_id") in unique

    try:
        with alembic_config_for(database) as config:
            command.upgrade(config, "head")
            assert present() == (tables, True)
            revision = ScriptDirectory.from_config(config).get_revision("d23b4e8f1a26")
            command.downgrade(config, revision.down_revision)
            assert present() == (set(), False)
            command.upgrade(config, "head")
            assert present() == (tables, True)
    finally:
        engine.dispose()
        drop_database(settings, database)


def test_cp23_corrections_revision_roundtrip(settings):
    """The addendum's revision: corrections table, and 'deleted' in the
    drafts' status CHECK; the downgrade turns deleted posts back into
    published ones (the old CHECK cannot hold them) and drops corrections."""
    from sqlalchemy import text

    database = "gulbot_cp23_corr_roundtrip"
    drop_database(settings, database)
    create_database(settings, database)
    engine = create_engine(settings.database_url(database=database, driver="psycopg"))
    try:
        with alembic_config_for(database) as config:
            command.upgrade(config, "head")
            with engine.begin() as connection:
                assert "announcement_corrections" in inspect(connection).get_table_names()
                shop = connection.execute(
                    text(
                        "INSERT INTO shops (name, working_hours) VALUES ('R', '{}'::jsonb) "
                        "RETURNING id"
                    )
                ).scalar_one()
                connection.execute(
                    text(
                        "INSERT INTO announcement_drafts (shop_id, author_id, status) "
                        "VALUES (:s, 1, 'deleted')"
                    ),
                    {"s": shop},
                )
            revision = ScriptDirectory.from_config(config).get_revision("e23c5a9d0b37")
            command.downgrade(config, revision.down_revision)
            with engine.connect() as connection:
                assert "announcement_corrections" not in inspect(connection).get_table_names()
                statuses = (
                    connection.execute(text("SELECT status FROM announcement_drafts"))
                    .scalars()
                    .all()
                )
                assert statuses == ["published"]
            command.upgrade(config, "head")
            with engine.connect() as connection:
                assert "announcement_corrections" in inspect(connection).get_table_names()
    finally:
        engine.dispose()
        drop_database(settings, database)
