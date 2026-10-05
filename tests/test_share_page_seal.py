"""Konvert's seal monogram (CP17).

The seal carries letters the creator typed -- checked like any other input --
or the couple's initials. tests/test_page_js.py proves the letter then opens
section by section.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
from tests.bot_harness import bound_session_factory
from tests.share_pages_harness import ShopBot
from tests.test_share_pages_service import invite, make_customer, make_shop

from gulbot.i18n.catalog import CATALOG
from gulbot.services import share_pages
from gulbot.services.share_pages import EditRefused, InvalidDraft, clean_monogram
from gulbot.web.app import build_app

pytestmark = pytest.mark.infra


def soon(days: int = 30) -> date:
    return (datetime.now(UTC) + timedelta(days=days)).astimezone(ZoneInfo("Asia/Tashkent")).date()


# --- the seal ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("typed", "stored"),
    [("a&m", "A&M"), (" s . d ", "S·D"), ("Ф", "Ф"), ("", None), (None, None)],
)
def test_a_monogram_is_letters_and_a_joiner(typed: str | None, stored: str | None) -> None:
    assert clean_monogram(typed) == stored


@pytest.mark.parametrize("typed", ["A1", "ABCDEF", "&&", "<b>", 5])
def test_anything_else_is_not_a_monogram(typed: object) -> None:
    with pytest.raises(ValueError):
        clean_monogram(typed)


@pytest.fixture
async def session(db: AsyncConnection) -> AsyncSession:
    return bound_session_factory(db)()


async def konvert(
    session: AsyncSession, db: AsyncConnection, *, user: int = 770, **kw: Any
) -> tuple[Any, int, int]:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, user)
    page = await share_pages.create_page(
        session,
        shop_id=shop,
        customer_id=customer,
        bot_username="lola_bot",
        draft=invite(template="konvert", event_date=soon(), **kw),
    )
    return page, shop, customer


async def refusal(call: Any) -> str:
    try:
        await call
    except Exception as error:  # noqa: BLE001 - the type is the assertion
        assert isinstance(error, EditRefused), repr(error)
        return error.reason
    raise AssertionError("not refused")


async def test_the_seal_is_stored_edited_and_reset(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, shop, customer = await konvert(session, db, seal_monogram="s&d")
    assert page.seal_monogram == "S&D"

    async def edit(**changes: object) -> Any:
        return await share_pages.update_page(
            session, shop_id=shop, customer_id=customer, page_id=page.id, changes=changes
        )

    assert (await edit(seal_monogram="m·a")).seal_monogram == "M·A"
    assert await refusal(edit(seal_monogram="A1")) == "invalid"
    assert (await edit(seal_monogram=None)).seal_monogram is None


async def test_a_bad_monogram_never_reaches_a_page(
    db: AsyncConnection, session: AsyncSession
) -> None:
    with pytest.raises(InvalidDraft):
        await konvert(session, db, seal_monogram="<script>")


def app_for(db: AsyncConnection) -> Any:
    return build_app(
        session_factory=bound_session_factory(db),
        notify=lambda _id, _delay: None,
        public_base_url="http://127.0.0.1:8088",
    )


def seal_of(html: str) -> str:
    found = re.search(r'<button type="button" class="(seal[^"]*)" id="seal"[^>]*>([^<]*)<', html)
    assert found is not None
    return f"{found[1]}|{found[2]}"


async def test_the_seal_shows_the_creators_letters_or_the_initials(
    db: AsyncConnection, session: AsyncSession
) -> None:
    mine, _, _ = await konvert(session, db, seal_monogram="s·d")
    plain, _, _ = await konvert(session, db, user=771)
    await session.commit()
    async with TestClient(TestServer(app_for(db))) as client:
        assert seal_of(await (await client.get(f"/p/{mine.token}")).text()) == "seal seal-long|S·D"
        # No letters typed: the couple's initials (invite() is Aziz & Malika).
        assert seal_of(await (await client.get(f"/p/{plain.token}")).text()) == (
            "seal seal-long|A&amp;M"
        )


async def test_the_seal_is_asked_for_and_skippable_in_the_bot(db: AsyncConnection) -> None:
    from tests.test_share_pages_flow import next_month

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
        PageSkipCB,
        PageTemplateCB,
        SealCB,
    )

    bot = ShopBot(db, await make_shop(db, "Lola"), bot_id=770_001, username="lola_bot")
    user = 772
    # A crafted "skip" before any seal step changes nothing.
    await bot.say(CATALOG["btn.menu.pages"]["uz"], user=user)
    await bot.tap(SealCB(action="skip").pack(), user=user)
    year, month = next_month()
    await bot.tap(PageMenuCB(action="invite").pack(), user=user)
    await bot.tap(InviteEventCB(event="birthday").pack(), user=user)
    await bot.tap(PageLangCB(lang="uz").pack(), user=user)
    await bot.say("Malika", user=user)
    await bot.tap(InviteMonthCB(year=year, month=month).pack(), user=user)
    await bot.tap(InviteDayCB(day=12).pack(), user=user)
    await bot.tap(InviteHourCB(hour=17).pack(), user=user)
    await bot.tap(InviteMinuteCB(minute=0).pack(), user=user)
    await bot.say("Toshkent, Bog'", user=user)
    await bot.tap(PageSkipCB(step="location").pack(), user=user)
    await bot.tap(PageSkipCB(step="message").pack(), user=user)
    await bot.tap(PageChoiceCB(field="rsvp", value="no").pack(), user=user)
    await bot.tap(PageTemplateCB(template="konvert").pack(), user=user)
    assert bot.last() == CATALOG["pages.ask_seal"]["uz"]
    await bot.say("A1", user=user)  # not letters: asked again, nothing stored
    assert bot.last() == CATALOG["pages.seal_invalid"]["uz"].format(max=5)
    await bot.tap(SealCB(action="skip").pack(), user=user)
    await bot.tap(PageConfirmCB(action="create").pack(), user=user)
    row = (
        await db.execute(
            text("SELECT template, seal_monogram FROM share_pages WHERE shop_id = :s"),
            {"s": bot.shop_id},
        )
    ).one()
    assert tuple(row) == ("konvert", None)
