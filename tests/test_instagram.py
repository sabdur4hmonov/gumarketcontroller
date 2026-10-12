"""CP23 phase 3: Instagram story publishing -- built, OFF by default.

No test talks to Meta. `FakeMeta` is an aiohttp server answering the same
endpoints (instagram_graph.py lists them); the page server under test runs
too, and the fake FETCHES the story image from it exactly as Meta would.

  * off (the default) nothing is offered, queued or served, and the bot
    falls back to the downloadable story image;
  * connecting: owners only, a one-time hashed state, the token stored
    encrypted, replays and stale states refused;
  * publishing: quota asked first, a STORIES container from our short-lived
    unguessable URL, polled, published; the image wiped and the URL dead
    afterwards; every failure told to the author in the shop's language;
  * a token Meta calls invalid retires the connection; tokens near their end
    are refreshed daily; no token ever reaches a log or an error message;
  * tenancy: a shop's connection, uploads and drafts are its own.
"""

from __future__ import annotations

import io
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import aiohttp
import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestServer
from cryptography.fernet import Fernet
from PIL import Image
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import bound_session_factory

import gulbot.services.shop_tokens as shop_tokens_module
from gulbot.config import Settings, production_config_problems
from gulbot.models.announcement import AnnouncementDraft
from gulbot.models.instagram import InstagramConnection, InstagramOAuthState, InstagramStoryUpload
from gulbot.models.shop import DEFAULT_WORKING_HOURS, Shop
from gulbot.models.staff import ShopStaff
from gulbot.services import instagram
from gulbot.services.instagram_graph import Graph, GraphError
from gulbot.web.app import build_app

OWNER, CLERK, OTHER = 925001, 925002, 925003
IG_USER = "17841400000000001"
LONG = "IGAALONGtokenLONGtokenLONGtoken0001"
REFRESHED = "IGAAREFRESHEDtokenREFRESHED000002"
SHORT = "IGAASHORTtokenSHORTtokenSHORT00003"


def jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (1080, 1920), "#c36481").save(out, format="JPEG")
    return out.getvalue()


