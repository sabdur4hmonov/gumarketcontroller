"""The shop owner's own panel, /shop (CP20), through the real page server.

What it must prove, beyond "the screens render":

- EVERY /shop route answers 401/403 without a session -- found by walking the
  router, so a route added later is covered without anyone remembering.
- A SESSION SEES ONE SHOP. An owner logged in for shop A walks every screen
  and export with shop B's customers, dates and orders planted, and none of
  B's appears -- including when the URL tries to name B.
- The way in is a one-time link minted by THAT shop's bot for one of ITS
  owners: single use, expires, refused once the person stops owning the shop,
  and a shop's customer who types /panel gets nothing.
- Exports are audit-logged; the audit log cannot be rewritten; a spreadsheet
  formula in a product name is shown, not run.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import SendMessage
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import bound_session_factory, feed, make_bot, text_update

from gulbot.bot.factory import build_dispatcher
from gulbot.i18n import t
from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.scheduling.occurrences import TASHKENT
from gulbot.services import shop_auth, shop_crm
from gulbot.web import shop_panel
from gulbot.web.app import build_app

pytestmark = pytest.mark.infra

OWNER_A, OWNER_B = 660_001, 660_002
PHONE_A, PHONE_B = "+998901110001", "+998902220002"
LABEL_A, LABEL_B = "Onajonim", "Bvoyjon"
PRODUCT_A, PRODUCT_B = "Atirgul A-buket", "Lola B-buket"
TODAY = datetime.now(UTC).astimezone(TASHKENT).date()


async def _shop(db: AsyncConnection, name: str, owner: int) -> int:
    return int(
        await db.scalar(
            text(
                "INSERT INTO shops (name, working_hours, owner_telegram_ids) "
                "VALUES (:n, CAST(:wh AS jsonb), ARRAY[CAST(:o AS bigint)]) RETURNING id"
            ),
            {"n": name, "wh": json.dumps(DEFAULT_WORKING_HOURS), "o": owner},
        )
    )


async def _customer(db: AsyncConnection, shop: int, tg: int, phone: str) -> int:
    return int(
        await db.scalar(
            text(
                "INSERT INTO customers (shop_id, telegram_user_id, phone) "
                "VALUES (:s, :t, :p) RETURNING id"
            ),
            {"s": shop, "t": tg, "p": phone},
        )
    )


async def _saved_date(db: AsyncConnection, shop: int, customer: int, label: str, on: date) -> None:
    recipient = await db.scalar(
        text(
            "INSERT INTO recipients (shop_id, customer_id, label, type) "
            "VALUES (:s, :c, :l, 'custom') RETURNING id"
        ),
        {"s": shop, "c": customer, "l": label},
    )
    await db.execute(
        text(
            "INSERT INTO occasions (shop_id, customer_id, recipient_id, label, type, kind, "
            " month, day) VALUES (:s, :c, :r, :l, 'custom', 'birthday', :m, :d)"
        ),
        {"s": shop, "c": customer, "r": recipient, "l": label, "m": on.month, "d": on.day},
    )


async def _order(
    db: AsyncConnection, shop: int, customer: int, product: str, *, token: str, source: str | None
) -> int:
    return int(
        await db.scalar(
            text(
                "INSERT INTO orders (shop_id, customer_id, product_name_snapshot, "
                " price_uzs_snapshot, telegram_file_id_snapshot, delivery_date, delivery_hour, "
                " delivery_location_text, landmark, status, submit_token, source) "
                "VALUES (:s, :c, :p, 350000, 'f', :d, '14:00', 'Chilonzor', 'eshik', "
                " 'placed', :t, :src) RETURNING id"
            ),
            {"s": shop, "c": customer, "p": product, "d": TODAY, "t": token, "src": source},
        )
    )


@pytest_asyncio.fixture
async def world(db: AsyncConnection) -> dict[str, Any]:
    a = await _shop(db, "Lola A", OWNER_A)
    b = await _shop(db, "Bog B", OWNER_B)
    ca = await _customer(db, a, 661_001, PHONE_A)
    cb = await _customer(db, b, 662_002, PHONE_B)
    await _saved_date(db, a, ca, LABEL_A, TODAY + timedelta(days=3))
    await _saved_date(db, b, cb, LABEL_B, TODAY + timedelta(days=3))
    await _order(db, a, ca, PRODUCT_A, token="pa", source="reminder")
    await _order(db, b, cb, PRODUCT_B, token="pb", source="reminder")
    return {"db": db, "a": a, "b": b, "ca": ca, "cb": cb}


def app_for(db: AsyncConnection) -> Any:
    return build_app(
        session_factory=bound_session_factory(db),
        notify=lambda page_id, delay: None,
        public_base_url="http://pages.test",
        shop_panel_on=True,
    )


async def mint(db: AsyncConnection, shop: int, who: int, *, now: datetime | None = None) -> str:
    async with bound_session_factory(db)() as session:
        raw = await shop_auth.mint_login_link(session, shop_id=shop, telegram_id=who, now=now)
        await session.commit()
    assert raw is not None
    return raw


async def log_in(client: TestClient, db: AsyncConnection, shop: int, who: int) -> str:
    """Through the real routes; carries the cookie by hand (see test_admin_auth)."""
    raw = await mint(db, shop, who)
    response = await client.post("/shop/login", data={"token": raw}, allow_redirects=False)
    assert response.status == 303, response.status
    client.session.cookie_jar.update_cookies(
        {shop_panel.COOKIE: response.cookies[shop_panel.COOKIE].value}
    )
    async with bound_session_factory(db)() as session:
        csrf = await session.scalar(
            text("SELECT csrf_token FROM shop_sessions ORDER BY id DESC LIMIT 1")
        )
    return str(csrf)


def panel_routes(app: Any) -> list[tuple[str, str]]:
    return sorted(
        {
            (route.method, route.resource.canonical)
            for route in app.router.routes()
            if route.resource is not None
            and shop_panel.is_panel_path(route.resource.canonical)
            and route.method != "HEAD"
        }
    )


def concrete(path: str) -> str:
    return path.replace("{token}", "x" * 43)


# --- the gate -----------------------------------------------------------------


async def test_every_shop_route_refuses_a_request_without_a_session(world: dict) -> None:
    app = app_for(world["db"])
    routes = panel_routes(app)
    gated = [r for r in routes if r not in shop_panel.PUBLIC_ROUTES]
    assert len(gated) >= 6, gated  # guards the guard: an empty walk passes everything
    async with TestClient(TestServer(app)) as client:
        for method, path in gated:
            response = await client.request(method, concrete(path), allow_redirects=False)
            expected = 401 if method == "GET" else 403
            assert response.status == expected, (method, path, response.status)
            body = await response.text()
            assert PHONE_A not in body and PRODUCT_A not in body, (method, path)


async def test_the_panel_is_absent_unless_switched_on(world: dict) -> None:
    app = build_app(
        session_factory=bound_session_factory(world["db"]),
        notify=lambda page_id, delay: None,
        public_base_url="http://pages.test",
    )
    async with TestClient(TestServer(app)) as client:
        assert (await client.get("/shop")).status == 404


# --- one session, one shop -----------------------------------------------------


async def _every_screen(client: TestClient, app: Any, suffix: str = "") -> str:
    bodies = []
    for method, path in panel_routes(app):
        if method != "GET" or (method, path) in shop_panel.PUBLIC_ROUTES:
            continue
        response = await client.get(concrete(path) + suffix)
        assert response.status == 200, (path, response.status)
        bodies.append(await response.text())
    return "\n".join(bodies)


async def test_a_session_sees_its_own_shop_and_never_another(world: dict) -> None:
    app = app_for(world["db"])
    async with TestClient(TestServer(app)) as client:
        await log_in(client, world["db"], world["a"], OWNER_A)
        everything = await _every_screen(client, app)
    for mine in (PHONE_A, LABEL_A, PRODUCT_A):
        assert mine in everything, f"{mine} missing from its own shop's panel"
    for theirs in (PHONE_B, LABEL_B, PRODUCT_B):
        assert theirs not in everything, f"shop B's {theirs} reached shop A's panel"


async def test_a_url_that_names_another_shop_still_shows_the_sessions_shop(world: dict) -> None:
    app = app_for(world["db"])
    b = world["b"]
    async with TestClient(TestServer(app)) as client:
        await log_in(client, world["db"], world["a"], OWNER_A)
        everything = await _every_screen(client, app, f"?shop={b}&shop_id={b}&page=1")
    for theirs in (PHONE_B, LABEL_B, PRODUCT_B):
        assert theirs not in everything


async def test_an_owner_of_two_shops_sees_only_the_shop_whose_link_they_used(world: dict) -> None:
    db = world["db"]
    await db.execute(
        text("UPDATE shops SET owner_telegram_ids = ARRAY[CAST(:o AS bigint)] WHERE id = :b"),
        {"o": OWNER_A, "b": world["b"]},
    )
    app = app_for(db)
    async with TestClient(TestServer(app)) as client:
        await log_in(client, db, world["b"], OWNER_A)
        everything = await _every_screen(client, app)
    assert PHONE_B in everything and PHONE_A not in everything


# --- the way in ---------------------------------------------------------------


async def test_only_an_owner_of_that_shop_gets_a_link(world: dict) -> None:
    async with bound_session_factory(world["db"])() as session:
        for shop, who in ((world["a"], OWNER_B), (world["b"], OWNER_A), (world["a"], 661_001)):
            assert await shop_auth.mint_login_link(session, shop_id=shop, telegram_id=who) is None


async def test_a_link_works_once(world: dict) -> None:
    db = world["db"]
    raw = await mint(db, world["a"], OWNER_A)
    async with TestClient(TestServer(app_for(db))) as client:
        first = await client.post("/shop/login", data={"token": raw}, allow_redirects=False)
        second = await client.post("/shop/login", data={"token": raw}, allow_redirects=False)
    assert first.status == 303 and second.status == 401


async def test_an_expired_link_is_refused(world: dict) -> None:
    db = world["db"]
    raw = await mint(db, world["a"], OWNER_A, now=datetime.now(UTC) - timedelta(minutes=11))
    async with TestClient(TestServer(app_for(db))) as client:
        response = await client.post("/shop/login", data={"token": raw}, allow_redirects=False)
    assert response.status == 401


async def test_opening_the_link_does_not_spend_it_and_the_cookie_is_locked_down(
    world: dict,
) -> None:
    db = world["db"]
    raw = await mint(db, world["a"], OWNER_A)
    async with TestClient(TestServer(app_for(db))) as client:
        shown = await client.get(f"/shop/login/{raw}")
        assert shown.status == 200 and "Kirish" in await shown.text()
        response = await client.post("/shop/login", data={"token": raw}, allow_redirects=False)
    assert response.status == 303
    morsel = response.cookies[shop_panel.COOKIE]
    assert morsel["httponly"] and morsel["secure"]
    assert morsel["samesite"] == "Strict" and morsel["path"] == "/shop"
    assert response.headers["Content-Security-Policy"].count("form-action 'self'") == 1


async def test_a_link_minted_before_the_owner_was_removed_does_not_log_in(world: dict) -> None:
    db = world["db"]
    raw = await mint(db, world["a"], OWNER_A)
    await db.execute(
        text("UPDATE shops SET owner_telegram_ids = '{}' WHERE id = :a"), {"a": world["a"]}
    )
    async with TestClient(TestServer(app_for(db))) as client:
        response = await client.post("/shop/login", data={"token": raw}, allow_redirects=False)
    assert response.status == 401


async def test_removing_an_owner_ends_their_session_at_once(world: dict) -> None:
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        await log_in(client, db, world["a"], OWNER_A)
        assert (await client.get("/shop")).status == 200
        await db.execute(
            text("UPDATE shops SET owner_telegram_ids = '{}' WHERE id = :a"), {"a": world["a"]}
        )
        assert (await client.get("/shop")).status == 401


@pytest.mark.parametrize(
    "ended",
    ["expires_at = now() - interval '1 second'", "revoked_at = now()"],
)
async def test_an_expired_or_revoked_session_is_refused(world: dict, ended: str) -> None:
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        await log_in(client, db, world["a"], OWNER_A)
        assert (await client.get("/shop")).status == 200
        await db.execute(text(f"UPDATE shop_sessions SET {ended}"))
        assert (await client.get("/shop")).status == 401


async def test_an_owner_cannot_mint_an_unbounded_stream_of_links(world: dict) -> None:
    async with bound_session_factory(world["db"])() as session:
        minted = [
            await shop_auth.mint_login_link(session, shop_id=world["a"], telegram_id=OWNER_A)
            for _ in range(shop_auth.LINK_RATE_LIMIT + 1)
        ]
    assert all(minted[:-1]) and minted[-1] is None


async def test_the_source_counts_are_the_shops_own(world: dict) -> None:
    async with bound_session_factory(world["db"])() as session:
        counts = await shop_crm.order_source_counts(session, shop_id=world["a"])
    assert counts == {"reminder": 1}


async def test_a_post_without_the_csrf_token_is_refused_and_recorded(world: dict) -> None:
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], OWNER_A)
        refused = await client.post("/shop/logout", data={"csrf": "nope"})
        assert refused.status == 403
        out = await client.post("/shop/logout", data={"csrf": csrf})
        assert out.status == 200
        assert (await client.get("/shop")).status == 401
    actions = list(
        (
            await db.execute(
                text("SELECT action FROM shop_audit_log WHERE shop_id = :a ORDER BY id"),
                {"a": world["a"]},
            )
        ).scalars()
    )
    assert actions == ["login_link_sent", "login", "csrf_refused", "logout"]


# --- the bot hands out the link -------------------------------------------------


async def _shop_bot_says(db: AsyncConnection, shop: int, user: int, body: str = "/panel") -> Any:
    bot, recorder = make_bot()
    dispatcher = build_dispatcher(
        session_factory=bound_session_factory(db),
        shop_id=shop,
        storage=MemoryStorage(),
        schedule_finalize=lambda **kwargs: None,
    )
    await feed(dispatcher, bot, text_update(body, user_id=user, update_id=1))
    return [c for c in recorder.calls if isinstance(c, SendMessage)]


async def test_an_owner_gets_a_link_from_their_shops_bot_and_does_not_become_a_customer(
    world: dict,
) -> None:
    db = world["db"]
    replies = await _shop_bot_says(db, world["a"], OWNER_A)
    assert len(replies) == 1, [r.text for r in replies]
    sent = replies[0]
    found = re.search(r"/shop/login/([A-Za-z0-9_-]{40,64})", str(sent.text))
    assert found, sent.text
    assert sent.link_preview_options is not None and sent.link_preview_options.is_disabled
    stored = (await db.execute(text("SELECT shop_id, token_hash FROM shop_login_links"))).all()
    assert stored == [(world["a"], shop_auth.hash_token(found.group(1)))]
    customers = await db.scalar(
        text("SELECT count(*) FROM customers WHERE shop_id = :a AND telegram_user_id = :o"),
        {"a": world["a"], "o": OWNER_A},
    )
    assert customers == 0


async def test_another_shops_bot_gives_an_owner_nothing(world: dict) -> None:
    sent = await _shop_bot_says(world["db"], world["b"], OWNER_A)
    assert not any("/shop/login/" in str(s.text) for s in sent)
    assert await world["db"].scalar(text("SELECT count(*) FROM shop_login_links")) == 0


async def test_a_customer_who_types_panel_gets_no_link(world: dict) -> None:
    sent = await _shop_bot_says(world["db"], world["a"], 661_001)
    assert not any("/shop/login/" in str(s.text) for s in sent)
    assert await world["db"].scalar(text("SELECT count(*) FROM shop_login_links")) == 0


async def test_panel_from_someone_who_is_not_an_owner_is_handled_as_before(world: dict) -> None:
    """Untouched, not answered about a panel: a new person writing /panel
    becomes a customer, as any first message makes them, and hears nothing
    about panels or links."""
    newcomer = 661_777
    sent = await _shop_bot_says(world["db"], world["a"], newcomer)
    panel_texts = {
        t(key, lang) for key in ("panel.link_refused", "panel.unavailable") for lang in ("uz", "ru")
    }
    assert not panel_texts & {str(s.text) for s in sent}
    registered = await world["db"].scalar(
        text("SELECT count(*) FROM customers WHERE shop_id = :a AND telegram_user_id = :n"),
        {"a": world["a"], "n": newcomer},
    )
    assert registered == 1


async def test_a_paused_shops_owner_still_gets_in(world: dict) -> None:
    db = world["db"]
    await db.execute(text("UPDATE shops SET status = 'paused' WHERE id = :a"), {"a": world["a"]})
    replies = await _shop_bot_says(db, world["a"], OWNER_A)
    assert [r for r in replies if "/shop/login/" in str(r.text)], [r.text for r in replies]


# --- the screens' content ------------------------------------------------------


async def test_upcoming_dates_cover_thirty_days_and_no_more(world: dict) -> None:
    db = world["db"]
    await _saved_date(db, world["a"], world["ca"], "Kechroq", TODAY + timedelta(days=31))
    await _saved_date(db, world["a"], world["ca"], "Bugungi", TODAY)
    async with TestClient(TestServer(app_for(db))) as client:
        await log_in(client, db, world["a"], OWNER_A)
        body = await (await client.get("/shop/dates")).text()
    assert "Bugungi" in body and LABEL_A in body
    assert "Kechroq" not in body
    assert body.index("Bugungi") < body.index(LABEL_A)  # soonest first


async def test_orders_filter_by_where_they_came_from(world: dict) -> None:
    db = world["db"]
    await _order(db, world["a"], world["ca"], "Direct-buket", token="pd", source="direct")
    async with TestClient(TestServer(app_for(db))) as client:
        await log_in(client, db, world["a"], OWNER_A)
        reminders = await (await client.get("/shop/orders?source=reminder")).text()
        direct = await (await client.get("/shop/orders?source=direct")).text()
        junk = await (await client.get("/shop/orders?source=';DROP&status=x")).text()
    assert PRODUCT_A in reminders and "Direct-buket" not in reminders
    assert "Direct-buket" in direct and PRODUCT_A not in direct
    assert PRODUCT_A in junk and "Direct-buket" in junk  # unknown filters are dropped


async def test_exports_are_csv_of_the_own_shop_and_are_audited(world: dict) -> None:
    db = world["db"]
    await _order(db, world["a"], world["ca"], '=HYPERLINK("x")', token="pf", source="direct")
    async with TestClient(TestServer(app_for(db))) as client:
        await log_in(client, db, world["a"], OWNER_A)
        customers = await client.get("/shop/export/customers.csv")
        orders = await client.get("/shop/export/orders.csv?source=direct")
        customers_csv, orders_csv = await customers.text(), await orders.text()
    assert customers.headers["Content-Type"].startswith("text/csv")
    assert "attachment" in customers.headers["Content-Disposition"]
    assert PHONE_A in customers_csv and PHONE_B not in customers_csv
    assert "'=HYPERLINK" in orders_csv and PRODUCT_A not in orders_csv
    rows = (
        await db.execute(
            text(
                "SELECT action, detail FROM shop_audit_log "
                "WHERE shop_id = :a AND action LIKE 'export_%' ORDER BY id"
            ),
            {"a": world["a"]},
        )
    ).all()
    assert [r.action for r in rows] == ["export_customers", "export_orders"]
    assert rows[0].detail["rows"] == 1
    assert rows[1].detail["rows"] == 1 and rows[1].detail["source"] == "direct"


async def test_the_shop_audit_log_cannot_be_rewritten(world: dict) -> None:
    db = world["db"]
    await mint(db, world["a"], OWNER_A)
    for statement in (
        "UPDATE shop_audit_log SET action = 'x'",
        "DELETE FROM shop_audit_log",
        "TRUNCATE shop_audit_log",
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            async with db.begin_nested():
                await db.execute(text(statement))
