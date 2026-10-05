"""The guest wishes wall (CP17): public input, bounded and escaped; the
creator hides any wish from the bot; nobody else can touch the wall."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
from tests.bot_harness import bound_session_factory
from tests.share_pages_harness import ShopBot
from tests.test_share_pages_service import invite, make_customer, make_shop, yesno

from gulbot.bot.callbacks import EditFieldCB, WishCB
from gulbot.i18n.catalog import CATALOG
from gulbot.services import share_page_wishes, share_pages
from gulbot.services.share_page_wishes import WISHES_PER_GUEST, WishRefused
from gulbot.web.app import build_app

pytestmark = pytest.mark.infra

JSON_HEADERS = {"Content-Type": "application/json", "X-Requested-With": "gulbot"}
HOSTILE = '<img src=x onerror=alert(1)>"&'


def soon(days: int = 30) -> date:
    return (datetime.now(UTC) + timedelta(days=days)).astimezone(ZoneInfo("Asia/Tashkent")).date()


@pytest.fixture
async def session(db: AsyncConnection) -> AsyncSession:
    return bound_session_factory(db)()


async def wall(
    session: AsyncSession, db: AsyncConnection, *, user: int = 750, on: bool = True
) -> tuple[Any, int, int]:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, user)
    page = await share_pages.create_page(
        session,
        shop_id=shop,
        customer_id=customer,
        bot_username="lola_bot",
        draft=invite(event_date=soon()),
    )
    if on:
        await share_pages.update_page(
            session,
            shop_id=shop,
            customer_id=customer,
            page_id=page.id,
            changes={"wishes_enabled": True},
        )
    return page, shop, customer


async def refusal(call: Any) -> str:
    try:
        await call
    except Exception as error:  # noqa: BLE001 - the type is the assertion
        assert isinstance(error, WishRefused), repr(error)
        return error.reason
    raise AssertionError("not refused")


async def leave(session: AsyncSession, page: Any, voter: str = "v" * 22, **kw: object) -> Any:
    return await share_page_wishes.leave_wish(
        session,
        page.token,
        voter_key=voter,
        author=kw.get("author", "Dilnoza"),
        body=kw.get("body", "Baxtli bo'linglar!"),
    )


# --- the service ---------------------------------------------------------------------


async def test_a_wish_is_cleaned_capped_and_shown_newest_first(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, _, _ = await wall(session, db)
    first = await leave(session, page, author="  Dilnoza‮ ", body="x" * 400)
    assert first.author == "Dilnoza" and len(first.body) == 300
    await leave(session, page, voter="w" * 22, author="Aziz", body="Qutlug' bo'lsin")
    shown = await share_page_wishes.visible_wishes(session, page_id=page.id)
    assert [w.author for w in shown] == ["Aziz", "Dilnoza"]


@pytest.mark.parametrize(
    ("author", "body"), [("", "Tabriklayman"), ("Aziz", "   "), (None, "x"), ("Aziz", 5)]
)
async def test_an_empty_or_odd_wish_is_refused(
    db: AsyncConnection, session: AsyncSession, author: object, body: object
) -> None:
    page, _, _ = await wall(session, db)
    assert await refusal(leave(session, page, author=author, body=body)) == "invalid"


async def test_the_wall_is_closed_until_it_is_switched_on(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, _, _ = await wall(session, db, on=False)
    assert await refusal(leave(session, page)) == "page"


async def test_only_a_live_invitation_takes_a_wish(
    db: AsyncConnection, session: AsyncSession
) -> None:
    """The wall's other two doors, each forced open in the database: an
    invitation past its expiry, and a Ha/Yo'q page with the switch on (no
    flow sets it today -- this keeps a future one from opening a wall there)."""
    expired, _, _ = await wall(session, db)
    await db.execute(
        text("UPDATE share_pages SET expires_at = now() - interval '1 minute' WHERE id = :i"),
        {"i": expired.id},
    )
    assert await refusal(leave(session, expired)) == "page"

    shop = await make_shop(db)
    customer = await make_customer(db, shop, 754)
    question = await share_pages.create_page(
        session, shop_id=shop, customer_id=customer, bot_username="lola_bot", draft=yesno()
    )
    await db.execute(
        text("UPDATE share_pages SET wishes_enabled = true WHERE id = :i"), {"i": question.id}
    )
    assert await refusal(leave(session, question)) == "page"


async def test_one_guest_leaves_a_few_wishes_not_a_flood(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, _, _ = await wall(session, db)
    for _ in range(WISHES_PER_GUEST):
        await leave(session, page)
    assert await refusal(leave(session, page)) == "full"
    await leave(session, page, voter="w" * 22)  # another guest still can


async def test_the_page_has_a_ceiling(
    db: AsyncConnection, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(share_page_wishes, "WISHES_PER_PAGE", 2)
    page, _, _ = await wall(session, db)
    await leave(session, page, voter="a" * 22)
    await leave(session, page, voter="b" * 22)
    assert await refusal(leave(session, page, voter="c" * 22)) == "full"


async def test_only_the_creator_hides_a_wish(db: AsyncConnection, session: AsyncSession) -> None:
    page, shop, customer = await wall(session, db)
    await leave(session, page)
    [own] = await share_page_wishes.wishes_for_creator(
        session, shop_id=shop, customer_id=customer, page_id=page.id
    ) or [None]
    assert own is not None
    other_shop = await make_shop(db, "B")
    stranger = await make_customer(db, other_shop, 750)
    neighbour = await make_customer(db, shop, 751)
    # (other shop, the owner's id) is what only the shop filter stops.
    for s, c in ((other_shop, stranger), (shop, neighbour), (other_shop, customer)):
        assert not await share_page_wishes.set_hidden(
            session, shop_id=s, customer_id=c, page_id=page.id, wish_id=own.id, hidden=True
        )
        assert (
            await share_page_wishes.wishes_for_creator(
                session, shop_id=s, customer_id=c, page_id=page.id
            )
            is None
        )
    assert len(await share_page_wishes.visible_wishes(session, page_id=page.id)) == 1
    assert await share_page_wishes.set_hidden(
        session, shop_id=shop, customer_id=customer, page_id=page.id, wish_id=own.id, hidden=True
    )
    assert await share_page_wishes.visible_wishes(session, page_id=page.id) == []


async def test_a_wish_id_from_another_page_hides_nothing(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, shop, customer = await wall(session, db)
    other, other_shop, other_customer = await wall(session, db, user=752)
    await leave(session, other)
    [foreign] = await share_page_wishes.wishes_for_creator(
        session, shop_id=other_shop, customer_id=other_customer, page_id=other.id
    ) or [None]
    assert foreign is not None
    # The owner of `page` names their own page but the other page's wish.
    assert not await share_page_wishes.set_hidden(
        session,
        shop_id=shop,
        customer_id=customer,
        page_id=page.id,
        wish_id=foreign.id,
        hidden=True,
    )
    assert len(await share_page_wishes.visible_wishes(session, page_id=other.id)) == 1


async def test_deleting_the_page_deletes_its_wishes(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, shop, customer = await wall(session, db)
    await leave(session, page)
    await share_pages.delete_page(session, shop_id=shop, customer_id=customer, page_id=page.id)
    left = await db.scalar(
        text("SELECT count(*) FROM share_page_wishes WHERE page_id = :p"), {"p": page.id}
    )
    assert left == 0


# --- on the page --------------------------------------------------------------------------


def app_for(db: AsyncConnection, **kw: Any) -> Any:
    return build_app(
        session_factory=bound_session_factory(db),
        notify=lambda _id, _delay: None,
        public_base_url="http://127.0.0.1:8088",
        **kw,
    )


async def test_a_guest_leaves_a_wish_through_the_page_and_it_shows_escaped(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, _, _ = await wall(session, db)
    await session.commit()
    async with TestClient(TestServer(app_for(db))) as client:
        html = await (await client.get(f"/p/{page.token}")).text()
        assert 'id="wish-form"' in html and CATALOG_EMPTY in html
        response = await client.post(
            f"/p/{page.token}/wish",
            data=json.dumps({"name": "Mehmon", "text": HOSTILE}),
            headers=JSON_HEADERS,
        )
        assert response.status == 200
        assert (await response.json())["text"] == HOSTILE  # text, for textContent
        assert "Set-Cookie" in response.headers
        after = await (await client.get(f"/p/{page.token}")).text()
        assert "<img src=x" not in after and "&lt;img src=x onerror=alert(1)&gt;" in after
        # Same-origin only, JSON only, values only.
        no_header = await client.post(f"/p/{page.token}/wish", json={"name": "a", "text": "b"})
        assert no_header.status == 403
        bad = await client.post(
            f"/p/{page.token}/wish", data='{"name": "", "text": "b"}', headers=JSON_HEADERS
        )
        assert bad.status == 400


CATALOG_EMPTY = "Birinchi bo&#39;lib tilak qoldiring!"


async def test_a_closed_wall_shows_no_form_and_takes_no_wish(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, _, _ = await wall(session, db, on=False)
    await session.commit()
    async with TestClient(TestServer(app_for(db))) as client:
        html = await (await client.get(f"/p/{page.token}")).text()
        assert 'id="wish-form"' not in html
        response = await client.post(
            f"/p/{page.token}/wish",
            data=json.dumps({"name": "a", "text": "b"}),
            headers=JSON_HEADERS,
        )
        assert response.status == 404


async def test_wishes_are_rate_limited_per_address(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, _, _ = await wall(session, db)
    await session.commit()
    async with TestClient(TestServer(app_for(db, wish_limit=2))) as client:
        statuses = [
            (
                await client.post(
                    f"/p/{page.token}/wish",
                    data=json.dumps({"name": "a", "text": "b"}),
                    headers=JSON_HEADERS,
                )
            ).status
            for _ in range(3)
        ]
    assert statuses[:2] == [200, 200] and statuses[2] == 429


# --- through the bot -------------------------------------------------------------------------


async def bot_wall(db: AsyncConnection, bot: ShopBot, user: int) -> Any:
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


async def hidden_of(db: AsyncConnection, page: Any) -> list[bool]:
    rows = await db.execute(
        text("SELECT hidden FROM share_page_wishes WHERE page_id = :p ORDER BY id"), {"p": page.id}
    )
    return [bool(r[0]) for r in rows]


async def test_the_creator_switches_the_wall_and_hides_a_wish_in_the_bot(
    db: AsyncConnection,
) -> None:
    bot = ShopBot(db, await make_shop(db, "Lola"), bot_id=750_001, username="lola_bot")
    page = await bot_wall(db, bot, 753)
    await bot.tap(EditFieldCB(page_id=page.id, field="wishes_enabled").pack(), user=753)
    assert await db.scalar(
        text("SELECT wishes_enabled FROM share_pages WHERE id = :i"), {"i": page.id}
    )
    session = bound_session_factory(db)()
    await leave(session, page, author="<b>Aziz</b>", body="Baxtli bo'linglar!")
    await session.commit()
    await bot.tap(EditFieldCB(page_id=page.id, field="wishes").pack(), user=753)
    assert "&lt;b&gt;Aziz&lt;/b&gt;" in bot.last() and "Baxtli" in bot.last()
    wish_id = await db.scalar(
        text("SELECT id FROM share_page_wishes WHERE page_id = :p"), {"p": page.id}
    )
    await bot.tap(WishCB(page_id=page.id, wish_id=wish_id, action="hide").pack(), user=753)
    assert await hidden_of(db, page) == [True]
    assert "🙈" in bot.last()
    await bot.tap(WishCB(page_id=page.id, wish_id=wish_id, action="show").pack(), user=753)
    assert await hidden_of(db, page) == [False]


async def test_another_shops_bot_cannot_read_or_hide_the_wishes(db: AsyncConnection) -> None:
    a = ShopBot(db, await make_shop(db, "A"), bot_id=750_002, username="a_bot")
    b = ShopBot(db, await make_shop(db, "B"), bot_id=750_003, username="b_bot")
    page = await bot_wall(db, a, 754)
    session = bound_session_factory(db)()
    await share_pages.update_page(
        session,
        shop_id=a.shop_id,
        customer_id=page.customer_id,
        page_id=page.id,
        changes={"wishes_enabled": True},
    )
    await leave(session, page, body="Sirli tilak")
    await session.commit()
    wish_id = await db.scalar(
        text("SELECT id FROM share_page_wishes WHERE page_id = :p"), {"p": page.id}
    )
    await b.say(CATALOG["btn.menu.help"]["uz"], user=754)
    b.clear()
    await b.tap(EditFieldCB(page_id=page.id, field="wishes").pack(), user=754)
    await b.tap(WishCB(page_id=page.id, wish_id=wish_id, action="hide").pack(), user=754)
    assert all("Sirli tilak" not in body for body in b.texts())
    assert CATALOG["pages.gone"]["uz"] in b.texts()
    assert await hidden_of(db, page) == [False]
