"""CP18: who can get into the platform admin panel, and how.

The rules, each proven here against the real page server app and the real
platform dispatcher:

- The only way in is a link the platform bot sends to an id on
  PLATFORM_ADMIN_TELEGRAM_IDS. A shop owner's id gets no link.
- A link works once, for ten minutes, and only for an id still on the list.
- EVERY /admin route refuses a request without a live session -- found by
  walking the router, so a route added later cannot be forgotten -- and every
  POST refuses one without the session's CSRF token.
- The session cookie is HttpOnly, Secure, SameSite=Strict, Path=/admin, short.
- Every login, refusal and logout lands in admin_audit_log, which the
  database itself will not let anyone rewrite.
- Production refuses to start with no admin ids.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from aiogram import Bot
from aiogram.methods import SendMessage
from aiogram.types import User
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import RecordingSession, bound_session_factory, feed, text_update

from gulbot.config import Settings, parse_admin_ids, production_config_problems
from gulbot.services import admin_auth
from gulbot.web import admin as admin_web
from gulbot.web.app import build_app

pytestmark = pytest.mark.infra

ADMIN = 7_000_001
OTHER_ADMIN = 7_000_002
OWNER = 7_000_900  # a shop owner, never an admin
ADMINS = frozenset({ADMIN, OTHER_ADMIN})


def app_for(db: AsyncConnection, admins: frozenset[int] = ADMINS) -> Any:
    return build_app(
        session_factory=bound_session_factory(db),
        notify=lambda page_id, delay: None,
        public_base_url="http://pages.test",
        admin_ids=lambda: admins,
    )


async def mint(db: AsyncConnection, who: int = ADMIN, *, now: datetime | None = None) -> str:
    async with bound_session_factory(db)() as session:
        raw = await admin_auth.mint_login_link(session, telegram_id=who, allowed=ADMINS, now=now)
        await session.commit()
    assert raw is not None
    return raw


async def logged_in(client: TestClient, db: AsyncConnection) -> str:
    """Log in through the real routes; returns the session's CSRF token."""
    raw = await mint(db)
    response = await client.post("/admin/login", data={"token": raw}, allow_redirects=False)
    assert response.status == 303, response.status
    # aiohttp's client jar stores no cookie from an IP-address host and sends
    # no Secure cookie over http; a browser treats 127.0.0.1 as a secure
    # context. So the test carries the cookie the server set, by hand. Its
    # flags are asserted in test_opening_the_link_does_not_spend_it_...
    client.session.cookie_jar.update_cookies(
        {admin_web.COOKIE: response.cookies[admin_web.COOKIE].value}
    )
    async with bound_session_factory(db)() as session:
        csrf = await session.scalar(
            text("SELECT csrf_token FROM admin_sessions ORDER BY id DESC LIMIT 1")
        )
    return str(csrf)


async def audit_actions(db: AsyncConnection) -> list[str]:
    return list(
        (await db.execute(text("SELECT action FROM admin_audit_log ORDER BY id"))).scalars()
    )


# --- the admin list and the production guard --------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("111,222 333", {111, 222, 333}),
        ("", set()),
        ("   ", set()),
        ("111,abc", set()),  # a typo locks everyone out; it never lets a wrong id in
        ("111,-5", set()),
    ],
)
def test_the_admin_list_is_parsed_strictly(raw: str, expected: set[int]) -> None:
    assert parse_admin_ids(raw) == expected


