"""English as a customer language (CP17).

A customer can pick English at first contact and in settings; the database
accepts it; the menu and the page flows answer in it; and the migration that
widened the CHECK round-trips, turning English customers back into Uzbek ones
on the way down rather than failing.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.conftest import alembic_config_for, create_database, drop_database
from tests.share_pages_harness import ShopBot, make_shop

from gulbot.config import Settings
from gulbot.i18n.catalog import CATALOG
from gulbot.models.shop import DEFAULT_WORKING_HOURS

pytestmark = pytest.mark.infra

USER = 660_101
ENGLISH = CATALOG["btn.language.en"]["uz"]


async def lang_of(db: AsyncConnection, shop_id: int) -> str:
    return str(
        await db.scalar(
            text("SELECT lang FROM customers WHERE shop_id = :s AND telegram_user_id = :u"),
            {"s": shop_id, "u": USER},
        )
    )


async def test_a_new_customer_can_choose_english(db: AsyncConnection) -> None:
    bot = ShopBot(db, await make_shop(db, "Lola"), bot_id=660_001, username="lola_bot")
    await bot.say("/start", user=USER)
    await bot.say(ENGLISH, user=USER)
    assert await lang_of(db, bot.shop_id) == "en"
    assert any(body.startswith("Great, we'll continue in English") for body in bot.texts())


async def test_english_from_settings_then_the_pages_menu_in_english(db: AsyncConnection) -> None:
    bot = ShopBot(db, await make_shop(db, "Lola"), bot_id=660_002, username="lola_bot")
    await bot.say(CATALOG["btn.menu.settings"]["uz"], user=USER)
    await bot.say(CATALOG["btn.settings.change_language"]["uz"], user=USER)
    await bot.say(ENGLISH, user=USER)
    assert await lang_of(db, bot.shop_id) == "en"
    await bot.say(CATALOG["btn.menu.pages"]["en"], user=USER)
    assert bot.last().startswith("What shall we make?")


async def test_the_database_accepts_en_and_nothing_else_new(
    db: AsyncConnection, shop_id: int
) -> None:
    await db.execute(
        text("INSERT INTO customers (shop_id, telegram_user_id, lang) VALUES (:s, 1, 'en')"),
        {"s": shop_id},
    )
    with pytest.raises(IntegrityError, match="ck_customers_lang_known"):
        async with db.begin_nested():
            await db.execute(
                text(
                    "INSERT INTO customers (shop_id, telegram_user_id, lang) VALUES (:s, 2, 'de')"
                ),
                {"s": shop_id},
            )


PROBE_DB = "gulbot_language_probe"
THIS = "360f0694be06"
BEFORE = "1897629a71dc"


@pytest.fixture
def probe(settings: Settings) -> Iterator[dict[str, Any]]:
    drop_database(settings, PROBE_DB)
    create_database(settings, PROBE_DB)
    engine = create_engine(settings.database_url(database=PROBE_DB, driver="psycopg"))
    try:
        with alembic_config_for(PROBE_DB) as cfg:
            yield {"cfg": cfg, "engine": engine}
    finally:
        engine.dispose()
        drop_database(settings, PROBE_DB)


def test_the_migration_round_trips_and_downgrades_english_to_uzbek(probe: dict[str, Any]) -> None:
    command.upgrade(probe["cfg"], THIS)
    with probe["engine"].begin() as conn:
        shop = conn.execute(
            text(
                "INSERT INTO shops (name, working_hours) "
                "VALUES ('P', CAST(:w AS jsonb)) RETURNING id"
            ),
            {"w": json.dumps(DEFAULT_WORKING_HOURS)},
        ).scalar_one()
        conn.execute(
            text("INSERT INTO customers (shop_id, telegram_user_id, lang) VALUES (:s, 1, 'en')"),
            {"s": shop},
        )
    command.downgrade(probe["cfg"], BEFORE)
    with probe["engine"].begin() as conn:
        assert conn.execute(text("SELECT lang FROM customers")).scalar_one() == "uz"
    command.upgrade(probe["cfg"], THIS)
