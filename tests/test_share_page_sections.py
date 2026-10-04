"""A taklifnoma's optional sections (CP17): programme rows, dress-code colours,
and the countdown and gallery switched on and off -- stored only in the shape
the page can show, editable in place, scoped like every other edit."""

from __future__ import annotations

import io
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
from tests.bot_harness import bound_session_factory
from tests.share_pages_harness import ShopBot
from tests.test_share_pages_service import invite, make_customer, make_shop

from gulbot.bot.callbacks import ColorCB, EditFieldCB
from gulbot.i18n.catalog import CATALOG
from gulbot.services import share_page_photos, share_pages
from gulbot.services.share_pages import EditRefused
from gulbot.web import sections
from gulbot.web.app import build_app
from gulbot.web.render import STATIC
from gulbot.web.sections import ProgramRefused, normalise_program, program_rows

pytestmark = pytest.mark.infra


# --- the programme --------------------------------------------------------------------


def test_programme_lines_are_stored_as_rows() -> None:
    stored = normalise_program("18:00 Kutib olish\n\n 9.30 -  Nonushta \nRaqslar")
    assert stored == "18:00 Kutib olish\n09:30 Nonushta\nRaqslar"
    assert program_rows(stored) == [
        ("18:00", "Kutib olish"),
        ("09:30", "Nonushta"),
        ("", "Raqslar"),
    ]


@pytest.mark.parametrize(
    "written",
    [
        "25:00 Tun",  # not a time
        "18:61 Ziyofat",
        "18:00",  # a time with nothing after it
        "\n".join(f"1{n}:00 Band" for n in range(9)),  # nine rows
        "18:00 " + "x" * (sections.PROGRAM_ITEM_MAX + 1),
    ],
)
def test_a_programme_that_cannot_be_shown_is_refused(written: str) -> None:
    with pytest.raises(ProgramRefused):
        normalise_program(written)


# --- the colours ---------------------------------------------------------------------


def test_colours_are_palette_keys_only() -> None:
    assert sections.checked_colors(("oq", "oltin")) == "oq,oltin"
    assert sections.checked_colors(()) is None and sections.checked_colors(None) is None
    for bad in (("oq", "oq"), ("teal",), tuple(sections.DRESS_PALETTE)[:6], "oq", (1,)):
        with pytest.raises(ValueError):
            sections.checked_colors(bad)
    assert sections.colors_of("oq,gone,oltin") == ["oq", "oltin"]


def test_every_palette_colour_is_a_class_in_the_stylesheet() -> None:
    """The page carries no inline style (CSP style-src 'self'): each colour
    must exist in base.css, with the same value as the palette."""
    css = (STATIC / "css" / "base.css").read_text(encoding="utf-8")
    for key, (hex_value, _names) in sections.DRESS_PALETTE.items():
        rule = re.search(rf"\.sw-{key} \{{\s*background: ([^;]+);", css)
        assert rule is not None and rule[1] == hex_value, key


# --- stored through the service -----------------------------------------------------------


@pytest.fixture
async def session(db: AsyncConnection) -> AsyncSession:
    return bound_session_factory(db)()


def soon(days: int = 30) -> date:
    return (datetime.now(UTC) + timedelta(days=days)).astimezone(ZoneInfo("Asia/Tashkent")).date()


async def made(session: AsyncSession, db: AsyncConnection, user: int = 740) -> tuple[Any, int, int]:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, user)
    page = await share_pages.create_page(
        session,
        shop_id=shop,
        customer_id=customer,
        bot_username="lola_bot",
        draft=invite(event_date=soon()),
    )
    return page, shop, customer


async def edit(
    session: AsyncSession, page: Any, shop: int, customer: int, **changes: object
) -> Any:
    return await share_pages.update_page(
        session, shop_id=shop, customer_id=customer, page_id=page.id, changes=changes
    )


async def refusal(call: Any) -> str:
    try:
        await call
    except Exception as error:  # noqa: BLE001 - the type is the assertion
        assert isinstance(error, EditRefused), repr(error)
        return error.reason
    raise AssertionError("not refused")