def _production(**overrides: str) -> Settings:
    values = {
        "environment": "production",
        "bot_token": "123456789:" + "P" * 35,
        "postgres_host": "db.prod.internal",
        "postgres_db": "gulbot_prod",
        "postgres_password": "prod-pw",
        "platform_admin_telegram_ids": "111",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


PROD_ENV = {
    "ENVIRONMENT": "production",
    "BOT_TOKEN": "x",
    "POSTGRES_HOST": "x",
    "POSTGRES_DB": "x",
    "POSTGRES_PASSWORD": "x",
}


@pytest.mark.parametrize("ids", ["", "  ", "111,oops"])
def test_production_refuses_to_start_without_a_usable_admin_list(ids: str) -> None:
    problems = production_config_problems(_production(platform_admin_telegram_ids=ids), PROD_ENV)
    assert any("PLATFORM_ADMIN_TELEGRAM_IDS" in p for p in problems), problems


def test_production_with_an_admin_list_has_no_admin_problem() -> None:
    assert production_config_problems(_production(), PROD_ENV) == []


# --- the platform bot hands out the link -------------------------------------------


async def _platform_says(db: AsyncConnection, user: int, monkeypatch: pytest.MonkeyPatch) -> Any:
    from gulbot.bot.factory import build_platform_dispatcher

    monkeypatch.setattr(admin_auth, "admin_ids", lambda settings=None: ADMINS)
    recorder = RecordingSession()
    bot = Bot(token="555000111:" + "A" * 35, session=recorder)
    bot._me = User(id=555_000_111, is_bot=True, first_name="platform", username="plat_bot")  # noqa: SLF001
    dispatcher = build_platform_dispatcher(session_factory=bound_session_factory(db))
    await feed(dispatcher, bot, text_update("/admin", user_id=user, update_id=1))
    return recorder


async def test_an_admin_gets_a_one_time_link_with_no_preview(
    db: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = await _platform_says(db, ADMIN, monkeypatch)
    (sent,) = [c for c in recorder.calls if isinstance(c, SendMessage)]
    found = re.search(r"/admin/login/([A-Za-z0-9_-]{40,64})", sent.text)
    assert found, sent.text
    assert sent.link_preview_options is not None and sent.link_preview_options.is_disabled
    raw = found.group(1)
    stored = (await db.execute(text("SELECT token_hash, telegram_id FROM admin_login_links"))).all()
    assert stored == [(admin_auth.hash_token(raw), ADMIN)], "the link must be stored hashed"
    assert raw not in str(stored)


async def test_a_shop_owner_gets_no_link_and_nothing_is_written(
    db: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = await _platform_says(db, OWNER, monkeypatch)
    texts = [c.text for c in recorder.calls if isinstance(c, SendMessage)]
    assert not any("/admin/login/" in t for t in texts), texts
    # The admin handler never even answered: "/admin" fell through to
    # onboarding, so a non-admin learns nothing about a panel.
    from gulbot.i18n.catalog import CATALOG

    refusals = {
        CATALOG[key][lang]
        for key in ("admin.link_refused", "admin.unavailable")
        for lang in ("uz", "ru")
    }
    assert not refusals & set(texts), texts
    assert await db.scalar(text("SELECT count(*) FROM admin_login_links")) == 0


async def test_the_service_itself_mints_nothing_for_a_non_admin(db: AsyncConnection) -> None:
    """The second wall, under the bot's filter: called directly for a shop
    owner's id, minting returns nothing and writes nothing."""
    async with bound_session_factory(db)() as session:
        raw = await admin_auth.mint_login_link(session, telegram_id=OWNER, allowed=ADMINS)
        await session.flush()
    assert raw is None
    assert await db.scalar(text("SELECT count(*) FROM admin_login_links")) == 0


async def test_minting_is_rate_limited_per_admin(db: AsyncConnection) -> None:
    for _ in range(admin_auth.LINK_RATE_LIMIT):
        await mint(db)
    async with bound_session_factory(db)() as session:
        refused = await admin_auth.mint_login_link(session, telegram_id=ADMIN, allowed=ADMINS)
    assert refused is None


# --- the link -------------------------------------------------------------------------


async def test_opening_the_link_does_not_spend_it_and_kirish_does_once(
    db: AsyncConnection,
) -> None:
    raw = await mint(db)
    async with TestClient(TestServer(app_for(db))) as client:
        opened = await client.get(f"/admin/login/{raw}")  # what a preview fetcher does
        assert opened.status == 200 and 'name="token"' in await opened.text()
        first = await client.post("/admin/login", data={"token": raw}, allow_redirects=False)
        again = await client.post("/admin/login", data={"token": raw}, allow_redirects=False)
    assert first.status == 303 and first.headers["Location"] == "/admin"
    cookie = first.headers["Set-Cookie"]
    for flag in ("HttpOnly", "Secure", "SameSite=Strict", "Path=/admin", "Max-Age=3600"):
        assert flag.lower() in cookie.lower(), (flag, cookie)
    assert again.status == 401, "a spent link logged in a second time"
    assert (await audit_actions(db))[-2:] == ["login", "login_refused"]


async def test_an_expired_link_is_refused(db: AsyncConnection) -> None:
    raw = await mint(db, now=datetime.now(UTC) - admin_auth.LINK_TTL - timedelta(seconds=1))
    async with TestClient(TestServer(app_for(db))) as client:
        response = await client.post("/admin/login", data={"token": raw}, allow_redirects=False)
    assert response.status == 401
    assert await db.scalar(text("SELECT count(*) FROM admin_sessions")) == 0


async def test_an_id_taken_off_the_list_cannot_spend_its_link(db: AsyncConnection) -> None:
    raw = await mint(db, OTHER_ADMIN)
    async with TestClient(TestServer(app_for(db, frozenset({ADMIN})))) as client:
        response = await client.post("/admin/login", data={"token": raw}, allow_redirects=False)
    assert response.status == 401
    assert await db.scalar(text("SELECT count(*) FROM admin_sessions")) == 0


async def test_a_shop_owner_cannot_log_in_even_with_a_forged_link_row(db: AsyncConnection) -> None:
    """Belt and braces: even a link row written for a non-admin id (by a bug,
    or by hand) opens nothing, because the list is checked when it is spent."""
    raw = "x" * 43
    await db.execute(
        text(
            "INSERT INTO admin_login_links (token_hash, telegram_id, expires_at) "
            "VALUES (:h, :t, now() + interval '5 minutes')"
        ),
        {"h": admin_auth.hash_token(raw), "t": OWNER},
    )
    async with TestClient(TestServer(app_for(db))) as client:
        response = await client.post("/admin/login", data={"token": raw}, allow_redirects=False)
    assert response.status == 401
    assert await db.scalar(text("SELECT count(*) FROM admin_sessions")) == 0


async def test_logging_in_is_rate_limited(db: AsyncConnection) -> None:
    async with TestClient(TestServer(app_for(db))) as client:
        statuses = [
            (await client.post("/admin/login", data={"token": "y" * 43})).status for _ in range(15)
        ]
    assert 429 in statuses, statuses


# --- every route behind the gate ------------------------------------------------------


def _admin_routes(app: Any) -> list[tuple[str, str]]:
    routes = []
    for route in app.router.routes():
        canonical = route.resource.canonical if route.resource is not None else ""
        if canonical.startswith("/admin") and route.method in ("GET", "POST"):
            routes.append((route.method, canonical))
    return routes


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", path)


async def test_the_router_has_admin_routes_and_only_the_login_pair_is_public(
    db: AsyncConnection,
) -> None:
    routes = _admin_routes(app_for(db))
    assert len(routes) >= 15, routes  # login pair, logout, 6 screens, 7 actions
    assert set(routes) >= admin_web.PUBLIC_ROUTES
    assert {
        ("GET", "/admin/login/{token}"),
        ("POST", "/admin/login"),
    } == admin_web.PUBLIC_ROUTES


async def test_every_admin_route_refuses_a_request_without_a_session(db: AsyncConnection) -> None:
    app = app_for(db)
    protected = [r for r in _admin_routes(app) if r not in admin_web.PUBLIC_ROUTES]
    before = await db.scalar(text("SELECT count(*) FROM admin_audit_log"))
    async with TestClient(TestServer(app)) as client:
        answered = {}
        for method, path in protected:
            response = await client.request(
                method, _concrete(path), data={"csrf": "x"}, allow_redirects=False
            )
            answered[(method, path)] = response.status
    let_through = {k: v for k, v in answered.items() if v not in (401, 403)}
    assert not let_through, let_through
    assert await db.scalar(text("SELECT count(*) FROM admin_audit_log")) == before


async def test_an_expired_or_revoked_session_is_refused(db: AsyncConnection) -> None:
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await logged_in(client, db)
        assert (await client.get("/admin")).status == 200
        await db.execute(text("UPDATE admin_sessions SET expires_at = now() - interval '1 s'"))
        assert (await client.get("/admin")).status == 401

        csrf = await logged_in(client, db)
        logout = await client.post("/admin/logout", data={"csrf": csrf}, allow_redirects=False)
        assert logout.status in (200, 303)
        assert (await client.get("/admin")).status == 401
    assert "logout" in await audit_actions(db)


async def test_removing_an_id_from_the_list_ends_its_sessions(db: AsyncConnection) -> None:
    admins = set(ADMINS)
    app = build_app(
        session_factory=bound_session_factory(db),
        notify=lambda page_id, delay: None,
        public_base_url="http://pages.test",
        admin_ids=lambda: frozenset(admins),
    )
    async with TestClient(TestServer(app)) as client:
        await logged_in(client, db)
        assert (await client.get("/admin")).status == 200
        admins.discard(ADMIN)
        assert (await client.get("/admin")).status == 401


async def test_every_post_refuses_a_missing_or_wrong_csrf_token(db: AsyncConnection) -> None:
    app = app_for(db)
    posts = [r for r in _admin_routes(app) if r[0] == "POST" and r not in admin_web.PUBLIC_ROUTES]
    assert posts
    async with TestClient(TestServer(app)) as client:
        csrf = await logged_in(client, db)
        answered = {}
        for _, path in posts:
            for sent in ({}, {"csrf": "wrong" + csrf[5:]}):
                response = await client.post(_concrete(path), data=sent, allow_redirects=False)
                answered[(path, "csrf" in sent)] = response.status
        assert (await client.get("/admin")).status == 200, "a refused POST must not end the session"
    assert set(answered.values()) == {403}, answered
    assert (await audit_actions(db)).count("csrf_refused") == len(answered)


# --- the audit log is append-only -------------------------------------------------------


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE admin_audit_log SET action = 'nothing'",
        "DELETE FROM admin_audit_log",
        "TRUNCATE admin_audit_log",
    ],
)
async def test_the_audit_log_cannot_be_rewritten(db: AsyncConnection, statement: str) -> None:
    await db.execute(text("INSERT INTO admin_audit_log (action) VALUES ('login')"))
    try:
        async with db.begin_nested():
            await db.execute(text(statement))
    except Exception as error:  # noqa: BLE001 - the message is the assertion
        refused = str(error)
    else:
        refused = ""
    assert "append-only" in refused, refused or f"{statement} was allowed"
