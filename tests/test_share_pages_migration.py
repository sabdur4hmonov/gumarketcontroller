"""The share-pages migration, round-tripped on a database made for this run.

Addressed by revision NAME, never by counting steps (CONTRIBUTING: "never
address a migration by counting steps"), so it keeps meaning the same thing
when later migrations land on top.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from tests.conftest import alembic_config_for, create_database, drop_database

from gulbot.config import Settings
from gulbot.models.shop import DEFAULT_WORKING_HOURS

pytestmark = pytest.mark.infra

PROBE_DB = "gulbot_share_pages_probe"
BEFORE = "0737b83c5742"
THIS = "1897629a71dc"
TABLES = {"share_pages", "share_page_rsvps", "share_page_referrals"}


@pytest.fixture
def probe(settings: Settings) -> Iterator[dict[str, Any]]:
    drop_database(settings, PROBE_DB)
    create_database(settings, PROBE_DB)
    engine = create_engine(settings.database_url(database=PROBE_DB, driver="psycopg"))
    try:
        with alembic_config_for(PROBE_DB) as cfg:
            command.upgrade(cfg, BEFORE)
            with engine.begin() as conn:
                shop = conn.execute(
                    text(
                        "INSERT INTO shops (name, working_hours) "
                        "VALUES ('Pilot', CAST(:wh AS jsonb)) RETURNING id"
                    ),
                    {"wh": json.dumps(DEFAULT_WORKING_HOURS)},
                ).scalar_one()
                conn.execute(
                    text("INSERT INTO customers (shop_id, telegram_user_id) VALUES (:s, 1)"),
                    {"s": shop},
                )
            yield {"cfg": cfg, "engine": engine}
    finally:
        engine.dispose()
        drop_database(settings, PROBE_DB)


def tables(engine: Any) -> set[str]:
    return set(inspect(engine).get_table_names())


def test_it_adds_three_tables_and_touches_nothing_else(probe: dict[str, Any]) -> None:
    before = tables(probe["engine"])
    command.upgrade(probe["cfg"], THIS)
    assert tables(probe["engine"]) - before == TABLES
    with probe["engine"].begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM customers")).scalar_one() == 1


def test_it_round_trips(probe: dict[str, Any]) -> None:
    command.upgrade(probe["cfg"], THIS)
    with probe["engine"].begin() as conn:
        conn.execute(
            text(
                "INSERT INTO share_pages (shop_id, customer_id, token, kind, template, lang, "
                " question_preset, question, expires_at) "
                "SELECT shop_id, id, 'TTTTTTTTTTTTTTTTTTTTTT', 'yesno', 'milliy', 'uz', 'marry', "
                " 'q', now() + interval '1 day' FROM customers"
            )
        )
    command.downgrade(probe["cfg"], BEFORE)
    assert not (TABLES & tables(probe["engine"]))
    command.upgrade(probe["cfg"], THIS)
    assert tables(probe["engine"]) >= TABLES