async def test_sections_are_stored_and_switched_in_place(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, shop, customer = await made(session, db)
    assert page.show_countdown and page.show_gallery and page.dress_colors is None
    edited = await edit(
        session,
        page,
        shop,
        customer,
        program="18:00 Kutib olish",
        dress_colors=("oltin", "oq"),
        show_countdown=False,
        show_gallery=False,
    )
    assert edited.token == page.token
    assert edited.program == "18:00 Kutib olish" and edited.dress_colors == "oltin,oq"
    assert not edited.show_countdown and not edited.show_gallery
    assert (await edit(session, page, shop, customer, dress_colors=None)).dress_colors is None


@pytest.mark.parametrize(
    "changes",
    [
        {"program": "25:00 Tun"},
        {"dress_colors": ("teal",)},
        {"dress_colors": ("oq", "oq")},
        {"dress_colors": "oq"},
        {"show_countdown": "no"},
    ],
)
async def test_what_the_bot_could_not_send_is_refused(
    db: AsyncConnection, session: AsyncSession, changes: dict[str, object]
) -> None:
    page, shop, customer = await made(session, db)
    assert await refusal(edit(session, page, shop, customer, **changes)) == "invalid"


async def test_the_database_keeps_the_colours_shape(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, _, _ = await made(session, db)
    with pytest.raises(Exception, match="ck_share_pages_dress_colors_shape"):
        async with db.begin_nested():
            await db.execute(
                text("UPDATE share_pages SET dress_colors = :c WHERE id = :i"),
                {"c": "a,b,c,d,e,f", "i": page.id},
            )


async def test_deleting_the_page_forgets_its_colours(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, shop, customer = await made(session, db)
    await edit(session, page, shop, customer, dress_colors=("oq",), program="18:00 Kutib olish")
    await share_pages.delete_page(session, shop_id=shop, customer_id=customer, page_id=page.id)
    row = (
        await db.execute(
            text("SELECT dress_colors, program FROM share_pages WHERE id = :i"), {"i": page.id}
        )
    ).one()
    assert row == (None, None)


# --- on the page ---------------------------------------------------------------------------


def small_jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (300, 400), (120, 160, 120)).save(out, format="JPEG")
    return out.getvalue()


async def test_the_page_shows_only_what_is_switched_on(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, shop, customer = await made(session, db)
    await share_page_photos.store_photo(
        session, shop_id=shop, customer_id=customer, page_id=page.id, raw=small_jpeg()
    )
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
            dress_colors=("oltin", "lavanda"),
            show_countdown=False,
            show_gallery=False,
        )
        await session.commit()
        after = await (await client.get(f"/p/{page.token}")).text()
    assert 'id="countdown"' in before and 'class="gallery"' in before
    assert 'id="countdown"' not in after and 'class="gallery"' not in after
    assert '<span class="sw sw-oltin" aria-hidden="true"></span>Oltin' in after
    assert '<span class="sw sw-lavanda" aria-hidden="true"></span>Lavanda' in after
    assert " style=" not in after


# --- through the bot -------------------------------------------------------------------------


async def bot_page(db: AsyncConnection, bot: ShopBot, user: int) -> Any:
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
        draft=invite(event_date=soon()),
    )
    await session.commit()
    return page


async def column(db: AsyncConnection, page: Any, name: str) -> Any:
    return await db.scalar(text(f"SELECT {name} FROM share_pages WHERE id = :i"), {"i": page.id})


async def test_colours_are_picked_in_the_bot_up_to_five(db: AsyncConnection) -> None:
    bot = ShopBot(db, await make_shop(db, "Lola"), bot_id=740_001, username="lola_bot")
    page = await bot_page(db, bot, 741)
    await bot.tap(EditFieldCB(page_id=page.id, field="dress_colors").pack(), user=741)
    for key in ("oq", "oltin", "pushti", "oltin", "kok", "yashil", "bej", "qora"):
        await bot.tap(ColorCB(color=key).pack(), user=741)
    await bot.tap(ColorCB(color="done").pack(), user=741)
    # oltin toggled off again; the sixth pick (qora) refused.
    assert await column(db, page, "dress_colors") == "oq,pushti,kok,yashil,bej"
    # The palette is closed now: a stray tap changes nothing -- not even in
    # the middle of another edit of the same page.
    await bot.tap(ColorCB(color="none").pack(), user=741)
    await bot.tap(EditFieldCB(page_id=page.id, field="title").pack(), user=741)
    await bot.tap(ColorCB(color="none").pack(), user=741)
    assert await column(db, page, "dress_colors") == "oq,pushti,kok,yashil,bej"


async def test_sections_switch_and_the_programme_is_written_in_the_bot(
    db: AsyncConnection,
) -> None:
    bot = ShopBot(db, await make_shop(db, "Lola"), bot_id=740_002, username="lola_bot")
    page = await bot_page(db, bot, 742)
    await bot.tap(EditFieldCB(page_id=page.id, field="show_countdown").pack(), user=742)
    await bot.tap(EditFieldCB(page_id=page.id, field="show_gallery").pack(), user=742)
    assert await column(db, page, "show_countdown") is False
    assert await column(db, page, "show_gallery") is False
    await bot.tap(EditFieldCB(page_id=page.id, field="program").pack(), user=742)
    assert any(CATALOG["pages.edit_program_hint"]["uz"] in body for body in bot.texts())
    await bot.say("18:00 Kutib olish\n19.30 Ziyofat", user=742)
    assert await column(db, page, "program") == "18:00 Kutib olish\n19:30 Ziyofat"
    await bot.tap(EditFieldCB(page_id=page.id, field="program").pack(), user=742)
    await bot.say("25:00 Tun", user=742)
    assert bot.last() == CATALOG["pages.edit_invalid"]["uz"]
    assert await column(db, page, "program") == "18:00 Kutib olish\n19:30 Ziyofat"


async def test_another_shops_bot_cannot_open_the_palette(db: AsyncConnection) -> None:
    a = ShopBot(db, await make_shop(db, "A"), bot_id=740_003, username="a_bot")
    b = ShopBot(db, await make_shop(db, "B"), bot_id=740_004, username="b_bot")
    page = await bot_page(db, a, 743)
    await b.say(CATALOG["btn.menu.help"]["uz"], user=743)
    await b.tap(EditFieldCB(page_id=page.id, field="dress_colors").pack(), user=743)
    assert b.last() == CATALOG["pages.gone"]["uz"]
    await b.tap(ColorCB(color="oq").pack(), user=743)
    await b.tap(ColorCB(color="done").pack(), user=743)
    await b.tap(EditFieldCB(page_id=page.id, field="show_countdown").pack(), user=743)
    assert await column(db, page, "dress_colors") is None
    assert await column(db, page, "show_countdown") is True
