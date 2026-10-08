# ruff: noqa: F811, F401  -- fixtures are imported by name; pytest injects them into
# the same-named test parameters, which ruff reads as a redefinition.
"""CP18: a shop's lifecycle status, and what `paused` actually stops.

The spec's warning, taken as the requirement: "A panel-only flag that the
workers ignore is worse than none." So every path that acts FOR a shop toward
its customers honours `paused` -- the reminder tick, the shop's own bot, and
the public page's "order flowers" link -- and these tests prove each one,
with an active shop beside it as the control.

What pause deliberately does NOT stop (decisions in CHECKPOINTS.md, CP18):
the shop's own group, so orders already placed can still be confirmed and
their delivery pings still arrive; and the public pages themselves.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import bound_session_factory
from tests.share_pages_harness import ShopBot, make_shop
from tests.test_dispatcher import NOW, add_due_row, world
from tests.test_share_pages_service import make_customer, yesno

from gulbot.i18n.catalog import CATALOG
from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.sending.dispatcher import select_due_rows
from gulbot.services import share_pages
from gulbot.web.app import build_app

pytestmark = pytest.mark.infra

PAUSED_UZ = CATALOG["shop.paused"]["uz"] if "shop.paused" in CATALOG else "<shop.paused>"


async def set_status(db: AsyncConnection, shop_id: int, status: str) -> None:
    await db.execute(
        text("UPDATE shops SET status = :st WHERE id = :s"), {"st": status, "s": shop_id}
    )


# --- the column ------------------------------------------------------------------


async def test_a_new_shop_is_active_and_an_unknown_status_is_refused(db: AsyncConnection) -> None:
    shop = await make_shop(db, "Status shop")
    assert await db.scalar(text("SELECT status FROM shops WHERE id = :s"), {"s": shop}) == "active"
    try:
        async with db.begin_nested():
            await set_status(db, shop, "closed")
    except Exception as error:  # noqa: BLE001 - the constraint's name is the assertion
        refused = str(error)
    else:
        refused = ""
    assert "ck_shops_status_known" in refused, refused or "'closed' was accepted"


# --- the reminder tick ------------------------------------------------------------


async def test_a_paused_shops_reminders_wait_and_resume_sends_them(
    db: AsyncConnection, world: dict[str, Any]
) -> None:
    await add_due_row(db, world)
    sessions = bound_session_factory(db)

    await set_status(db, world["shop_id"], "paused")
    async with sessions() as session:
        while_paused = [r.shop_id for r in await select_due_rows(session, now_utc=NOW)]
    assert world["shop_id"] not in while_paused, "a paused shop's reminder was selected"
    state = await db.scalar(
        text("SELECT state FROM scheduled_notifications WHERE shop_id = :s"),
        {"s": world["shop_id"]},
    )
    assert state == "pending", "pausing must leave the reminder waiting, not spend it"

    await set_status(db, world["shop_id"], "active")
    async with sessions() as session:
        resumed = [r.shop_id for r in await select_due_rows(session, now_utc=NOW)]
    assert world["shop_id"] in resumed


# --- the shop's own bot -------------------------------------------------------------


async def test_a_paused_shops_bot_tells_its_customer_and_does_nothing_else(
    db: AsyncConnection,
) -> None:
    paused = ShopBot(db, await make_shop(db, "Paused"), bot_id=520_001, username="paused_bot")
    active = ShopBot(db, await make_shop(db, "Active"), bot_id=520_002, username="active_bot")
    await set_status(db, paused.shop_id, "paused")

    for bot in (paused, active):
        await bot.say("/start", user=990_201)

    assert paused.texts() == [PAUSED_UZ], paused.texts()
    assert active.texts() and PAUSED_UZ not in active.texts()
    # Nothing behind the gate ran: not even the customer row was created.
    created = await db.scalar(
        text("SELECT count(*) FROM customers WHERE shop_id = :s"), {"s": paused.shop_id}
    )
    assert created == 0


async def test_a_paused_shops_group_is_still_served(db: AsyncConnection) -> None:
    """Orders already placed must still be confirmable: the gate is for
    customers, in private chats, and lets the shop's own group through."""
    from gulbot.bot.middlewares import ShopPausedMiddleware

    shop = await make_shop(db, "Paused group")
    await set_status(db, shop, "paused")
    reached: list[str] = []

    async def handler(event: Any, data: dict[str, Any]) -> None:
        reached.append("handler")

    from aiogram.types import Chat

    async with bound_session_factory(db)() as session:
        gate = ShopPausedMiddleware(shop)
        await gate(
            handler,
            object(),  # type: ignore[arg-type]
            {"event_chat": Chat(id=-100_777, type="supergroup"), "session": session},
        )
    assert reached == ["handler"]


# --- the public page ----------------------------------------------------------------


async def test_a_paused_shops_page_stays_up_without_the_order_link(db: AsyncConnection) -> None:
    shops = {}
    for label in ("paused", "active"):
        shop_id = (
            await db.execute(
                text(
                    "INSERT INTO shops (name, working_hours) "
                    "VALUES (:n, CAST(:wh AS jsonb)) RETURNING id"
                ),
                {"n": label, "wh": json.dumps(DEFAULT_WORKING_HOURS)},
            )
        ).scalar_one()
        customer = await make_customer(db, shop_id, 990_301)
        session = bound_session_factory(db)()
        page = await share_pages.create_page(
            session, shop_id=shop_id, customer_id=customer, bot_username="lola_bot", draft=yesno()
        )
        await session.flush()
        shops[label] = (shop_id, page.token)
    await set_status(db, shops["paused"][0], "paused")

    app = build_app(
        session_factory=bound_session_factory(db),
        notify=lambda page_id, delay: None,
        public_base_url="http://pages.test",
    )
    async with TestClient(TestServer(app)) as client:
        seen = {}
        for label, (_, token) in shops.items():
            page_html = await (await client.get(f"/p/{token}")).text()
            go = await client.get(f"/p/{token}/go", allow_redirects=False)
            seen[label] = (f"/p/{token}/go" in page_html, go.status, go.headers.get("Location"))

    assert seen["active"][0] and seen["active"][2].startswith("https://t.me/")
    has_link, status, location = seen["paused"]
    assert not has_link, "a paused shop's page still offers the order link"
    assert status == 302 and location == f"/p/{shops['paused'][1]}", location
