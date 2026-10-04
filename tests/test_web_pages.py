"""The public pages, through the real aiohttp app and real Postgres.

What a stranger with a link can do, and what they cannot: every response is
noindex and carries the strict CSP; everything typed is escaped; no phone
number ever appears; a POST without the page's own header is refused; a
deleted or expired page shows nothing that was typed into it.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from datetime import date, time, timedelta
from decimal import Decimal
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import bound_session_factory
from tests.test_share_pages_service import invite, make_customer, make_shop, yesno

from gulbot.models.share_page import PAGE_LANGUAGES, PAGE_TEMPLATES
from gulbot.services import share_pages
from gulbot.web import app as web_app
from gulbot.web.app import CSP, build_app

pytestmark = pytest.mark.infra

HOSTILE = "<script>alert(1)</script>\"'&<img src=x onerror=alert(2)>"
JSON_HEADERS = {"X-Requested-With": "gulbot", "Content-Type": "application/json"}


class World:
    def __init__(self, db: AsyncConnection, client: TestClient, notified: list[int]) -> None:
        self.db, self.client, self.notified = db, client, notified
        self.session = bound_session_factory(db)()

    async def page(self, draft: object, *, shop_name: str = "Lola gullari", user: int = 601) -> Any:
        shop = await make_shop(self.db, shop_name)
        customer = await make_customer(self.db, shop, user)
        page = await share_pages.create_page(
            self.session,
            shop_id=shop,
            customer_id=customer,
            bot_username="lola_gullar_bot",
            draft=draft,  # type: ignore[arg-type]
        )
        await self.session.commit()
        return page


@pytest.fixture
async def world(db: AsyncConnection) -> AsyncIterator[World]:
    notified: list[int] = []

    async def notify(page_id: int, delay: float = 0) -> None:
        if not delay:
            notified.append(page_id)

    app = build_app(
        session_factory=bound_session_factory(db),
        notify=notify,
        public_base_url="http://127.0.0.1:8088",
        yes_limit=5,
        rsvp_limit=5,
    )
    async with TestClient(TestServer(app)) as client:
        yield World(db, client, notified)


def _near(days: int = 40) -> date:
    return date.today() + timedelta(days=days)


# --- headers -------------------------------------------------------------------


async def test_every_page_is_unlisted_and_locked_down(world: World) -> None:
    page = await world.page(yesno())
    for path in (f"/p/{page.token}", "/p/" + "x" * 22, "/robots.txt", "/demo/yesno/milliy"):
        response = await world.client.get(path)
        headers = response.headers
        assert headers.get("Content-Security-Policy") == CSP, path
        assert headers.get("X-Robots-Tag", "").startswith("noindex"), path
        assert headers.get("Referrer-Policy") == "no-referrer", path
        assert headers.get("X-Frame-Options") == "DENY", path
        assert headers.get("X-Content-Type-Options") == "nosniff", path
    body = await (await world.client.get(f"/p/{page.token}")).text()
    assert '<meta name="robots" content="noindex' in body
    assert (await (await world.client.get("/robots.txt")).text()) == "User-agent: *\nDisallow: /\n"


async def test_the_csp_allows_nothing_inline_and_nothing_foreign() -> None:
    assert "'unsafe-inline'" not in CSP and "'unsafe-eval'" not in CSP
    assert "http" not in CSP  # no third-party origin anywhere
    for directive in (
        "default-src 'none'",
        "script-src 'self'",
        "style-src 'self'",
        "frame-ancestors 'none'",
    ):
        assert directive in CSP


async def test_no_page_has_inline_script_or_style(world: World) -> None:
    page = await world.page(invite(event_date=_near()))
    body = await (await world.client.get(f"/p/{page.token}")).text()
    assert not re.search(r"<script(?![^>]*\bsrc=)", body)
    assert " style=" not in body and "<style" not in body
    assert not re.search(r"\son[a-z]+=", body)  # no event-handler attributes


# --- escaping and privacy --------------------------------------------------------


async def test_everything_typed_is_escaped(world: World) -> None:
    question = await world.page(
        yesno(question=HOSTILE, question_preset="custom"), shop_name=HOSTILE
    )
    card = await world.page(
        invite(
            name_1=HOSTILE[:60],
            name_2=HOSTILE[:60],
            venue=HOSTILE,
            message=HOSTILE,
            event_date=_near(),
        ),
        shop_name=HOSTILE,
        user=602,
    )
    for page in (question, card):
        body = await (await world.client.get(f"/p/{page.token}")).text()
        assert "<script>alert" not in body
        assert "<img src=x" not in body
        assert "&lt;script&gt;" in body


async def test_no_phone_number_is_ever_on_a_page(world: World) -> None:
    """make_customer gives every creator +998901234567."""
    page = await world.page(invite(event_date=_near()))
    for path in (f"/p/{page.token}", f"/p/{page.token}/event.ics"):
        body = await (await world.client.get(path)).text()
        assert "998901234567" not in body
        assert not re.search(r"\+?998[\s-]?\d{2}", body)


# --- the life of a page -------------------------------------------------------------


async def test_unknown_and_malformed_tokens_are_404(world: World) -> None:
    for token in ("x" * 22, "short", "../etc/passwd", "a" * 40):
        response = await world.client.get(f"/p/{token}")
        assert response.status == 404


async def test_a_deleted_page_is_gone_and_shows_nothing_typed(world: World) -> None:
    page = await world.page(invite(name_1="Sardorbek", venue="Chilonzor 5", event_date=_near()))
    owner = page.customer_id
    assert await share_pages.delete_page(
        world.session, shop_id=page.shop_id, customer_id=owner, page_id=page.id
    )
    await world.session.commit()
    response = await world.client.get(f"/p/{page.token}")
    assert response.status == 410
    body = await response.text()
    assert "Sardorbek" not in body and "Chilonzor" not in body


async def test_views_are_counted_but_not_telegrams_preview(world: World) -> None:
    page = await world.page(yesno())
    await world.client.get(f"/p/{page.token}")
    await world.client.get(
        f"/p/{page.token}", headers={"User-Agent": "TelegramBot (like TwitterBot)"}
    )
    await world.client.get(f"/p/{page.token}")
    views = await world.db.scalar(
        text("SELECT view_count FROM share_pages WHERE id = :id"), {"id": page.id}
    )
    assert views == 2


async def test_the_link_preview_does_not_give_the_question_away(world: World) -> None:
    page = await world.page(yesno(question="Menga turmushga chiqasanmi?"))
    body = await (await world.client.get(f"/p/{page.token}")).text()
    og = re.findall(r'<meta property="og:[a-z]+" content="([^"]*)"', body)
    assert og and not any("turmushga" in value for value in og)


# --- Ha -------------------------------------------------------------------------


async def test_ha_without_the_pages_own_header_is_refused(world: World) -> None:
    page = await world.page(yesno())
    plain_form = await world.client.post(f"/p/{page.token}/yes", data={"a": "b"})
    assert plain_form.status == 403
    wrong_type = await world.client.post(
        f"/p/{page.token}/yes", data="{}", headers={"X-Requested-With": "gulbot"}
    )
    assert wrong_type.status == 415
    foreign = await world.client.post(
        f"/p/{page.token}/yes",
        data="{}",
        headers={**JSON_HEADERS, "Origin": "https://evil.example"},
    )
    assert foreign.status == 403
    answered = await world.db.scalar(
        text("SELECT answered_at FROM share_pages WHERE id = :id"), {"id": page.id}
    )
    assert answered is None


async def test_ha_notifies_once_however_often_it_is_pressed(world: World) -> None:
    page = await world.page(yesno())
    for _ in range(3):
        response = await world.client.post(f"/p/{page.token}/yes", data="{}", headers=JSON_HEADERS)
        assert response.status == 200
    assert world.notified == [page.id]


async def test_ha_is_rate_limited_per_address(world: World) -> None:
    page = await world.page(yesno(notify_creator=False))
    statuses = [
        (await world.client.post(f"/p/{page.token}/yes", data="{}", headers=JSON_HEADERS)).status
        for _ in range(7)
    ]
    assert statuses[:5] == [200] * 5 and statuses[5:] == [429, 429]


async def test_ha_on_an_invitation_is_404(world: World) -> None:
    page = await world.page(invite(event_date=_near()))
    response = await world.client.post(f"/p/{page.token}/yes", data="{}", headers=JSON_HEADERS)
    assert response.status == 404


# --- RSVP -----------------------------------------------------------------------


async def test_rsvp_is_kept_per_browser(world: World) -> None:
    page = await world.page(invite(event_date=_near()))
    url = f"/p/{page.token}/rsvp"
    first = await world.client.post(
        url,
        data=json.dumps({"answer": "yes", "guests": 3, "name": "Dilnoza"}),
        headers=JSON_HEADERS,
    )
    assert first.status == 200
    cookie = first.cookies["gb_rsvp"]
    assert (
        cookie["httponly"]
        and cookie["samesite"] == "Strict"
        and cookie["path"] == f"/p/{page.token}"
    )
    # The same browser (the client keeps the cookie) changes its mind.
    again = await world.client.post(
        url, data=json.dumps({"answer": "no", "guests": 0}), headers=JSON_HEADERS
    )
    assert again.status == 200
    summary = await share_pages.rsvp_summary(world.session, shop_id=page.shop_id, page_id=page.id)
    assert summary == share_pages.RsvpSummary(coming=0, guests=0, not_coming=1)


@pytest.mark.parametrize(
    "body",
    [
        "not json",
        "[1, 2]",
        json.dumps({"answer": "yes", "guests": "3"}),
        json.dumps({"answer": "yes", "guests": True}),
        json.dumps({"answer": "yes", "guests": 99}),
        json.dumps({"answer": "maybe", "guests": 1}),
        json.dumps({"answer": "yes", "guests": 1, "name": 5}),
    ],
)
async def test_rsvp_refuses_what_the_form_cannot_send(world: World, body: str) -> None:
    page = await world.page(invite(event_date=_near()))
    response = await world.client.post(f"/p/{page.token}/rsvp", data=body, headers=JSON_HEADERS)
    assert response.status == 400


async def test_rsvp_body_size_is_capped(world: World) -> None:
    page = await world.page(invite(event_date=_near()))
    huge = json.dumps({"answer": "yes", "guests": 1, "name": "x" * 10_000})
    response = await world.client.post(f"/p/{page.token}/rsvp", data=huge, headers=JSON_HEADERS)
    assert response.status == 413


# --- the shop's link --------------------------------------------------------------


async def test_the_shop_link_counts_and_goes_to_that_shops_bot(world: World) -> None:
    page = await world.page(yesno())
    response = await world.client.get(f"/p/{page.token}/go", allow_redirects=False)
    assert response.status == 302
    assert response.headers["Location"] == f"https://t.me/lola_gullar_bot?start=pg_{page.token}"
    clicks = await world.db.scalar(
        text("SELECT cta_click_count FROM share_pages WHERE id = :id"), {"id": page.id}
    )
    assert clicks == 1


async def test_a_page_without_a_known_bot_has_no_link_out(world: World) -> None:
    page = await world.page(yesno())
    await world.db.execute(
        text("UPDATE share_pages SET bot_username = 'bad name!' WHERE id = :id"), {"id": page.id}
    )
    response = await world.client.get(f"/p/{page.token}/go", allow_redirects=False)
    assert response.headers["Location"] == f"/p/{page.token}"


# --- the invitation's extras -------------------------------------------------------


async def test_the_calendar_file(world: World) -> None:
    page = await world.page(
        invite(event_date=_near(), event_time=time(18, 30), venue="Navro'z, Toshkent; 2-zal")
    )
    response = await world.client.get(f"/p/{page.token}/event.ics")
    assert response.status == 200
    assert response.content_type == "text/calendar"
    body = await response.text()
    assert "BEGIN:VEVENT" in body and "DTSTART:" in body
    assert "LOCATION:Navro'z\\, Toshkent\\; 2-zal" in body
    assert "GEO:41.311081;69.240562" in body


async def test_the_map_links_carry_only_numbers(world: World) -> None:
    page = await world.page(invite(event_date=_near(), location=(Decimal("41.3"), Decimal("69.2"))))
    body = await (await world.client.get(f"/p/{page.token}")).text()
    assert "https://www.google.com/maps/search/?api=1&amp;query=41.300000,69.200000" in body


# --- every design, every language --------------------------------------------------


@pytest.mark.parametrize("theme", PAGE_TEMPLATES)
async def test_every_design_renders_in_every_language(world: World, theme: str) -> None:
    for kind in ("yesno", "invite"):
        for lang in PAGE_LANGUAGES:
            response = await world.client.get(f"/demo/{kind}/{theme}?lang={lang}")
            assert response.status == 200, (kind, theme, lang)
            body = await response.text()
            assert f"theme-{theme}.css" in body
    gallery = await world.client.get("/demo/invite?lang=ru")
    assert gallery.status == 200


async def test_static_files_are_cached_and_never_listed(world: World) -> None:
    css = await world.client.get("/static/css/base.css")
    assert css.status == 200 and "immutable" in css.headers["Cache-Control"]
    assert (await world.client.get("/static/")).status in (403, 404)
    assert (await world.client.get("/static/../app.py")).status in (403, 404)


def test_the_rate_limiter_forgets_old_hits() -> None:
    now = [0.0]
    limiter = web_app.RateLimiter(limit=2, window=60, now=lambda: now[0])
    assert limiter.allow("a") and limiter.allow("a") and not limiter.allow("a")
    assert limiter.allow("b")
    now[0] = 61
    assert limiter.allow("a")


def test_the_rate_limiter_cannot_grow_without_bound() -> None:
    limiter = web_app.RateLimiter(limit=1, window=60, max_keys=100)
    for n in range(1000):
        limiter.allow(str(n))
    assert len(limiter._hits) == 100  # noqa: SLF001
