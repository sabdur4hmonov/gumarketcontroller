"""CP27.1 in the SHOP's bot: "🌐 Taklifnoma yaratish" gives this customer a
one-time studio link for this shop, and nothing else changes in the menu."""

from __future__ import annotations

import hashlib
import re

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.share_pages_harness import ShopBot, make_shop

from gulbot.bot.callbacks import PageMenuCB
from gulbot.i18n.catalog import CATALOG

pytestmark = pytest.mark.infra

USER = 881_001
MENU = CATALOG["btn.menu.pages"]["uz"]


@pytest.fixture
async def shop_bot(db: AsyncConnection) -> ShopBot:
    shop = await make_shop(db, "Lola gullari")
    return ShopBot(db, shop, bot_id=424_301, username="lola_gullar_bot")


async def test_the_menu_leads_with_the_studio(shop_bot: ShopBot) -> None:
    await shop_bot.say(MENU, user=USER)
    first_row = shop_bot.markups()[-1].inline_keyboard[0]
    assert first_row[0].text == CATALOG["ibtn.pages.studio"]["uz"]
    assert first_row[0].callback_data == PageMenuCB(action="studio").pack()
    # The wizard stays until CP27.5.
    actions = [row[0].callback_data for row in shop_bot.markups()[-1].inline_keyboard]
    assert PageMenuCB(action="invite").pack() in actions


async def test_the_button_sends_a_one_time_link_for_this_customer(
    db: AsyncConnection, shop_bot: ShopBot
) -> None:
    await shop_bot.tap(PageMenuCB(action="studio").pack(), user=USER)
    assert shop_bot.texts(), "the button answered nothing"
    found = re.search(r"/studio/enter/([A-Za-z0-9_-]{40,64})", shop_bot.last())
    assert found, shop_bot.last()
    row = (
        await db.execute(
            text(
                "SELECT l.token_hash, l.bot_username, c.telegram_user_id, l.shop_id "
                "FROM studio_links l JOIN customers c ON c.id = l.customer_id"
            )
        )
    ).one()
    assert row.token_hash == hashlib.sha256(found.group(1).encode()).hexdigest()
    assert (row.telegram_user_id, row.shop_id) == (USER, shop_bot.shop_id)
    assert row.bot_username == "lola_gullar_bot"
    assert "15" in shop_bot.last()
