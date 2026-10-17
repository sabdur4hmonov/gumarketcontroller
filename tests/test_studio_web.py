"""Taklifnoma Studio (CP27.1) through the real page server and real Postgres.

- EVERY /studio route answers 401/403 without a session -- found by walking
  the router -- and every POST without the session's CSRF token is refused.
- The link: a GET (Telegram's preview robot included) never spends it; the
  POST spends it once; the cookie is HttpOnly, SameSite=Lax, Path=/studio, and
  Secure exactly when the site is https.
- ONE form makes a whole taklifnoma, places included, through the bot's own
  service; mistakes come back next to their field with what was typed kept.
- Premium designs are shown locked with the CP18 wording and refused on
  create; with the gift they work. The preview saves nothing.
- A creator sees only their own pages in their own shop; no phone number, no
  other customer's text and no link token reaches a studio screen.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import bound_session_factory

from gulbot.config import TASHKENT
from gulbot.i18n import t
from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.services import premium, studio
from gulbot.web import render
from gulbot.web import studio as studio_web
from gulbot.web.app import build_app

pytestmark = pytest.mark.infra

PHONE_A, PHONE_B = "+998901110071", "+998902220072"
OWNER_PHONE = "+998903330073"
SECRET_B = "Bshop-maxfiy-matn"
DATE = (datetime.now(UTC).astimezone(TASHKENT).date() + timedelta(days=40)).isoformat()


async def _shop(db: AsyncConnection, name: str) -> int:
    return int(
        await db.scalar(
            text(
                "INSERT INTO shops (name, working_hours, owner_phone) "
                "VALUES (:n, CAST(:wh AS jsonb), :p) RETURNING id"
            ),
            {"n": name, "wh": json.dumps(DEFAULT_WORKING_HOURS), "p": OWNER_PHONE},
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


@pytest_asyncio.fixture
async def world(db: AsyncConnection) -> dict[str, Any]:
    a, b = await _shop(db, "Lola A"), await _shop(db, "Bog B")
    ca = await _customer(db, a, 771_001, PHONE_A)
    cb = await _customer(db, b, 772_002, PHONE_B)
    return {"db": db, "a": a, "b": b, "ca": ca, "cb": cb}


def app_for(db: AsyncConnection, base: str = "http://127.0.0.1:8088", **kw: Any) -> Any:
    return build_app(
        session_factory=bound_session_factory(db),
        notify=lambda page_id, delay: None,
        public_base_url=base,
        studio_on=True,
        **kw,
    )


async def mint(db: AsyncConnection, shop: int, customer: int) -> str:
    async with bound_session_factory(db)() as session:
        raw = await studio.mint_link(
            session, shop_id=shop, customer_id=customer, bot_username="lola_bot"
        )
        await session.commit()
    assert raw is not None
    return raw


async def log_in(client: TestClient, db: AsyncConnection, shop: int, customer: int) -> str:
    """Through the real routes; the cookie is carried by hand, as for /shop."""
    raw = await mint(db, shop, customer)
    response = await client.post("/studio/enter", data={"token": raw}, allow_redirects=False)
    assert response.status == 303, response.status
    client.session.cookie_jar.update_cookies(
        {studio_web.COOKIE: response.cookies[studio_web.COOKIE].value}
    )
    async with bound_session_factory(db)() as session:
        csrf = await session.scalar(
            text("SELECT csrf_token FROM studio_sessions ORDER BY id DESC LIMIT 1")
        )
    return str(csrf)


def studio_routes(app: Any) -> list[tuple[str, str]]:
    return sorted(
        {
            (route.method, route.resource.canonical)
            for route in app.router.routes()
            if route.resource is not None
            and studio_web.is_studio_path(route.resource.canonical)
            and route.method != "HEAD"
        }
    )


def concrete(path: str) -> str:
    return path.replace("{token}", "x" * 43).replace("{page_id}", "1")


def form(csrf: str, **overrides: str) -> dict[str, str]:
    data = {
        "csrf": csrf,
        "lang": "uz",
        "event_type": "wedding",
        "name_1": "Aziz",
        "name_2": "Malika",
        "event_date": DATE,
        "event_time": "18:00",
        "venue_count": "2",
        "venue_kind_1": "toyxona",
        "venue_name_1": "Navro‘z to‘yxonasi",
        "venue_address_1": "Chilonzor 5",
        "venue_map_1": "https://www.google.com/maps/place/X/@41.311081,69.240562,17z",
        "venue_time_1": "18:00",
        "venue_kind_2": "uy",
        "venue_name_2": "Kelin tomon",
        "venue_address_2": "",
        "venue_map_2": "https://maps.app.goo.gl/abc123",
        "venue_time_2": "",
        "message": "Kutib qolamiz!",
        "rsvp": "1",
        "template": "milliy",
        "action": "create",
    }
    data.update(overrides)
    return data


# --- the gate -------------------------------------------------------------------


async def test_every_studio_route_refuses_a_request_without_a_session(world: dict) -> None:
    app = app_for(world["db"])
    gated = [r for r in studio_routes(app) if r not in studio_web.PUBLIC_ROUTES]
    assert len(gated) >= 5, gated  # guards the guard: an empty walk passes everything
    async with TestClient(TestServer(app)) as client:
        for method, path in gated:
            response = await client.request(method, concrete(path), allow_redirects=False)
            assert response.status == (401 if method == "GET" else 403), (method, path)
            assert PHONE_A not in await response.text()


async def test_every_post_needs_the_sessions_csrf_token(world: dict) -> None:
    db = world["db"]
    app = app_for(db)
    posts = [r for r in studio_routes(app) if r[0] == "POST" and r not in studio_web.PUBLIC_ROUTES]
    assert len(posts) >= 3, posts
    async with TestClient(TestServer(app)) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        for _method, path in posts:
            for wrong in ({}, {"csrf": "x" * len(csrf)}):
                response = await client.post(concrete(path), data=wrong, allow_redirects=False)
                assert response.status == 403, (path, wrong)
    refused = await db.scalar(
        text("SELECT count(*) FROM studio_audit_log WHERE action = 'csrf_refused'")
    )
    assert refused == 2 * len(posts)


async def test_the_studio_is_absent_unless_switched_on(world: dict) -> None:
    app = build_app(
        session_factory=bound_session_factory(world["db"]),
        notify=lambda page_id, delay: None,
        public_base_url="http://127.0.0.1:8088",
    )
    async with TestClient(TestServer(app)) as client:
        assert (await client.get("/studio")).status == 404


# --- the way in -------------------------------------------------------------------


async def test_opening_the_link_does_not_spend_it(world: dict) -> None:
    db = world["db"]
    raw = await mint(db, world["a"], world["ca"])
    async with TestClient(TestServer(app_for(db))) as client:
        for agent in ("TelegramBot (like TwitterBot)", "Mozilla/5.0"):
            page = await client.get(f"/studio/enter/{raw}", headers={"User-Agent": agent})
            assert page.status == 200 and "Kirish" in await page.text()
        used = await db.scalar(text("SELECT used_at FROM studio_links"))
        assert used is None, "a GET spent the link"
        first = await client.post("/studio/enter", data={"token": raw}, allow_redirects=False)
        second = await client.post("/studio/enter", data={"token": raw}, allow_redirects=False)
    assert first.status == 303 and second.status == 401


@pytest.mark.parametrize(
    ("base", "secure"), [("http://127.0.0.1:8088", False), ("https://x.uz", True)]
)
async def test_the_cookie_is_httponly_lax_scoped_and_secure_on_https(
    world: dict, base: str, secure: bool
) -> None:
    db = world["db"]
    raw = await mint(db, world["a"], world["ca"])
    async with TestClient(TestServer(app_for(db, base))) as client:
        response = await client.post("/studio/enter", data={"token": raw}, allow_redirects=False)
    header = response.headers["Set-Cookie"]
    assert header.startswith(f"{studio_web.COOKIE}=")
    assert "HttpOnly" in header and "SameSite=Lax" in header and "Path=/studio" in header
    assert ("Secure" in header) is secure


async def test_the_login_is_rate_limited(world: dict) -> None:
    db = world["db"]
    async with TestClient(TestServer(app_for(db, admin_login_limit=2))) as client:
        statuses = [(await client.get(f"/studio/enter/{'y' * 43}")).status for _ in range(3)]
    assert statuses == [200, 200, 429]


async def test_logout_ends_the_session(world: dict) -> None:
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        assert (await client.get("/studio")).status == 200
        assert (await client.post("/studio/logout", data={"csrf": csrf})).status == 200
        assert (await client.get("/studio")).status == 401


async def test_pausing_the_shop_closes_the_studio_on_the_next_request(world: dict) -> None:
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        await log_in(client, db, world["a"], world["ca"])
        assert (await client.get("/studio")).status == 200
        await db.execute(
            text("UPDATE shops SET status = 'paused' WHERE id = :s"), {"s": world["a"]}
        )
        assert (await client.get("/studio")).status == 401


# --- the form ------------------------------------------------------------------------


async def test_one_form_makes_a_whole_taklifnoma(world: dict) -> None:
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        picker = await (
            await client.post("/studio/design", data=form(csrf, action="pick", cat="all"))
        ).text()
        for design in render.THEME_NAMES:
            assert f'data-design="{design}"' in picker, f"design {design} missing from the picker"
        made = await client.post("/studio/create", data=form(csrf), allow_redirects=False)
        assert made.status == 303, await made.text()
        done_url = made.headers["Location"]
        assert re.fullmatch(r"/studio/done/\d+", done_url)
        done = await (await client.get(done_url)).text()
    row = (
        await db.execute(
            text(
                "SELECT id, token, shop_id, customer_id, venue, bot_username, rsvp_enabled "
                "FROM share_pages ORDER BY id DESC LIMIT 1"
            )
        )
    ).one()
    assert (row.shop_id, row.customer_id) == (world["a"], world["ca"])
    assert row.venue == "Navro‘z to‘yxonasi, Chilonzor 5" and row.bot_username == "lola_bot"
    assert row.rsvp_enabled is True
    assert f"http://127.0.0.1:8088/p/{row.token}" in done
    places = list(
        await db.scalars(
            text("SELECT name FROM share_page_venues WHERE page_id = :p ORDER BY position"),
            {"p": row.id},
        )
    )
    assert places == ["Navro‘z to‘yxonasi", "Kelin tomon"]
    audit = await db.scalar(
        text("SELECT count(*) FROM studio_audit_log WHERE action = 'page_created'")
    )
    assert audit == 1


async def test_adding_and_removing_a_place_keeps_what_was_typed(world: dict) -> None:
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        added = await (
            await client.post("/studio/create", data=form(csrf, action="add_venue"))
        ).text()
        assert 'name="venue_name_3"' in added and 'value="Kelin tomon"' in added
        assert 'value="Aziz"' in added
        removed = await (
            await client.post("/studio/create", data=form(csrf, action="remove_1"))
        ).text()
        assert 'name="venue_name_2"' not in removed and 'value="Kelin tomon"' in removed
    assert await db.scalar(text("SELECT count(*) FROM share_pages")) == 0


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"name_1": "  "}, "Ismni yozing."),
        ({"event_date": "2020-01-01"}, "Sana bugundan boshlab 12 oy ichida"),
        ({"venue_map_1": "https://evil.example/x"}, "Xarita havolasi Google, Yandex yoki 2GIS"),
        (
            {
                "venue_name_1": "",
                "venue_name_2": "",
                "venue_map_1": "",
                "venue_map_2": "",
                "venue_address_1": "",
            },
            "Kamida bitta joy yozing.",
        ),
        ({"venue_kind_1": "saroy"}, "Joy turini tanlang."),
        ({"template": "nope"}, "Dizaynni tanlang."),
    ],
)
async def test_a_mistake_comes_back_next_to_its_field(
    world: dict, overrides: dict[str, str], message: str
) -> None:
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        response = await client.post("/studio/create", data=form(csrf, **overrides))
        body = await response.text()
    assert response.status == 422
    assert message in body and 'value="Malika"' in body
    assert await db.scalar(text("SELECT count(*) FROM share_pages")) == 0


async def test_premium_designs_are_locked_with_the_cp18_wording(world: dict) -> None:
    db = world["db"]
    locked_text = t("premium.locked", "uz")
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        screen = await (
            await client.post("/studio/design", data=form(csrf, action="pick", cat="all"))
        ).text()
        assert 'name="choose" value="milliy"' in screen
        assert 'name="choose" value="deco"' not in screen, "a locked design offers no choice"
        assert locked_text.split("—")[0].strip() in screen.replace("&#39;", "'")
        refused = await client.post("/studio/create", data=form(csrf, template="deco"))
        assert refused.status == 422
    assert await db.scalar(text("SELECT count(*) FROM share_pages")) == 0


async def test_with_the_gift_premium_designs_open(world: dict) -> None:
    db = world["db"]
    order = await db.scalar(
        text(
            "INSERT INTO orders (shop_id, customer_id, product_name_snapshot, price_uzs_snapshot, "
            " telegram_file_id_snapshot, delivery_date, delivery_hour, delivery_location_text, "
            " landmark, status, submit_token) VALUES (:s, :c, 'Atirgul', 1, 'f', now()::date, "
            " '14:00', 'x', 'y', 'confirmed', 'gift') RETURNING id"
        ),
        {"s": world["a"], "c": world["ca"]},
    )
    await db.execute(
        text("INSERT INTO premium_unlocks (shop_id, customer_id, order_id) VALUES (:s, :c, :o)"),
        {"s": world["a"], "c": world["ca"], "o": order},
    )
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        screen = await (
            await client.post("/studio/design", data=form(csrf, action="pick", cat="all"))
        ).text()
        assert 'name="choose" value="deco"' in screen
        made = await client.post(
            "/studio/create", data=form(csrf, template="deco"), allow_redirects=False
        )
    assert made.status == 303
    assert premium.is_premium_template("deco")


async def test_the_preview_shows_the_creators_data_and_saves_nothing(world: dict) -> None:
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        before = await db.scalar(text("SELECT count(*) FROM share_pages"))
        for design in ("milliy", "deco"):  # a premium one may be looked at
            response = await client.post(
                "/studio/preview", data=form(csrf, preview_template=design, name_1="Zarina")
            )
            body = await response.text()
            assert response.status == 200, body[:300]
            assert "Zarina" in body and f"theme-{design}" in body
            assert "Kelin tomon" in body
        half = await client.post(
            "/studio/preview", data=form(csrf, name_1="", venue_name_1="", venue_name_2="")
        )
        assert half.status == 200, "an unfinished form can still be previewed"
    assert await db.scalar(text("SELECT count(*) FROM share_pages")) == before
    assert await db.scalar(text("SELECT count(*) FROM share_page_venues")) == 0


# --- isolation and leaks --------------------------------------------------------------


async def test_a_creator_sees_only_their_own_pages(world: dict) -> None:
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        csrf_b = await log_in(client, db, world["b"], world["cb"])
        made = await client.post(
            "/studio/create", data=form(csrf_b, message=SECRET_B), allow_redirects=False
        )
        theirs = made.headers["Location"]
    async with TestClient(TestServer(app_for(db))) as client:
        await log_in(client, db, world["a"], world["ca"])
        response = await client.get(theirs)
        assert response.status == 404
        assert SECRET_B not in await response.text()
        assert (await client.get("/studio/done/abc")).status == 404


async def test_no_phone_or_token_reaches_any_studio_screen(world: dict) -> None:
    db = world["db"]
    app = app_for(db)
    raw = await mint(db, world["a"], world["ca"])
    async with TestClient(TestServer(app)) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        bodies = [await (await client.get("/studio")).text()]
        made = await client.post("/studio/create", data=form(csrf), allow_redirects=False)
        bodies.append(await (await client.get(made.headers["Location"])).text())
        bodies.append(
            await (await client.post("/studio/create", data=form(csrf, name_1=""))).text()
        )
        bodies.append(await (await client.post("/studio/preview", data=form(csrf))).text())
        bodies.append(  # CP27.1b: the design picker
            await (await client.post("/studio/design", data=form(csrf, cat="all"))).text()
        )
        cookie = client.session.cookie_jar.filter_cookies(client.make_url("/studio"))
    everything = "\n".join(bodies)
    for planted in (PHONE_A, PHONE_B, OWNER_PHONE, raw, cookie[studio_web.COOKIE].value):
        assert planted not in everything


async def test_studio_pages_may_post_to_themselves_and_public_pages_may_not(world: dict) -> None:
    db = world["db"]
    raw = await mint(db, world["a"], world["ca"])
    async with TestClient(TestServer(app_for(db))) as client:
        studio_csp = (await client.get(f"/studio/enter/{raw}")).headers["Content-Security-Policy"]
        public_csp = (await client.get("/demo/invite/milliy")).headers["Content-Security-Policy"]
    assert "form-action 'self'" in studio_csp and "script-src 'self'" in studio_csp
    assert "unsafe-inline" not in studio_csp and "frame-ancestors 'none'" in studio_csp
    assert "form-action 'none'" in public_csp


def test_every_design_has_a_thumbnail() -> None:
    missing = [
        key
        for key in render.THEME_NAMES
        if not (render.STATIC / "studio" / "thumbs" / f"{key}.webp").is_file()
    ]
    assert not missing, f"run scripts/studio_thumbs.py for {missing}"
