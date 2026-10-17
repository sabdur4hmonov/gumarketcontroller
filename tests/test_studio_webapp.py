"""CP27.4: Taklifnoma Studio as a Telegram Mini App, fully offline.

Launch data is crafted here by Telegram's own published rule (HMAC-SHA256
over the sorted data-check-string, key = HMAC-SHA256("WebAppData", token)),
independently of the code under test, and posted as the Mini App page would.

- valid data from THIS shop's bot opens the same studio session a link does;
- tampered, stale, future-dated, another shop's bot's, or replayed data is
  refused, and so is a Telegram user who is not this shop's customer, or a
  paused shop; the legacy shop is checked with the process BOT_TOKEN;
- the POST needs JSON and X-Requested-With (a cross-site form cannot send it);
- the page loads only our own script, no telegram.org script, no inline code;
- the bot offers the Mini App button only when the site is https.
"""

# ruff: noqa: F811  (the `world` fixture is imported by name)

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from typing import Any
from urllib.parse import urlencode

import pytest
from aiohttp.test_utils import TestClient, TestServer
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.share_pages_harness import ShopBot
from tests.test_studio_web import app_for, world  # noqa: F401  (fixture)

from gulbot.bot.callbacks import PageMenuCB
from gulbot.config import Settings, get_settings
from gulbot.services import shop_tokens, studio_webapp
from gulbot.web import links
from gulbot.web import studio as studio_web

pytestmark = pytest.mark.infra

TOKEN_A = "700000001:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
TOKEN_B = "700000002:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
TOKEN_LEGACY = "700000003:LLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLLL"
USER_A = 771_001  # world's customer of shop A
HEADERS = {"X-Requested-With": "gulbot", "Content-Type": "application/json"}


