"""The catalogue cursor has a tenant-leading sellable partial index."""

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
from tests.conftest import alembic_config_for, create_database, drop_database

from gulbot.models.product import Product

INDEX = "ix_products_shop_sellable_cursor"
REVISION = "a25f2c7d9e10"
BEFORE = "a25e1d6c8b90"
PROBE = "gulbot_cp25_index_probe"


def test_cursor_index_roundtrips_without_changing_existing_tables(settings) -> None:
    indices = {i.name: i for i in Product.__table__.indexes}
    assert INDEX in indices, "Keyset queries must not sort the entire sellable catalogue"
    assert [c.name for c in indices[INDEX].columns] == ["shop_id", "indexed_at", "id"]
    drop_database(settings, PROBE)
    create_database(settings, PROBE)
    engine = create_engine(settings.database_url(database=PROBE, driver="psycopg"))
    try:
        with alembic_config_for(PROBE) as cfg:
            script = ScriptDirectory.from_config(cfg)
            assert len(script.get_heads()) == 1
            assert script.get_revision(REVISION).down_revision == BEFORE
            command.upgrade(cfg, BEFORE)
            old_tables = set(inspect(engine).get_table_names())
            old_indexes = {i["name"] for i in inspect(engine).get_indexes("products")}
            for _ in range(2):
                command.upgrade(cfg, REVISION)
                found = {i["name"]: i for i in inspect(engine).get_indexes("products")}
                assert set(found) == old_indexes | {INDEX}, "Migration adds exactly one index"
                assert found[INDEX]["column_names"] == ["shop_id", "indexed_at", "id"]
                predicate = str(found[INDEX]["dialect_options"]["postgresql_where"])
                assert "active IS TRUE" in predicate
                assert "deleted_at IS NULL" in predicate
                assert "finalized_at IS NOT NULL" in predicate
                assert set(inspect(engine).get_table_names()) == old_tables
                command.downgrade(cfg, BEFORE)
                assert {i["name"] for i in inspect(engine).get_indexes("products")} == old_indexes
    finally:
        engine.dispose()
        drop_database(settings, PROBE)