class FakeMeta:
    """The endpoints Meta documents, answering like Meta, recording calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.tokens_seen: list[str] = []
        self.statuses = ["IN_PROGRESS", "FINISHED"]
        self.quota = (0, 25)
        self.fail: dict[str, tuple[int, int]] = {}  # path key -> (http status, meta code)
        self.fetched: list[tuple[int, str, bytes]] = []

    def _error(self, key: str) -> web.Response | None:
        if key in self.fail:
            status, code = self.fail[key]
            return web.json_response({"error": {"code": code, "message": "nope"}}, status=status)
        return None

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_post("/oauth/access_token", self.short)
        app.router.add_get("/access_token", self.exchange)
        app.router.add_get("/refresh_access_token", self.refresh)
        app.router.add_get("/v21.0/me", self.me)
        app.router.add_get("/v21.0/{ig}/content_publishing_limit", self.limit)
        app.router.add_post("/v21.0/{ig}/media", self.media)
        app.router.add_post("/v21.0/{ig}/media_publish", self.publish)
        app.router.add_get("/v21.0/{container}", self.status)
        return app

    async def short(self, request: web.Request) -> web.Response:
        form = await request.post()
        self.calls.append(("short", str(form.get("code"))))
        return self._error("short") or web.json_response(
            {"access_token": SHORT, "user_id": int(IG_USER)}
        )

    async def exchange(self, request: web.Request) -> web.Response:
        self.calls.append(("exchange", request.query["grant_type"]))
        self.tokens_seen.append(request.query["access_token"])
        return self._error("exchange") or web.json_response(
            {"access_token": LONG, "token_type": "bearer", "expires_in": 5_184_000}
        )

    async def refresh(self, request: web.Request) -> web.Response:
        self.calls.append(("refresh", request.query["grant_type"]))
        self.tokens_seen.append(request.query["access_token"])
        return self._error("refresh") or web.json_response(
            {"access_token": REFRESHED, "token_type": "bearer", "expires_in": 5_184_000}
        )

    async def me(self, request: web.Request) -> web.Response:
        self.calls.append(("me", request.query["fields"]))
        return web.json_response({"user_id": IG_USER, "username": "gulshan_flowers"})

    async def limit(self, request: web.Request) -> web.Response:
        self.calls.append(("limit", request.match_info["ig"]))
        self.tokens_seen.append(request.query["access_token"])
        used, total = self.quota
        return self._error("limit") or web.json_response(
            {"data": [{"quota_usage": used, "config": {"quota_total": total}}]}
        )

    async def media(self, request: web.Request) -> web.Response:
        form = await request.post()
        self.calls.append(("media", str(form.get("media_type"))))
        self.tokens_seen.append(str(form.get("access_token")))
        refused = self._error("media")
        if refused:
            return refused
        # Meta fetches the image from the URL it was given.
        async with aiohttp.ClientSession() as http, http.get(str(form["image_url"])) as got:
            self.fetched.append((got.status, got.content_type, await got.read()))
        return web.json_response({"id": "900001"})

    async def status(self, request: web.Request) -> web.Response:
        self.calls.append(("status", request.match_info["container"]))
        state = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return web.json_response({"status_code": state, "id": request.match_info["container"]})

    async def publish(self, request: web.Request) -> web.Response:
        form = await request.post()
        self.calls.append(("publish", str(form.get("creation_id"))))
        return self._error("publish") or web.json_response({"id": "180000001"})


@pytest_asyncio.fixture
async def world(db: AsyncConnection, settings: Settings, monkeypatch) -> Any:
    sessions = bound_session_factory(db)
    async with sessions() as session:
        a = Shop(
            name="Gulshan",
            channel_id=-100925001,
            owner_telegram_ids=[OWNER],
            working_hours=DEFAULT_WORKING_HOURS,
            lang="ru",
        )
        b = Shop(
            name="B",
            channel_id=-100925002,
            owner_telegram_ids=[OTHER],
            working_hours=DEFAULT_WORKING_HOURS,
        )
        session.add_all([a, b])
        await session.flush()
        session.add(ShopStaff(shop_id=a.id, telegram_id=CLERK, added_by=OWNER))
        drafts = []
        for shop in (a, b):
            draft = AnnouncementDraft(
                shop_id=shop.id,
                author_id=OWNER,
                photos=["p"],
                fields={},
                preview_media=[],
                receipts=[],
                status="published",
            )
            session.add(draft)
            drafts.append(draft)
        await session.commit()
        ids = {"a": a.id, "b": b.id, "draft_a": drafts[0].id, "draft_b": drafts[1].id}

    meta = FakeMeta()
    meta_server = TestServer(meta.app())
    await meta_server.start_server()
    pages = build_app(
        session_factory=sessions,
        notify=lambda page_id, delay: None,
        public_base_url="https://pages.test",
        shop_panel_on=True,
    )
    page_server = TestServer(pages)
    await page_server.start_server()
    base = str(meta_server.make_url("")).rstrip("/")
    configured = settings.model_copy(
        update={
            "instagram_publishing_enabled": True,
            "instagram_app_id": "123456",
            "instagram_app_secret": SecretStr("app-secret-value"),
            "instagram_graph_url": base,
            "instagram_oauth_url": base,
            "instagram_authorize_url": "https://www.instagram.com/oauth/authorize",
            "public_base_url": str(page_server.make_url("")).rstrip("/"),
            "shop_token_encryption_key": SecretStr(Fernet.generate_key().decode()),
        }
    )
    monkeypatch.setattr(instagram, "get_settings", lambda: configured)
    monkeypatch.setattr(shop_tokens_module, "get_settings", lambda: configured)
    told: list[tuple[int, int, str]] = []

    async def notify(shop_id: int, chat_id: int, text_: str) -> None:
        told.append((shop_id, chat_id, text_))

    async with aiohttp.ClientSession() as http:
        yield {
            "db": db,
            "sessions": sessions,
            "meta": meta,
            "pages": page_server,
            "graph": Graph(instagram.graph_config(), http),
            "settings": configured,
            "told": told,
            "notify": notify,
            **ids,
        }
    await page_server.close()
    await meta_server.close()


class Pages:
    """Requests to the shared page server WITHOUT closing it afterwards
    (TestClient's context would, and the fake Meta still needs it)."""

    def __init__(self, server: TestServer) -> None:
        self.server = server

    async def __aenter__(self) -> Pages:
        self.http = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.http.close()

    async def get(self, path: str, **kwargs: Any) -> aiohttp.ClientResponse:
        response = await self.http.get(self.server.make_url(path), **kwargs)
        await response.read()
        return response


async def no_sleep(_: float) -> None:
    return None


async def connected(world: Any) -> None:
    async with world["sessions"]() as session:
        link = await instagram.start_connect(session, shop_id=world["a"], owner_id=OWNER)
        state = parse_qs(urlparse(link).query)["state"][0]
        await instagram.complete_connect(session, world["graph"], state=state, code="the-code")
        await session.commit()


async def queued(world: Any, shop: str = "a") -> tuple[int, str]:
    async with world["sessions"]() as session:
        upload, token = await instagram.queue_story(
            session,
            shop_id=world[shop],
            actor=OWNER,
            draft_id=world[f"draft_{shop}"],
            layout="arch",
            jpeg=jpeg(),
        )
        await session.commit()
    return upload, token


async def publish(world: Any, upload: int, token: str) -> str:
    return await instagram.publish_upload(
        world["sessions"],
        world["graph"],
        upload_id=upload,
        token=token,
        notify=world["notify"],
        sleep=no_sleep,
    )


# --- off by default --------------------------------------------------------------------


def test_publishing_is_off_by_default() -> None:
    assert Settings().instagram_publishing_enabled is False


def test_production_refuses_a_half_configured_switch() -> None:
    settings = Settings(
        environment="production",
        instagram_publishing_enabled=True,
        public_base_url="http://pages.example",
    )
    problems = " ".join(production_config_problems(settings, environ={}))
    assert "INSTAGRAM_APP_ID" in problems and "INSTAGRAM_APP_SECRET" in problems
    assert "PUBLIC_BASE_URL is not https" in problems


async def test_off_nothing_is_offered_queued_or_served(world, monkeypatch, settings) -> None:
    monkeypatch.setattr(instagram, "get_settings", lambda: settings)  # the real default: off
    assert not instagram.enabled()
    async with world["sessions"]() as session:
        with pytest.raises(instagram.InstagramRefused, match="off"):
            await instagram.start_connect(session, shop_id=world["a"], owner_id=OWNER)
        with pytest.raises(instagram.InstagramRefused, match="off"):
            await instagram.queue_story(
                session,
                shop_id=world["a"],
                actor=OWNER,
                draft_id=world["draft_a"],
                layout="arch",
                jpeg=b"x",
            )
    async with Pages(world["pages"]) as client:
        assert (await client.get("/ig/" + "a" * 43 + ".jpg")).status == 404
        assert (await client.get("/ig/callback?state=s&code=c")).status == 404


# --- connecting -------------------------------------------------------------------------


async def test_the_owner_connects_and_the_token_is_stored_encrypted(world) -> None:
    async with world["sessions"]() as session:
        link = await instagram.start_connect(session, shop_id=world["a"], owner_id=OWNER)
        query = parse_qs(urlparse(link).query)
        assert query["client_id"] == ["123456"]
        assert query["scope"] == ["instagram_business_basic,instagram_business_content_publish"]
        assert query["redirect_uri"] == [world["settings"].public_base_url + "/ig/callback"]
        state = query["state"][0]
        stored = await session.scalar(select(InstagramOAuthState.token_hash))
        assert stored != state and len(stored) == 64  # only the hash
        connection = await instagram.complete_connect(
            session, world["graph"], state=state, code="the-code"
        )
        await session.commit()
    assert (connection.ig_user_id, connection.username) == (IG_USER, "gulshan_flowers")
    assert LONG not in connection.token_encrypted
    assert shop_tokens_module.decrypt_access_token(connection.token_encrypted) == LONG
    remaining = connection.token_expires_at - datetime.now(UTC)
    assert timedelta(days=59) < remaining <= timedelta(days=60)
    assert world["meta"].tokens_seen == [SHORT]  # the short token was exchanged, nothing else


@pytest.mark.parametrize("who", [CLERK, OTHER, -1])
async def test_only_an_owner_starts_a_connection(world, who) -> None:
    async with world["sessions"]() as session:
        with pytest.raises(instagram.InstagramRefused, match="not_owner"):
            await instagram.start_connect(session, shop_id=world["a"], owner_id=who)


async def test_a_state_works_once_and_not_after_ten_minutes(world) -> None:
    async with world["sessions"]() as session:
        link = await instagram.start_connect(session, shop_id=world["a"], owner_id=OWNER)
        state = parse_qs(urlparse(link).query)["state"][0]
        await instagram.complete_connect(session, world["graph"], state=state, code="c")
        with pytest.raises(instagram.InstagramRefused, match="state_invalid"):
            await instagram.complete_connect(session, world["graph"], state=state, code="c")
        stale = await instagram.start_connect(session, shop_id=world["a"], owner_id=OWNER)
        await session.execute(text("UPDATE instagram_oauth_states SET expires_at = now()"))
        with pytest.raises(instagram.InstagramRefused, match="state_invalid"):
            await instagram.complete_connect(
                session, world["graph"], state=parse_qs(urlparse(stale).query)["state"][0], code="c"
            )
        with pytest.raises(instagram.InstagramRefused, match="state_invalid"):
            await instagram.complete_connect(session, world["graph"], state="made-up", code="c")


async def test_an_owner_removed_mid_flow_connects_nothing(world) -> None:
    async with world["sessions"]() as session:
        link = await instagram.start_connect(session, shop_id=world["a"], owner_id=OWNER)
        await session.execute(
            text("UPDATE shops SET owner_telegram_ids = '{}' WHERE id = :s"), {"s": world["a"]}
        )
        with pytest.raises(instagram.InstagramRefused, match="not_owner"):
            await instagram.complete_connect(
                session, world["graph"], state=parse_qs(urlparse(link).query)["state"][0], code="c"
            )
        assert await session.get(InstagramConnection, world["a"]) is None


async def test_a_refused_code_connects_nothing_and_spends_the_state(world) -> None:
    world["meta"].fail["short"] = (400, 100)
    async with world["sessions"]() as session:
        link = await instagram.start_connect(session, shop_id=world["a"], owner_id=OWNER)
        with pytest.raises(instagram.InstagramRefused, match="graph"):
            await instagram.complete_connect(
                session, world["graph"], state=parse_qs(urlparse(link).query)["state"][0], code="c"
            )
        assert await session.get(InstagramConnection, world["a"]) is None
        assert await session.scalar(select(InstagramOAuthState.used_at)) is not None


async def test_the_callback_route_connects_and_is_audited(world) -> None:
    async with world["sessions"]() as session:
        link = await instagram.start_connect(session, shop_id=world["a"], owner_id=OWNER)
        await session.commit()
    state = parse_qs(urlparse(link).query)["state"][0]
    async with Pages(world["pages"]) as client:
        ok = await client.get("/ig/callback", params={"state": state, "code": "c"})
        assert ok.status == 200 and "gulshan_flowers" in await ok.text()
        again = await client.get("/ig/callback", params={"state": state, "code": "c"})
        assert "Ulanmadi" in await again.text()
        denied = await client.get("/ig/callback?error=access_denied")
        assert "Ulanmadi" in await denied.text()
    async with world["sessions"]() as session:
        actions = (await session.scalars(text("SELECT action FROM shop_audit_log"))).all()
        assert "instagram_connected" in actions


# --- publishing ---------------------------------------------------------------------------


async def test_a_story_is_published_and_its_url_dies(world) -> None:
    await connected(world)
    upload, token = await queued(world)
    async with Pages(world["pages"]) as client:
        served = await client.get(f"/ig/{token}.jpg")
        assert served.status == 200 and served.content_type == "image/jpeg"
        assert (await client.get(f"/ig/{'x' * 43}.jpg")).status == 404
    assert await publish(world, upload, token) == "published"
    meta = world["meta"]
    assert [c[0] for c in meta.calls[-5:]] == ["limit", "media", "status", "status", "publish"]
    assert ("media", "STORIES") in meta.calls
    [(status, content_type, body)] = meta.fetched
    assert (status, content_type) == (200, "image/jpeg") and body == jpeg()
    assert set(meta.tokens_seen[-2:]) == {LONG}
    async with world["sessions"]() as session:
        row = await session.get(InstagramStoryUpload, upload)
        assert (row.status, row.media_id, row.image) == ("published", "180000001", None)
    async with Pages(world["pages"]) as client:
        assert (await client.get(f"/ig/{token}.jpg")).status == 404
    assert world["told"][-1] == (world["a"], OWNER, instagram.message("published", "ru"))


async def test_the_url_expires_on_its_own(world) -> None:
    await connected(world)
    upload, token = await queued(world)
    async with world["sessions"]() as session:
        await session.execute(
            text("UPDATE instagram_story_uploads SET expires_at = now() - interval '1 second'")
        )
        await session.commit()
    async with Pages(world["pages"]) as client:
        assert (await client.get(f"/ig/{token}.jpg")).status == 404


@pytest.mark.parametrize(
    ("setup", "code"),
    [
        (lambda m: setattr(m, "statuses", ["ERROR"]), "container_failed"),
        (lambda m: setattr(m, "statuses", ["IN_PROGRESS"]), "timeout"),
        (lambda m: setattr(m, "quota", (25, 25)), "quota"),
        (lambda m: m.fail.update(media=(400, 4)), "rate_limited"),
        (lambda m: m.fail.update(publish=(500, 2)), "graph"),
    ],
)
async def test_every_failure_is_wiped_and_told(world, setup, code) -> None:
    await connected(world)
    setup(world["meta"])
    upload, token = await queued(world)
    assert await publish(world, upload, token) == "failed"
    async with world["sessions"]() as session:
        row = await session.get(InstagramStoryUpload, upload)
        assert (row.status, row.error_code, row.image) == ("failed", code, None)
        connection = await session.get(InstagramConnection, world["a"])
        assert connection.status == "active"
    assert world["told"][-1] == (world["a"], OWNER, instagram.message(code, "ru"))
    if code == "quota":
        assert not any(call[0] == "media" for call in world["meta"].calls)


async def test_an_invalid_token_retires_the_connection(world) -> None:
    await connected(world)
    world["meta"].fail["media"] = (400, 190)
    upload, token = await queued(world)
    assert await publish(world, upload, token) == "failed"
    async with world["sessions"]() as session:
        connection = await session.get(InstagramConnection, world["a"])
        assert (connection.status, connection.last_error) == ("expired", "token_invalid")
        with pytest.raises(instagram.InstagramRefused, match="not_connected"):
            await instagram.queue_story(
                session,
                shop_id=world["a"],
                actor=OWNER,
                draft_id=world["draft_a"],
                layout="arch",
                jpeg=b"x",
            )
    assert world["told"][-1][2] == instagram.message("token_invalid", "ru")


async def test_a_redelivery_or_a_wrong_token_publishes_nothing_twice(world) -> None:
    await connected(world)
    upload, token = await queued(world)
    assert await publish(world, upload, "w" * 43) == "queued"
    assert not any(call[0] == "media" for call in world["meta"].calls)
    assert await publish(world, upload, token) == "published"
    calls = len(world["meta"].calls)
    assert await publish(world, upload, token) == "published"
    assert len(world["meta"].calls) == calls


async def test_a_shop_may_queue_at_most_its_daily_cap(world, monkeypatch) -> None:
    await connected(world)
    monkeypatch.setattr(instagram, "DAILY_CAP", 3)
    for _ in range(3):
        await queued(world)
    with pytest.raises(instagram.InstagramRefused, match="daily_cap"):
        await queued(world)


# --- tenancy -------------------------------------------------------------------------------


async def test_a_connection_serves_only_its_own_shop(world) -> None:
    await connected(world)  # shop A only
    with pytest.raises(instagram.InstagramRefused, match="not_connected"):
        await queued(world, "b")


async def test_an_upload_cannot_point_at_another_shops_draft(world) -> None:
    async with world["sessions"]() as session:
        session.add(
            InstagramStoryUpload(
                shop_id=world["a"],
                draft_id=world["draft_b"],
                actor=OWNER,
                layout="arch",
                token_hash="0" * 64,
                image=b"x",
                expires_at=datetime.now(UTC),
            )
        )
        with pytest.raises(IntegrityError, match="announcement_drafts"):
            await session.flush()


async def test_only_an_owner_disconnects_their_own_shop(world) -> None:
    await connected(world)
    async with world["sessions"]() as session:
        with pytest.raises(instagram.InstagramRefused, match="not_owner"):
            await instagram.disconnect(session, shop_id=world["a"], owner_id=OTHER)
        assert await instagram.disconnect(session, shop_id=world["b"], owner_id=OTHER) is False
        assert await session.get(InstagramConnection, world["a"]) is not None
        assert await instagram.disconnect(session, shop_id=world["a"], owner_id=OWNER) is True


# --- upkeep -----------------------------------------------------------------------------------


async def test_tokens_near_their_end_are_refreshed_and_dead_ones_retired(world) -> None:
    await connected(world)
    now = datetime.now(UTC)
    async with world["sessions"]() as session:
        connection = await session.get(InstagramConnection, world["a"])
        connection.token_expires_at = now + timedelta(days=40)
        await session.flush()
        assert (await instagram.refresh_tokens(session, world["graph"]))["refreshed"] == 0
        connection.token_expires_at = now + timedelta(days=5)
        await session.flush()
        assert (await instagram.refresh_tokens(session, world["graph"]))["refreshed"] == 1
        assert shop_tokens_module.decrypt_access_token(connection.token_encrypted) == REFRESHED
        assert connection.token_expires_at > now + timedelta(days=59)
        world["meta"].fail["refresh"] = (400, 190)
        connection.token_expires_at = now + timedelta(days=5)
        await session.flush()
        assert (await instagram.refresh_tokens(session, world["graph"]))["expired"] == 1
        assert connection.status == "expired"


async def test_upkeep_wipes_stale_uploads(world) -> None:
    await connected(world)
    upload, _ = await queued(world)
    async with world["sessions"]() as session:
        await session.execute(
            text("UPDATE instagram_story_uploads SET expires_at = now() - interval '1 minute'")
        )
        counts = await instagram.refresh_tokens(session, world["graph"])
        assert counts["uploads_expired"] == 1
        row = await session.get(InstagramStoryUpload, upload, populate_existing=True)
        assert (row.status, row.image) == ("expired", None)


# --- no secret anywhere ----------------------------------------------------------------------


async def test_no_token_reaches_a_log_or_an_error(world, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    await connected(world)
    upload, token = await queued(world)
    await publish(world, upload, token)
    async with world["sessions"]() as session:
        connection = await session.get(InstagramConnection, world["a"])
        connection.token_expires_at = datetime.now(UTC) + timedelta(days=1)
        await instagram.refresh_tokens(session, world["graph"])
    # Our own code's logs. The test HTTP servers' access logs are left out:
    # the fake Meta's are Meta's, and the production page server writes none
    # (test_the_page_server_writes_no_access_log).
    logged = "\n".join(
        record.getMessage() for record in caplog.records if record.name != "aiohttp.access"
    )
    for secret in (LONG, SHORT, REFRESHED, token, "app-secret-value"):
        assert secret not in logged
    # A transport failure's error carries no URL (a GET's URL carries the token).
    async with aiohttp.ClientSession() as http:
        dead = Graph(
            instagram.graph_config().__class__(
                **{**instagram.graph_config().__dict__, "graph_url": "http://127.0.0.1:9"}
            ),
            http,
        )
        with pytest.raises(GraphError) as failed:
            await dead.refresh(LONG)
    assert LONG not in str(failed.value) and "127.0.0.1" not in str(failed.value)
    assert failed.value.code == "network"


async def test_the_page_server_writes_no_access_log(monkeypatch) -> None:
    """Every /ig/<token>.jpg and /p/<token> path is a secret: the production
    page server must never log request lines."""
    import asyncio as _asyncio

    from gulbot.web import run

    seen: dict[str, Any] = {}

    class Runner:
        def __init__(self, app: Any, **kwargs: Any) -> None:
            seen.update(kwargs)

        async def setup(self) -> None:
            return None

        async def cleanup(self) -> None:
            return None

    class Site:
        def __init__(self, *args: Any) -> None:
            pass

        async def start(self) -> None:
            raise _asyncio.CancelledError  # stop before serving forever

    monkeypatch.setattr(run.web, "AppRunner", Runner)
    monkeypatch.setattr(run.web, "TCPSite", Site)
    monkeypatch.setattr(run, "build_session_factory", lambda: None)
    with pytest.raises(_asyncio.CancelledError):
        await run.main()
    assert "access_log" in seen and seen["access_log"] is None
