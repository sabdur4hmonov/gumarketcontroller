"""Editing a page after it is made (CP17): same link, new content.

The service changes only what the page's kind allows, only for its own
customer in its own shop, never empties a name, a venue or the question, and
refuses an answered Ha/Yo'q page -- that answer was given to exactly that
question. The public page shows the new content at the SAME link. And through
the bot, a crafted button cannot edit someone else's page or a field the page
does not have.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
from tests.bot_harness import bound_session_factory
from tests.share_pages_harness import ShopBot
from tests.test_share_pages_service import invite, make_customer, make_shop, yesno

from gulbot.bot.callbacks import (
    EditFieldCB,
    EditValueCB,
    InviteDayCB,
    InviteHourCB,
    InviteMinuteCB,
    InviteMonthCB,
    MyPageCB,
    PageTemplateCB,
)
from gulbot.i18n.catalog import CATALOG
from gulbot.services import share_pages
from gulbot.services.share_pages import EditRefused
from gulbot.web.app import build_app

pytestmark = pytest.mark.infra

NOW = datetime.now(UTC)
HOSTILE = '<script>alert(1)</script>&"'


@pytest.fixture
async def session(db: AsyncConnection) -> AsyncSession:
    return bound_session_factory(db)()


async def made(
    session: AsyncSession, db: AsyncConnection, draft: object, *, user: int = 710
) -> tuple[Any, int, int]:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, user)
    page = await share_pages.create_page(
        session,
        shop_id=shop,
        customer_id=customer,
        bot_username="lola_bot",
        draft=draft,  # type: ignore[arg-type]
    )
    return page, shop, customer


async def refused(call: Any) -> str:
    """The SERVICE's refusal -- not the database CHECK behind it, which is the
    backstop and would also stop a bad row, but with a crash, not a reason."""
    try:
        await call
    except Exception as error:  # noqa: BLE001 - the type is the assertion
        assert isinstance(error, EditRefused), repr(error)
        return error.reason
    raise AssertionError("not refused")


def soon(days: int = 30) -> date:
    return (NOW + timedelta(days=days)).astimezone(ZoneInfo("Asia/Tashkent")).date()


async def edit(
    session: AsyncSession, page: Any, shop: int, customer: int, **changes: object
) -> Any:
    return await share_pages.update_page(
        session, shop_id=shop, customer_id=customer, page_id=page.id, changes=changes
    )


# --- the service ------------------------------------------------------------------


async def test_every_invitation_text_block_is_editable_in_place(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, shop, customer = await made(session, db, invite(event_date=soon()))
    token = page.token
    edited = await edit(
        session,
        page,
        shop,
        customer,
        title="Bizning to'yimiz",
        name_1="Sardor",
        name_2="Madina",
        message="Bir umrlik kunimiz!",
        venue="Bahor to'yxonasi",
        dress_code="Oq va oltin",
        program="18:00 kutib olish\n19:00 bazm",
        contact="Aziz aka",
        closing="Kutib qolamiz!",
    )
    assert edited.token == token and edited.id == page.id
    assert (edited.title, edited.name_1, edited.name_2) == ("Bizning to'yimiz", "Sardor", "Madina")
    assert edited.program == "18:00 kutib olish\n19:00 bazm"
    assert (edited.dress_code, edited.contact, edited.closing) == (
        "Oq va oltin",
        "Aziz aka",
        "Kutib qolamiz!",
    )
    assert edited.edited_at is not None


async def test_text_is_cleaned_and_capped_as_at_creation(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, shop, customer = await made(session, db, invite(event_date=soon()))
    edited = await edit(session, page, shop, customer, title="  x‮" + "y" * 200, contact="a\x00b")
    assert edited.title == "x" + "y" * 79
    assert edited.contact == "ab"


async def test_a_preset_field_can_go_back_to_its_preset(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, shop, customer = await made(session, db, invite(event_date=soon()))
    await edit(session, page, shop, customer, title="Mine", closing="Mine too")
    edited = await edit(session, page, shop, customer, title=None, closing=None)
    assert edited.title is None and edited.closing is None
    assert share_pages.effective_text(edited, "title") == "To'y"
    assert share_pages.effective_text(edited, "closing") == "Sizni intizorlik bilan kutamiz!"


@pytest.mark.parametrize("field", ["name_1", "venue"])
async def test_a_name_or_the_venue_can_never_be_emptied(
    db: AsyncConnection, session: AsyncSession, field: str
) -> None:
    page, shop, customer = await made(session, db, invite(event_date=soon()))
    assert await refused(edit(session, page, shop, customer, **{field: "   "})) == "invalid"


@pytest.mark.parametrize(
    "changes",
    [
        {"venue": "x"},  # a yesno page has no venue
        {"template": "evil"},
        {"lang": "de"},
        {"notify_creator": "yes"},
        {},
    ],
)
async def test_values_and_fields_the_page_does_not_have_are_refused(
    db: AsyncConnection, session: AsyncSession, changes: dict[str, object]
) -> None:
    page, shop, customer = await made(session, db, yesno())
    assert await refused(edit(session, page, shop, customer, **changes)) == "invalid"


async def test_moving_the_date_moves_the_expiry_and_stays_in_the_window(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, shop, customer = await made(session, db, invite(event_date=soon(10)))
    before = page.expires_at
    edited = await edit(session, page, shop, customer, event_at=(soon(40), time(19, 30)))
    assert edited.event_date == soon(40) and edited.event_time == time(19, 30)
    assert edited.expires_at - before == timedelta(days=30)
    with pytest.raises(EditRefused):
        await edit(session, page, shop, customer, event_at=(soon(-3), time(19, 0)))


async def test_the_map_pin_can_be_moved_and_removed(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, shop, customer = await made(session, db, invite(event_date=soon()))
    edited = await edit(session, page, shop, customer, location=(Decimal("41.1"), Decimal("69.2")))
    assert edited.location_lat == Decimal("41.1")
    edited = await edit(session, page, shop, customer, location=None)
    assert edited.location_lat is None and edited.location_lon is None
    with pytest.raises(EditRefused):
        await edit(session, page, shop, customer, location=(Decimal("95"), Decimal("0")))


async def test_a_yesno_page_is_editable_until_it_is_answered(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, shop, customer = await made(session, db, yesno())
    edited = await edit(
        session, page, shop, customer, question="Kinoga boramizmi?", template="tungi"
    )
    assert (edited.question, edited.question_preset, edited.template) == (
        "Kinoga boramizmi?",
        "custom",
        "tungi",
    )
    await share_pages.answer_yes(session, page.token)
    with pytest.raises(EditRefused) as refused:
        await edit(session, page, shop, customer, template="pastel")
    assert refused.value.reason == "locked"


async def test_a_ready_question_follows_the_page_into_a_new_language(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, shop, customer = await made(session, db, yesno())
    edited = await edit(session, page, shop, customer, lang="en")
    assert edited.question == "Will you marry me?"


async def test_nobody_else_can_edit(db: AsyncConnection, session: AsyncSession) -> None:
    page, shop, customer = await made(session, db, invite(event_date=soon()))
    neighbour = await make_customer(db, shop, 711)
    other_shop = await make_shop(db, "B")
    same_person_elsewhere = await make_customer(db, other_shop, 710)
    for s, c in ((shop, neighbour), (other_shop, same_person_elsewhere), (other_shop, customer)):
        with pytest.raises(EditRefused) as refused:
            await share_pages.update_page(
                session, shop_id=s, customer_id=c, page_id=page.id, changes={"title": "hacked"}
            )
        assert refused.value.reason == "gone"
    await session.refresh(page)
    assert page.title is None


async def test_a_deleted_page_cannot_be_edited_and_its_new_fields_are_scrubbed(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, shop, customer = await made(session, db, invite(event_date=soon()))
    await edit(
        session, page, shop, customer, dress_code="Oq", contact="Aziz", closing="!", title="T"
    )
    await share_pages.delete_page(session, shop_id=shop, customer_id=customer, page_id=page.id)
    await session.refresh(page)
    assert (page.title, page.dress_code, page.program, page.contact, page.closing) == (None,) * 5
    with pytest.raises(EditRefused):
        await edit(session, page, shop, customer, title="again")


# --- the public page: same link, new content ------------------------------------------


async def test_the_same_link_shows_the_new_content_escaped(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, shop, customer = await made(session, db, invite(event_date=soon()))
    await session.commit()
    app = build_app(
        session_factory=bound_session_factory(db),
        notify=lambda _id, _delay: None,
        public_base_url="http://127.0.0.1:8088",
    )
    async with TestClient(TestServer(app)) as client:
        before = await (await client.get(f"/p/{page.token}")).text()
        await edit(
            session,
            page,
            shop,
            customer,
            title="Bizning kun",
            dress_code=HOSTILE,
            program="18:00\n19:00",
            closing="Kutamiz!",
        )
        await session.commit()
        after = await (await client.get(f"/p/{page.token}")).text()
    assert "Bizning kun" not in before and "Bizning kun" in after
    # No closing written yet: the event type's preset closes the card.
    assert "Sizni intizorlik bilan kutamiz!" in before
    assert "Kutamiz!" in after and "18:00\n19:00" in after
    assert "<script>alert" not in after and "&lt;script&gt;" in after
    assert " style=" not in after


# --- through the bot -------------------------------------------------------------------


async def page_of_bot(db: AsyncConnection, bot: ShopBot, user: int, draft: object) -> Any:
    await bot.say(CATALOG["btn.menu.help"]["uz"], user=user)
    customer = await db.scalar(
        text("SELECT id FROM customers WHERE shop_id = :s AND telegram_user_id = :u"),
        {"s": bot.shop_id, "u": user},
    )
    session = bound_session_factory(db)()
    page = await share_pages.create_page(
        session,
        shop_id=bot.shop_id,
        customer_id=int(customer),
        bot_username="lola_bot",
        draft=draft,  # type: ignore[arg-type]
    )
    await session.commit()
    return page


async def test_editing_a_title_through_the_bot_keeps_the_link(db: AsyncConnection) -> None:
    bot = ShopBot(db, await make_shop(db, "Lola"), bot_id=720_001, username="lola_bot")
    page = await page_of_bot(db, bot, 720, invite(event_date=soon()))
    await bot.tap(MyPageCB(action="edit", page_id=page.id).pack(), user=720)
    assert bot.last() == CATALOG["pages.edit_menu"]["uz"]
    await bot.tap(EditFieldCB(page_id=page.id, field="title").pack(), user=720)
    await bot.say("Sardor va Madina to'yi", user=720)
    title, token = (
        await db.execute(text("SELECT title, token FROM share_pages WHERE id = :i"), {"i": page.id})
    ).one()
    assert title == "Sardor va Madina to'yi" and token == page.token
    assert any(f"/p/{page.token}" in body for body in bot.texts())


async def test_reset_and_toggles_and_pickers_through_the_bot(db: AsyncConnection) -> None:
    bot = ShopBot(db, await make_shop(db, "Lola"), bot_id=720_002, username="lola_bot")
    page = await page_of_bot(db, bot, 721, invite(event_date=soon(), rsvp_enabled=True))
    await bot.tap(EditFieldCB(page_id=page.id, field="rsvp_enabled").pack(), user=721)
    await bot.tap(EditFieldCB(page_id=page.id, field="template").pack(), user=721)
    await bot.tap(PageTemplateCB(template="tungi").pack(), user=721)
    target = soon(50)
    await bot.tap(EditFieldCB(page_id=page.id, field="event_at").pack(), user=721)
    await bot.tap(InviteMonthCB(year=target.year, month=target.month).pack(), user=721)
    await bot.tap(InviteDayCB(day=target.day).pack(), user=721)
    await bot.tap(InviteHourCB(hour=20).pack(), user=721)
    await bot.tap(InviteMinuteCB(minute=15).pack(), user=721)
    await bot.tap(EditFieldCB(page_id=page.id, field="closing").pack(), user=721)
    await bot.say("Albatta keling!", user=721)
    await bot.tap(EditFieldCB(page_id=page.id, field="closing").pack(), user=721)
    await bot.tap(EditValueCB(action="reset").pack(), user=721)
    row = (
        await db.execute(
            text(
                "SELECT rsvp_enabled, template, event_date, event_time, closing "
                "FROM share_pages WHERE id = :i"
            ),
            {"i": page.id},
        )
    ).one()
    assert row == (False, "tungi", target, time(20, 15), None)


async def test_an_answered_yesno_page_says_why_it_cannot_be_edited(db: AsyncConnection) -> None:
    bot = ShopBot(db, await make_shop(db, "Lola"), bot_id=720_003, username="lola_bot")
    page = await page_of_bot(db, bot, 722, yesno())
    session = bound_session_factory(db)()
    await share_pages.answer_yes(session, page.token)
    await session.commit()
    await bot.tap(MyPageCB(action="edit", page_id=page.id).pack(), user=722)
    assert bot.last() == CATALOG["pages.edit_locked"]["uz"]
    await bot.tap(EditFieldCB(page_id=page.id, field="template").pack(), user=722)
    assert bot.last() == CATALOG["pages.edit_locked"]["uz"]


async def test_a_crafted_edit_button_cannot_touch_another_shops_page(db: AsyncConnection) -> None:
    a = ShopBot(db, await make_shop(db, "A"), bot_id=720_004, username="a_bot")
    b = ShopBot(db, await make_shop(db, "B"), bot_id=720_005, username="b_bot")
    page = await page_of_bot(db, a, 723, invite(event_date=soon()))
    await b.say(CATALOG["btn.menu.help"]["uz"], user=723)
    b.clear()
    await b.tap(EditFieldCB(page_id=page.id, field="title").pack(), user=723)
    assert b.last() == CATALOG["pages.gone"]["uz"]  # not even a prompt for it
    await b.say("hacked", user=723)
    await b.tap(MyPageCB(action="edit", page_id=page.id).pack(), user=723)
    assert CATALOG["pages.gone"]["uz"] in b.texts()
    title = await db.scalar(text("SELECT title FROM share_pages WHERE id = :i"), {"i": page.id})
    assert title is None


async def test_a_field_the_page_does_not_have_is_ignored(db: AsyncConnection) -> None:
    bot = ShopBot(db, await make_shop(db, "Lola"), bot_id=720_006, username="lola_bot")
    page = await page_of_bot(db, bot, 724, yesno())
    bot.clear()
    await bot.tap(EditFieldCB(page_id=page.id, field="venue").pack(), user=724)
    await bot.say("Restoran", user=724)
    venue = await db.scalar(text("SELECT venue FROM share_pages WHERE id = :i"), {"i": page.id})
    assert venue is None