def init_data(
    token: str, *, user_id: int, auth_date: int | None = None, query_id: str = "Q1"
) -> str:
    """Launch data exactly as Telegram signs it (core.telegram.org/bots/webapps)."""
    fields = {
        "query_id": query_id,
        "user": json.dumps({"id": user_id, "first_name": "Ali"}, separators=(",", ":")),
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


@pytest.fixture
def keyed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Fernet key for shop tokens, and a known process BOT_TOKEN."""
    moved = get_settings().model_copy(
        update={
            "shop_token_encryption_key": SecretStr(Fernet.generate_key().decode()),
            "bot_token": SecretStr(TOKEN_LEGACY),
        }
    )
    monkeypatch.setattr(shop_tokens, "get_settings", lambda: moved)
    monkeypatch.setattr(studio_webapp, "get_settings", lambda: moved)


async def _tokens(db: AsyncConnection, world: dict[str, Any]) -> None:
    for shop, token in ((world["a"], TOKEN_A), (world["b"], TOKEN_B)):
        await db.execute(
            text("UPDATE shops SET bot_token_encrypted = :t WHERE id = :s"),
            {"t": shop_tokens.encrypt_token(token), "s": shop},
        )


async def _post(client: TestClient, shop: int, data: str, **extra: Any) -> Any:
    body = {"shop": str(shop), "init_data": data, "bot": "lola_bot", **extra}
    return await client.post("/studio/webapp", data=json.dumps(body), headers=HEADERS)


async def test_valid_launch_data_opens_the_same_session(world: dict[str, Any], keyed: None) -> None:  # noqa: F811
    db = world["db"]
    await _tokens(db, world)
    async with TestClient(TestServer(app_for(db))) as client:
        response = await _post(client, world["a"], init_data(TOKEN_A, user_id=USER_A))
        assert response.status == 200, await response.text()
        assert (await response.json()) == {"ok": True, "next": "/studio"}
        cookie = response.cookies[studio_web.COOKIE]
        assert cookie["httponly"] and cookie["samesite"] == "Lax" and cookie["path"] == "/studio"
        client.session.cookie_jar.update_cookies({studio_web.COOKIE: cookie.value})
        assert (await client.get("/studio")).status == 200
    row = (
        await db.execute(
            text("SELECT customer_id, bot_username FROM studio_sessions ORDER BY id DESC LIMIT 1")
        )
    ).one()
    assert (row.customer_id, row.bot_username) == (world["ca"], "lola_bot")
    assert (
        await db.scalar(text("SELECT count(*) FROM studio_audit_log WHERE action = 'webapp_login'"))
        == 1
    )


@pytest.mark.parametrize(
    "case",
    ["tampered", "stale", "future", "other_shops_bot", "no_hash", "garbage", "huge"],
)
async def test_bad_launch_data_is_refused(world: dict[str, Any], keyed: None, case: str) -> None:  # noqa: F811
    db = world["db"]
    await _tokens(db, world)
    now = int(time.time())
    data = {
        "tampered": init_data(TOKEN_A, user_id=USER_A).replace(str(USER_A), "771002"),
        "stale": init_data(TOKEN_A, user_id=USER_A, auth_date=now - 3601 - 5),
        "future": init_data(TOKEN_A, user_id=USER_A, auth_date=now + 600),
        "other_shops_bot": init_data(TOKEN_B, user_id=USER_A),
        "no_hash": re.sub(r"&hash=[0-9a-f]+", "", init_data(TOKEN_A, user_id=USER_A)),
        "garbage": "%%%not-a-query",
        "huge": init_data(TOKEN_A, user_id=USER_A, query_id="Q" * 5000),
    }[case]
    async with TestClient(TestServer(app_for(db))) as client:
        response = await _post(client, world["a"], data)
        # Oversize launch data is stopped by the app's 4 KB body cap (413).
        assert response.status == (413 if case == "huge" else 403), case
        assert studio_web.COOKIE not in response.cookies
    assert await db.scalar(text("SELECT count(*) FROM studio_sessions")) == 0


async def test_launch_data_opens_one_session_only(world: dict[str, Any], keyed: None) -> None:  # noqa: F811
    db = world["db"]
    await _tokens(db, world)
    data = init_data(TOKEN_A, user_id=USER_A)
    async with TestClient(TestServer(app_for(db))) as client:
        assert (await _post(client, world["a"], data)).status == 200
        assert (await _post(client, world["a"], data)).status == 403
    assert await db.scalar(text("SELECT count(*) FROM studio_sessions")) == 1
    assert (
        await db.scalar(text("SELECT count(*) FROM studio_audit_log WHERE reason = 'replay'")) == 1
    )


async def test_only_this_shops_entitled_customer(world: dict[str, Any], keyed: None) -> None:  # noqa: F811
    db = world["db"]
    await _tokens(db, world)
    async with TestClient(TestServer(app_for(db))) as client:
        stranger = await _post(client, world["a"], init_data(TOKEN_A, user_id=999_999))
        assert stranger.status == 403
        # Shop B's customer, signed by shop A's bot, is not shop A's customer.
        theirs = await _post(client, world["a"], init_data(TOKEN_A, user_id=772_002))
        assert theirs.status == 403
        await db.execute(
            text("UPDATE shops SET status = 'paused' WHERE id = :s"), {"s": world["a"]}
        )
        paused = await _post(client, world["a"], init_data(TOKEN_A, user_id=USER_A, query_id="Q2"))
        assert paused.status == 403
        unknown = await _post(
            client, 987_654_321, init_data(TOKEN_A, user_id=USER_A, query_id="Q3")
        )
        assert unknown.status == 403
    assert await db.scalar(text("SELECT count(*) FROM studio_sessions")) == 0


async def test_the_legacy_shop_is_checked_with_the_process_token(
    world: dict[str, Any], keyed: None
) -> None:  # noqa: F811
    db = world["db"]
    await db.execute(
        text("UPDATE shops SET uses_process_bot_token = true WHERE id = :s"), {"s": world["a"]}
    )
    async with TestClient(TestServer(app_for(db))) as client:
        own = await _post(client, world["a"], init_data(TOKEN_A, user_id=USER_A))
        assert own.status == 403, "a shop with no stored token has no key but the process token"
        legacy = await _post(
            client, world["a"], init_data(TOKEN_LEGACY, user_id=USER_A, query_id="L")
        )
        assert legacy.status == 200


async def test_the_post_needs_json_and_the_header(world: dict[str, Any], keyed: None) -> None:  # noqa: F811
    db = world["db"]
    await _tokens(db, world)
    data = init_data(TOKEN_A, user_id=USER_A)
    async with TestClient(TestServer(app_for(db))) as client:
        form = await client.post(
            "/studio/webapp", data={"shop": str(world["a"]), "init_data": data}
        )
        assert form.status == 403
        bare = await client.post(
            "/studio/webapp",
            data=json.dumps({"shop": str(world["a"]), "init_data": data}),
            headers={"Content-Type": "application/json"},
        )
        assert bare.status == 403
        broken = await client.post("/studio/webapp", data="{", headers=HEADERS)
        assert broken.status == 400
    assert await db.scalar(text("SELECT count(*) FROM studio_sessions")) == 0


async def test_the_page_loads_only_our_own_script(world: dict[str, Any]) -> None:  # noqa: F811
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        page = await client.get("/studio/app?s=5&b=lola_bot")
        body = await page.text()
        odd = await (await client.get('/studio/app?s=<x>&b="><script>')).text()
    assert page.status == 200
    assert 'data-shop="5"' in body and 'data-bot="lola_bot"' in body
    scripts = re.findall(r"<script[^>]*>", body)
    assert scripts and all(re.search(r'src="/static/js/[a-z-]+\.js\?v=', s) for s in scripts)
    assert "telegram.org" not in body and "<script>" not in body.replace("<script src", "")
    assert "form-action 'self'" in page.headers["Content-Security-Policy"]
    assert 'data-shop=""' in odd and 'data-bot=""' in odd and "<x>" not in odd


@pytest.mark.parametrize(
    ("base", "offered"), [("https://pages.uz", True), ("http://127.0.0.1:8088", False)]
)
async def test_the_bot_offers_the_mini_app_only_on_https(
    db: AsyncConnection, monkeypatch: pytest.MonkeyPatch, base: str, offered: bool
) -> None:
    from tests.share_pages_harness import make_shop

    moved: Settings = get_settings().model_copy(update={"public_base_url": base})
    monkeypatch.setattr(links, "get_settings", lambda: moved)
    shop = await make_shop(db, "Lola gullari")
    bot = ShopBot(db, shop, bot_id=424_401, username="lola_gullar_bot")
    await bot.tap(PageMenuCB(action="studio").pack(), user=881_101)
    markup = bot.markups()[-1]
    buttons = [b for row in (markup.inline_keyboard if markup else []) for b in row]
    apps = [b.web_app.url for b in buttons if b.web_app is not None]
    if offered:
        assert apps == [f"https://pages.uz/studio/app?s={shop}&b=lola_gullar_bot"]
    else:
        assert apps == []
