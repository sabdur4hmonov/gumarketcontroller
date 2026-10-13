"""Runtime state is durable and shop scoped, with a fresh additive round trip."""

from __future__ import annotations

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
from tests.conftest import alembic_config_for, create_database, drop_database

import gulbot.models  # noqa: F401 registers model metadata
from gulbot.db.base import Base

REVISION = "a25e1d6c8b90"
BEFORE = "a24d9e7b2c10"
PROBE = "gulbot_cp25_runtime_probe"


def test_runtime_schema_is_additive_on_a_fresh_database(settings) -> None:
    assert "shop_runtime_states" in Base.metadata.tables, (
        "Persist poller state independently of health snapshots"
    )
    drop_database(settings, PROBE)
    create_database(settings, PROBE)
    engine = create_engine(settings.database_url(database=PROBE, driver="psycopg"))
    try:
        with alembic_config_for(PROBE) as cfg:
            script = ScriptDirectory.from_config(cfg)
            assert script.get_heads() == [REVISION]
            assert script.get_revision(REVISION).down_revision == BEFORE
            command.upgrade(cfg, BEFORE)
            old = set(inspect(engine).get_table_names())
            command.upgrade(cfg, REVISION)
            assert set(inspect(engine).get_table_names()) == old | {"shop_runtime_states"}
            columns = {c["name"] for c in inspect(engine).get_columns("shop_runtime_states")}
            assert columns == {"shop_id", "updated_at", "state"}
            command.downgrade(cfg, BEFORE)
            assert set(inspect(engine).get_table_names()) == old
            command.upgrade(cfg, REVISION)
            assert "shop_runtime_states" in inspect(engine).get_table_names()
    finally:
        engine.dispose()
        drop_database(settings, PROBE)
