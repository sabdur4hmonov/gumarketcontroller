"""The per-shop token migration, run against shops that predate it.

The interesting part is the DATA step, not the columns: exactly one shop -- the
single pre-existing one every running deployment has -- is allowed to keep
using the process BOT_TOKEN, so nothing running today stops. Every shop created
afterwards must bring its own token.

"The single pre-existing shop" is taken literally. With more than one shop
already present there is no single one, and `resolve_single_shop` would have
refused to start such a deployment anyway, so none is flagged.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from tests.conftest import alembic_config_for, create_database, drop_database

from gulbot.config import Settings
from gulbot.models.shop import DEFAULT_WORKING_HOURS

pytestmark = pytest.mark.infra

PROBE_DB = "gulbot_shop_token_probe"
#: The head before per-shop tokens existed.
BEFORE = "93b90673b997"


@pytest.fixture
def old_schema(settings: Settings) -> Iterator[dict[str, Any]]:
    drop_database(settings, PROBE_DB)
    create_database(settings, PROBE_DB)
    engine = create_engine(settings.database_url(database=PROBE_DB, driver="psycopg"))
    try:
        with alembic_config_for(PROBE_DB) as cfg:
            command.upgrade(cfg, BEFORE)
            yield {"cfg": cfg, "engine": engine}
    finally:
        engine.dispose()
        drop_database(settings, PROBE_DB)


def _shops(engine: Engine, *names: str) -> list[int]:
    with engine.begin() as conn:
        return [
            int(
                conn.execute(
                    text(
                        "INSERT INTO shops (name, working_hours) "
                        "VALUES (:n, CAST(:wh AS jsonb)) RETURNING id"
                    ),
                    {"n": name, "wh": json.dumps(DEFAULT_WORKING_HOURS)},
                ).scalar_one()
            )
            for name in names
        ]


def _flags(engine: Engine) -> dict[str, tuple[bool, str | None]]:
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT name, uses_process_bot_token, bot_token_encrypted FROM shops")
        ).all()
    return {name: (flag, token) for name, flag, token in rows}


def test_the_single_pre_existing_shop_keeps_bot_token(old_schema: dict[str, Any]) -> None:
    _shops(old_schema["engine"], "Pilot")
    command.upgrade(old_schema["cfg"], "head")
    assert _flags(old_schema["engine"]) == {"Pilot": (True, None)}


def test_with_several_shops_already_present_none_may_fall_back(
    old_schema: dict[str, Any],
) -> None:
    _shops(old_schema["engine"], "One", "Two")
    command.upgrade(old_schema["cfg"], "head")
    assert _flags(old_schema["engine"]) == {"One": (False, None), "Two": (False, None)}


def test_a_shop_created_after_the_migration_must_bring_its_own_token(
    old_schema: dict[str, Any],
) -> None:
    """Even as the only shop in the database: the fallback belongs to the
    shop that was already running, not to whichever shop is alone."""
    command.upgrade(old_schema["cfg"], "head")
    _shops(old_schema["engine"], "Newcomer")
    assert _flags(old_schema["engine"]) == {"Newcomer": (False, None)}


def test_the_migration_downgrades_cleanly(old_schema: dict[str, Any]) -> None:
    _shops(old_schema["engine"], "Pilot")
    command.upgrade(old_schema["cfg"], "head")
    command.downgrade(old_schema["cfg"], BEFORE)

    columns = {c["name"] for c in inspect(old_schema["engine"]).get_columns("shops")}
    assert "bot_token_encrypted" not in columns
    assert "uses_process_bot_token" not in columns
