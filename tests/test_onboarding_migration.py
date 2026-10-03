"""The onboarding columns, migrated onto shops that predate them.

Additive only: every column is nullable or defaulted, so the pilot shop and
every existing row come through unchanged, and `bot_telegram_id` starts NULL --
a shop's bot id is recorded when its token is next stored, and the pilot, on
the BOT_TOKEN fallback, has no stored token to take one from.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from tests.conftest import alembic_config_for, create_database, drop_database

from gulbot.config import Settings
from gulbot.models.shop import DEFAULT_WORKING_HOURS

pytestmark = pytest.mark.infra

PROBE_DB = "gulbot_onboarding_probe"
#: The per-shop-token head, before the onboarding columns.
BEFORE = "da3db957e4c0"
PRE_TOKENS = "93b90673b997"
NEW_COLUMNS = {"bot_telegram_id", "owner_phone", "owner_phone_verified"}


@pytest.fixture
def old_schema(settings: Settings) -> Iterator[dict[str, Any]]:
    drop_database(settings, PROBE_DB)
    create_database(settings, PROBE_DB)
    engine = create_engine(settings.database_url(database=PROBE_DB, driver="psycopg"))
    try:
        with alembic_config_for(PROBE_DB) as cfg:
            # Seeded BEFORE per-shop tokens, as the real pilot was, so the
            # token migration flags it -- and this one must leave that alone.
            command.upgrade(cfg, PRE_TOKENS)
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO shops (name, working_hours) "
                        "VALUES ('Pilot', CAST(:wh AS jsonb))"
                    ),
                    {"wh": json.dumps(DEFAULT_WORKING_HOURS)},
                )
            command.upgrade(cfg, BEFORE)
            yield {"cfg": cfg, "engine": engine}
    finally:
        engine.dispose()
        drop_database(settings, PROBE_DB)


def test_existing_shops_come_through_unchanged(old_schema: dict[str, Any]) -> None:
    command.upgrade(old_schema["cfg"], "head")
    with old_schema["engine"].begin() as conn:
        row = conn.execute(
            text(
                "SELECT name, uses_process_bot_token, bot_telegram_id, owner_phone, "
                " owner_phone_verified FROM shops"
            )
        ).one()
    assert tuple(row) == ("Pilot", True, None, None, False)


def test_two_shops_cannot_share_a_bot_id(old_schema: dict[str, Any]) -> None:
    command.upgrade(old_schema["cfg"], "head")
    with old_schema["engine"].begin() as conn:
        conn.execute(text("UPDATE shops SET bot_telegram_id = 777777"))
    with (
        pytest.raises(IntegrityError, match="uq_shops_bot_telegram_id"),
        old_schema["engine"].begin() as conn,
    ):
        conn.execute(
            text(
                "INSERT INTO shops (name, working_hours, bot_telegram_id) "
                "VALUES ('Second', CAST(:wh AS jsonb), 777777)"
            ),
            {"wh": json.dumps(DEFAULT_WORKING_HOURS)},
        )


def test_the_migration_downgrades_cleanly(old_schema: dict[str, Any]) -> None:
    command.upgrade(old_schema["cfg"], "head")
    command.downgrade(old_schema["cfg"], BEFORE)
    columns = {c["name"] for c in inspect(old_schema["engine"]).get_columns("shops")}
    assert not (NEW_COLUMNS & columns)
