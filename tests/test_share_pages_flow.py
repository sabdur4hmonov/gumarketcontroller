"""Making a page in the bot, through the real dispatcher.

Both flows end to end, then the ways a client could try to steer them: values
no keyboard offered, a button pressed where a name was asked for, a confirm
tapped twice, and the creation limit.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.share_pages_harness import ShopBot, make_shop

from gulbot.bot.callbacks import (
    InviteDayCB,
    InviteEventCB,
    InviteHourCB,
    InviteMinuteCB,
    InviteMonthCB,
    PageChoiceCB,
    PageConfirmCB,
    PageLangCB,
    PageMenuCB,
    PageQuestionCB,
    PageSkipCB,
    PageTemplateCB,
)
from gulbot.bot.states import InvitePage, YesNoPage
from gulbot.i18n.catalog import CATALOG
from gulbot.services import share_pages

pytestmark = pytest.mark.infra

USER = 880_001
MENU = CATALOG["btn.menu.pages"]["uz"]
CANCEL = CATALOG["btn.nav.cancel"]["uz"]
BROWSE = CATALOG["btn.menu.browse"]["uz"]


@pytest.fixture
async def shop_bot(db: AsyncConnection) -> ShopBot:
    shop = await make_shop(db, "Lola gullari")
    return ShopBot(db, shop, bot_id=424_201, username="lola_gullar_bot")


async def state_of(bot: ShopBot, user: int = USER) -> str | None:
    context = bot.dispatcher.fsm.get_context(bot=bot.bot, chat_id=user, user_id=user)
    return await context.get_state()


async def pages(db: AsyncConnection) -> list[dict[str, Any]]:
    rows = await db.execute(text("SELECT * FROM share_pages ORDER BY id"))
    return [dict(row._mapping) for row in rows]


def next_month() -> tuple[int, int]:
    today = datetime.now(ZoneInfo("Asia/Tashkent")).date()
    return (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)


async def yesno_up_to_confirm(bot: ShopBot, user: int = USER) -> None:
    await bot.say(MENU, user=user)
    await bot.tap(PageMenuCB(action="yesno").pack(), user=user)
    await bot.tap(PageLangCB(lang="uz").pack(), user=user)
    await bot.tap(PageQuestionCB(preset="marry").pack(), user=user)
    await bot.tap(PageTemplateCB(template="romantik").pack(), user=user)
    await bot.tap(PageChoiceCB(field="notify", value="yes").pack(), user=user)


# --- the happy paths ----------------------------------------------------------------


async def test_a_yesno_page_end_to_end(db: AsyncConnection, shop_bot: ShopBot) -> None:
    await yesno_up_to_confirm(shop_bot)
    assert await state_of(shop_bot) == YesNoPage.confirming.state
    assert "Menga turmushga chiqasanmi?" in shop_bot.last() or any(
        "Menga turmushga chiqasanmi?" in body for body in shop_bot.texts()[-2:]
    )
    await shop_bot.tap(PageConfirmCB(action="create").pack(), user=USER)

    [page] = await pages(db)
    assert page["shop_id"] == shop_bot.shop_id
    assert page["kind"] == "yesno" and page["template"] == "romantik" and page["lang"] == "uz"
    assert page["question"] == "Menga turmushga chiqasanmi?" and page["notify_creator"] is True
    assert page["bot_username"] == "lola_gullar_bot"
    assert any(f"/p/{page['token']}" in body for body in shop_bot.texts())
    assert await state_of(shop_bot) is None


async def test_a_custom_question(db: AsyncConnection, shop_bot: ShopBot) -> None:
    await shop_bot.say(MENU, user=USER)
    await shop_bot.tap(PageMenuCB(action="yesno").pack(), user=USER)
    await shop_bot.tap(PageLangCB(lang="ru").pack(), user=USER)
    await shop_bot.tap(PageQuestionCB(preset="custom").pack(), user=USER)
    assert await state_of(shop_bot) == YesNoPage.entering_question.state
    await shop_bot.say("Пойдём в кино в субботу?", user=USER)
    await shop_bot.tap(PageTemplateCB(template="tungi").pack(), user=USER)
    await shop_bot.tap(PageChoiceCB(field="notify", value="no").pack(), user=USER)
    await shop_bot.tap(PageConfirmCB(action="create").pack(), user=USER)
    [page] = await pages(db)
    assert page["question"] == "Пойдём в кино в субботу?" and page["question_preset"] == "custom"
    assert page["lang"] == "ru" and page["notify_creator"] is False


async def test_a_taklifnoma_end_to_end(db: AsyncConnection, shop_bot: ShopBot) -> None:
    year, month = next_month()
    await shop_bot.say(MENU, user=USER)
    await shop_bot.tap(PageMenuCB(action="invite").pack(), user=USER)
    await shop_bot.tap(InviteEventCB(event="wedding").pack(), user=USER)
    await shop_bot.tap(PageLangCB(lang="uz_cyrl").pack(), user=USER)
    await shop_bot.say("Азиз", user=USER)
    await shop_bot.say("Малика", user=USER)
    await shop_bot.tap(InviteMonthCB(year=year, month=month).pack(), user=USER)
    await shop_bot.tap(InviteDayCB(day=10).pack(), user=USER)
    await shop_bot.tap(InviteHourCB(hour=18).pack(), user=USER)
    await shop_bot.tap(InviteMinuteCB(minute=30).pack(), user=USER)
    await shop_bot.say("Тошкент, «Наврўз» тўйхонаси", user=USER)
    await shop_bot.pin(user=USER, lat=41.311081, lon=69.240562)
    await shop_bot.say("Сизни кутамиз!", user=USER)
    await shop_bot.tap(PageChoiceCB(field="rsvp", value="yes").pack(), user=USER)
    await shop_bot.tap(PageTemplateCB(template="konvert").pack(), user=USER)
    assert await state_of(shop_bot) == InvitePage.confirming.state
    await shop_bot.tap(PageConfirmCB(action="create").pack(), user=USER)

    [page] = await pages(db)
    assert (page["kind"], page["event_type"], page["lang"], page["template"]) == (
        "invite",
        "wedding",
        "uz_cyrl",
        "konvert",
    )
    assert (page["name_1"], page["name_2"]) == ("Азиз", "Малика")
    assert page["event_date"] == date(year, month, 10)
    assert page["event_time"].strftime("%H:%M") == "18:30"
    assert float(page["location_lat"]) == pytest.approx(41.311081)
    assert page["message"] == "Сизни кутамиз!" and page["rsvp_enabled"] is True


async def test_a_birthday_asks_one_name_and_may_skip_the_extras(
    db: AsyncConnection, shop_bot: ShopBot
) -> None:
    year, month = next_month()
    await shop_bot.say(MENU, user=USER)
    await shop_bot.tap(PageMenuCB(action="invite").pack(), user=USER)
    await shop_bot.tap(InviteEventCB(event="birthday").pack(), user=USER)
    await shop_bot.tap(PageLangCB(lang="en").pack(), user=USER)
    await shop_bot.say("Malika", user=USER)
    assert await state_of(shop_bot) == InvitePage.choosing_month.state
    await shop_bot.tap(InviteMonthCB(year=year, month=month).pack(), user=USER)
    await shop_bot.tap(InviteDayCB(day=1).pack(), user=USER)
    await shop_bot.tap(InviteHourCB(hour=12).pack(), user=USER)
    await shop_bot.tap(InviteMinuteCB(minute=0).pack(), user=USER)
    await shop_bot.say("Cafe Lola, Tashkent", user=USER)
    await shop_bot.tap(PageSkipCB(step="location").pack(), user=USER)
    await shop_bot.tap(PageSkipCB(step="message").pack(), user=USER)
    await shop_bot.tap(PageChoiceCB(field="rsvp", value="no").pack(), user=USER)
    await shop_bot.tap(PageTemplateCB(template="quvnoq").pack(), user=USER)
    await shop_bot.tap(PageConfirmCB(action="create").pack(), user=USER)
    [page] = await pages(db)
    assert page["name_2"] is None and page["location_lat"] is None and page["message"] is None
    assert page["rsvp_enabled"] is False


# --- steering it -------------------------------------------------------------------


@pytest.mark.parametrize(
    "crafted",
    [
        PageTemplateCB(template="evil").pack(),
        PageTemplateCB(template="../../etc").pack(),
        PageChoiceCB(field="rsvp", value="yes").pack(),  # the other flow's toggle
        PageChoiceCB(field="notify", value="maybe").pack(),
        PageConfirmCB(action="create").pack(),  # not yet at the confirm step
    ],
)
async def test_values_no_keyboard_offered_change_nothing(
    db: AsyncConnection, shop_bot: ShopBot, crafted: str
) -> None:
    await shop_bot.say(MENU, user=USER)
    await shop_bot.tap(PageMenuCB(action="yesno").pack(), user=USER)
    await shop_bot.tap(PageLangCB(lang="uz").pack(), user=USER)
    await shop_bot.tap(PageQuestionCB(preset="date").pack(), user=USER)
    before = await state_of(shop_bot)
    await shop_bot.tap(crafted, user=USER)
    assert await state_of(shop_bot) == before == YesNoPage.choosing_template.state
    assert await pages(db) == []


@pytest.mark.parametrize("crafted", [PageLangCB(lang="xx"), PageQuestionCB(preset="hack")])
async def test_an_unknown_language_or_question_changes_nothing(
    shop_bot: ShopBot, crafted: Any
) -> None:
    await shop_bot.say(MENU, user=USER)
    await shop_bot.tap(PageMenuCB(action="yesno").pack(), user=USER)
    if isinstance(crafted, PageQuestionCB):
        await shop_bot.tap(PageLangCB(lang="uz").pack(), user=USER)
    before = await state_of(shop_bot)
    await shop_bot.tap(crafted.pack(), user=USER)
    assert await state_of(shop_bot) == before


async def invite_to_month(bot: ShopBot) -> None:
    await bot.say(MENU, user=USER)
    await bot.tap(PageMenuCB(action="invite").pack(), user=USER)
    await bot.tap(InviteEventCB(event="birthday").pack(), user=USER)
    await bot.tap(PageLangCB(lang="uz").pack(), user=USER)
    await bot.say("Malika", user=USER)


async def test_a_month_outside_the_window_is_refused(shop_bot: ShopBot) -> None:
    await invite_to_month(shop_bot)
    today = datetime.now(ZoneInfo("Asia/Tashkent")).date()
    for year, month in ((today.year + 2, 1), (today.year - 1, 12), (today.year, 13)):
        try:
            data = InviteMonthCB(year=year, month=month).pack()
        except ValueError:
            continue
        await shop_bot.tap(data, user=USER)
        assert await state_of(shop_bot) == InvitePage.choosing_month.state


async def test_a_day_that_does_not_exist_or_has_passed_is_refused(shop_bot: ShopBot) -> None:
    await invite_to_month(shop_bot)
    today = datetime.now(ZoneInfo("Asia/Tashkent")).date()
    await shop_bot.tap(InviteMonthCB(year=today.year, month=today.month).pack(), user=USER)
    assert await state_of(shop_bot) == InvitePage.choosing_day.state
    for day in (32, 0) + ((today.day - 1,) if today.day > 1 else ()):
        await shop_bot.tap(InviteDayCB(day=day).pack(), user=USER)
        assert await state_of(shop_bot) == InvitePage.choosing_day.state


async def test_an_hour_or_minute_not_offered_is_refused(shop_bot: ShopBot) -> None:
    year, month = next_month()
    await invite_to_month(shop_bot)
    await shop_bot.tap(InviteMonthCB(year=year, month=month).pack(), user=USER)
    await shop_bot.tap(InviteDayCB(day=2).pack(), user=USER)
    for hour in (3, 24, -1):
        await shop_bot.tap(InviteHourCB(hour=hour).pack(), user=USER)
        assert await state_of(shop_bot) == InvitePage.choosing_hour.state
    await shop_bot.tap(InviteHourCB(hour=19).pack(), user=USER)
    for minute in (7, 60):
        await shop_bot.tap(InviteMinuteCB(minute=minute).pack(), user=USER)
        assert await state_of(shop_bot) == InvitePage.choosing_minute.state


async def test_a_button_label_is_not_taken_for_a_name(shop_bot: ShopBot) -> None:
    await shop_bot.say(MENU, user=USER)
    await shop_bot.tap(PageMenuCB(action="invite").pack(), user=USER)
    await shop_bot.tap(InviteEventCB(event="birthday").pack(), user=USER)
    await shop_bot.tap(PageLangCB(lang="uz").pack(), user=USER)
    await shop_bot.say(BROWSE, user=USER)
    assert await state_of(shop_bot) == InvitePage.entering_name_1.state


async def test_cancel_and_start_still_win_from_a_text_step(shop_bot: ShopBot) -> None:
    await shop_bot.say(MENU, user=USER)
    await shop_bot.tap(PageMenuCB(action="yesno").pack(), user=USER)
    await shop_bot.tap(PageLangCB(lang="uz").pack(), user=USER)
    await shop_bot.tap(PageQuestionCB(preset="custom").pack(), user=USER)
    await shop_bot.say(CANCEL, user=USER)
    assert await state_of(shop_bot) is None
    await shop_bot.tap(PageMenuCB(action="yesno").pack(), user=USER)
    await shop_bot.tap(PageLangCB(lang="uz").pack(), user=USER)
    await shop_bot.tap(PageQuestionCB(preset="custom").pack(), user=USER)
    await shop_bot.say("/start", user=USER)
    assert await state_of(shop_bot) != YesNoPage.entering_question.state


async def test_a_double_tap_on_create_makes_one_page(
    db: AsyncConnection, shop_bot: ShopBot
) -> None:
    await yesno_up_to_confirm(shop_bot)
    await shop_bot.tap(PageConfirmCB(action="create").pack(), user=USER)
    await shop_bot.tap(PageConfirmCB(action="create").pack(), user=USER)
    assert len(await pages(db)) == 1


async def test_cancel_at_the_end_makes_nothing(db: AsyncConnection, shop_bot: ShopBot) -> None:
    await yesno_up_to_confirm(shop_bot)
    await shop_bot.tap(PageConfirmCB(action="cancel").pack(), user=USER)
    assert await pages(db) == []


async def test_the_limit_is_explained_not_crashed_into(
    db: AsyncConnection, shop_bot: ShopBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(share_pages, "CREATE_PER_DAY", 1)
    await yesno_up_to_confirm(shop_bot)
    await shop_bot.tap(PageConfirmCB(action="create").pack(), user=USER)
    await yesno_up_to_confirm(shop_bot)
    await shop_bot.tap(PageConfirmCB(action="create").pack(), user=USER)
    assert len(await pages(db)) == 1
    assert any("kunlik chegara" in body for body in shop_bot.texts())


async def test_in_production_without_https_the_feature_is_off(
    db: AsyncConnection, shop_bot: ShopBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gulbot.web import links

    monkeypatch.setattr(links, "pages_available", lambda: False)
    await shop_bot.say(MENU, user=USER)
    assert "hali ishga tushmagan" in shop_bot.last()
    await shop_bot.tap(PageMenuCB(action="yesno").pack(), user=USER)
    assert await state_of(shop_bot) is None
