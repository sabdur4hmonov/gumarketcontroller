"""CP27.5: the shop bot's share-page flow is one button by default.

- SHARE_WIZARD_IN_BOT defaults to OFF; the suite pins it ON (conftest) only so
  the wizard's own tests keep proving the code the flag brings back.
- OFF: the pages menu offers only "🌐 Taklifnoma yaratish"; every menu action
  and every button the old wizard ever sent answers with a studio link; a
  conversation stopped half-way through the wizard is cleared, not misread;
  the wishes buttons (a notification) still work; and the dispatcher passes the
  shadowing sweep.
- ON: the old wizard is exactly as it was.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.share_pages_harness import ShopBot, make_shop

from gulbot import config
from gulbot.bot.callbacks import (
    EditFieldCB,
    InviteEventCB,
    MyPageCB,
    PageLangCB,
    PageMenuCB,
    PageTemplateCB,
    PlanCB,
)
from gulbot.bot.factory import build_dispatcher
from gulbot.bot.routers.share_pages_slim import WIZARD_BUTTONS
from gulbot.bot.shadow_sweep import render_report, sweep
from gulbot.bot.states import InvitePage
from gulbot.config import Settings
from gulbot.i18n.catalog import CATALOG

pytestmark = pytest.mark.infra

USER = 882_001
MENU = CATALOG["btn.menu.pages"]["uz"]
STUDIO_LINK = re.compile(r"/studio/enter/[A-Za-z0-9_-]{40,64}")


@pytest.fixture
def wizard_off(monkeypatch: pytest.MonkeyPatch) -> None:
    moved = config.get_settings().model_copy(update={"share_wizard_in_bot": False})
    monkeypatch.setattr(config, "get_settings", lambda: moved)


@pytest.fixture
async def slim_bot(db: AsyncConnection, wizard_off: None) -> ShopBot:
    shop = await make_shop(db, "Lola gullari")
    return ShopBot(db, shop, bot_id=424_501, username="lola_gullar_bot")


def test_the_wizard_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SHARE_WIZARD_IN_BOT", raising=False)
    assert Settings(_env_file=None).share_wizard_in_bot is False  # type: ignore[call-arg]
    monkeypatch.setenv("SHARE_WIZARD_IN_BOT", "true")
    assert Settings(_env_file=None).share_wizard_in_bot is True  # type: ignore[call-arg]


async def test_the_menu_is_one_button(slim_bot: ShopBot) -> None:
    await slim_bot.say(MENU, user=USER)
    rows = slim_bot.markups()[-1].inline_keyboard
    assert [[b.callback_data for b in row] for row in rows] == [
        [PageMenuCB(action="studio").pack()]
    ]


@pytest.mark.parametrize("action", ["studio", "yesno", "invite", "apology", "mine"])
async def test_every_menu_action_sends_a_studio_link(slim_bot: ShopBot, action: str) -> None:
    await slim_bot.tap(PageMenuCB(action=action).pack(), user=USER)
    assert slim_bot.texts(), "a menu button went dead"
    assert STUDIO_LINK.search(slim_bot.last()), slim_bot.last()


@pytest.mark.parametrize(
    "data",
    [
        PageLangCB(lang="uz").pack(),
        InviteEventCB(event="wedding").pack(),
        PageTemplateCB(template="milliy").pack(),
        MyPageCB(action="edit", page_id=1).pack(),
        PlanCB(action="skip").pack(),
        EditFieldCB(page_id=1, field="name_1").pack(),
    ],
)
async def test_an_old_wizard_button_sends_a_studio_link(slim_bot: ShopBot, data: str) -> None:
    await slim_bot.tap(data, user=USER)
    assert slim_bot.texts(), "an old wizard button went dead"
    assert STUDIO_LINK.search(slim_bot.last()), slim_bot.last()


def test_every_old_wizard_button_is_covered() -> None:
    """A wizard factory added later must be listed, or its buttons go dead."""
    from gulbot.bot import callbacks

    page_factories = {
        cls
        for cls in vars(callbacks).values()
        if isinstance(cls, type)
        and getattr(cls, "__prefix__", "").startswith("pg")
        and cls.__prefix__ not in ("pgmenu", "pgwish")
    }
    assert page_factories == set(WIZARD_BUTTONS)


async def test_a_conversation_left_mid_wizard_is_cleared(
    db: AsyncConnection, slim_bot: ShopBot
) -> None:
    await slim_bot.say("/start", user=USER)
    context = slim_bot.dispatcher.fsm.get_context(bot=slim_bot.bot, chat_id=USER, user_id=USER)
    await context.set_state(InvitePage.entering_name_1)
    await slim_bot.say("Aziz", user=USER)
    assert await context.get_state() is None
    assert any(STUDIO_LINK.search(body) for body in slim_bot.texts()[-2:])
    assert await db.scalar(text("SELECT count(*) FROM share_pages")) == 0


async def test_the_slim_dispatcher_passes_the_shadow_sweep(wizard_off: None) -> None:
    dispatcher = build_dispatcher(session_factory=None, shop_id=0)  # type: ignore[arg-type]
    names = {r.name for r in dispatcher.sub_routers}
    assert "share_pages_slim" in names and "share_pages" not in names
    assert "share_page_wishes" in names, "the wishes notification router stays"
    violations = await sweep(dispatcher)
    assert violations == [], render_report(violations)


async def test_on_the_wizard_is_back() -> None:
    """conftest pins SHARE_WIZARD_IN_BOT=true: the full wizard is registered."""
    dispatcher = build_dispatcher(session_factory=None, shop_id=0)  # type: ignore[arg-type]
    names = {r.name for r in dispatcher.sub_routers}
    assert "share_pages" in names and "share_pages_slim" not in names
