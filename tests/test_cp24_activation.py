"""CP24 persists all forty styles and widens only its existing CHECK."""

from __future__ import annotations

import json
import re

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from tests.conftest import alembic_config_for, create_database, drop_database

from gulbot.config import Settings
from gulbot.models.share_page import PAGE_TEMPLATES
from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.services.premium import CP24_PREMIUM_TEMPLATES, PREMIUM_TEMPLATES
from gulbot.web.designs_cp24 import CP24_DESIGNS

REVISION = "a24d9e7b2c10"
BEFORE = "f23d7c2e5a41"
PROBE = "gulbot_cp24_probe"


def test_cp24_is_active_in_creation_and_existing_gift_policy() -> None:
    assert len(PAGE_TEMPLATES) == len(set(PAGE_TEMPLATES)) == 40
    assert set(CP24_DESIGNS) <= set(PAGE_TEMPLATES)
    assert CP24_PREMIUM_TEMPLATES <= PREMIUM_TEMPLATES
    assert len(PREMIUM_TEMPLATES) == 22
    assert len(set(PAGE_TEMPLATES) - PREMIUM_TEMPLATES) == 18


def test_additive_cp24_migration_round_trips_on_fresh_db(settings: Settings) -> None:
    drop_database(settings, PROBE)
    create_database(settings, PROBE)
    engine = create_engine(settings.database_url(database=PROBE, driver="psycopg"))
    try:
        with alembic_config_for(PROBE) as cfg:
            script = ScriptDirectory.from_config(cfg)
            assert len(script.get_heads()) == 1
            assert script.get_revision(REVISION).down_revision == BEFORE
            command.upgrade(cfg, BEFORE)
            with engine.begin() as conn:
                shop = conn.scalar(
                    text(
                        "INSERT INTO shops (name, working_hours) "
                        "VALUES ('CP24 probe', CAST(:wh AS jsonb)) RETURNING id"
                    ),
                    {"wh": json.dumps(DEFAULT_WORKING_HOURS)},
                )
                customer = conn.scalar(
                    text(
                        "INSERT INTO customers (shop_id, telegram_user_id) "
                        "VALUES (:s, 1) RETURNING id"
                    ),
                    {"s": shop},
                )
                conn.execute(
                    text(
                        "INSERT INTO share_pages (shop_id, customer_id, token, kind, "
                        "template, lang, question_preset, question, expires_at) "
                        "VALUES (:s, :c, 'CP24existingAAAAAAAAAA', 'yesno', 'milliy', "
                        "'uz', 'marry', 'Preserved', now() + interval '1 day')"
                    ),
                    {"s": shop, "c": customer},
                )
            command.upgrade(cfg, REVISION)
            with engine.connect() as conn:
                assert conn.scalar(text("SELECT question FROM share_pages")) == "Preserved"
                definition = conn.scalar(
                    text(
                        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE conname = 'ck_share_pages_template_known'"
                    )
                )
                assert set(re.findall(r"'([^']*)'", definition)) == set(PAGE_TEMPLATES)
                tables = set(
                    conn.scalars(
                        text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                    )
                )
            command.downgrade(cfg, BEFORE)
            with engine.connect() as conn:
                definition = conn.scalar(
                    text(
                        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE conname = 'ck_share_pages_template_known'"
                    )
                )
                assert set(re.findall(r"'([^']*)'", definition)) == set(PAGE_TEMPLATES) - set(
                    CP24_DESIGNS
                )
                assert (
                    set(
                        conn.scalars(
                            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                        )
                    )
                    == tables
                )
            command.upgrade(cfg, REVISION)
            with engine.connect() as conn:
                assert conn.scalar(text("SELECT question FROM share_pages")) == "Preserved"
                definition = conn.scalar(
                    text(
                        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE conname = 'ck_share_pages_template_known'"
                    )
                )
                assert set(re.findall(r"'([^']*)'", definition)) == set(PAGE_TEMPLATES)
    finally:
        engine.dispose()
        drop_database(settings, PROBE)
