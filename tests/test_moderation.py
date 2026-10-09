"""CP18 moderation: a platform admin hides an abusive page or a guest's wish.

- A hidden page is, to the public, gone -- on EVERY /p/<token> route, found
  by walking the router so a route added later cannot be forgotten -- and
  nothing a visitor does on it is recorded. The creator's text is kept: a
  hide is reversible, unlike deletion, and showing it again restores it.
- A hidden wish disappears from the wall, and the creator's own show/hide
  switch cannot bring it back.
- Each hide needs a reason; each is audited.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import bound_session_factory
from tests.test_share_pages_service import invite, make_customer, make_shop

from gulbot.services import share_page_wishes, share_pages, shop_admin
from gulbot.services.admin_auth import Admin
from gulbot.web.app import build_app

pytestmark = pytest.mark.infra

ADMIN = Admin(telegram_id=7_200_001, csrf="c" * 43, session_id=0)
JSON = {"Content-Type": "application/json", "X-Requested-With": "gulbot"}


@pytest.fixture
async def page(db: AsyncConnection) -> dict[str, Any]:
    """A live invitation with RSVP and a wish wall, and one wish on it."""
    shop = await make_shop(db, "Moderated")
    customer = await make_customer(db, shop, 990_501)
    async with bound_session_factory(db)() as session:
        made = await share_pages.create_page(
            session, shop_id=shop, customer_id=customer, bot_username="mod_bot", draft=invite()
        )
        await session.flush()
        await share_pages.update_page(
            session,
            shop_id=shop,
            customer_id=customer,
            page_id=made.id,
            changes={"wishes_enabled": True},
        )
        wish = await share_page_wishes.leave_wish(
            session, made.token, voter_key="v" * 22, author="Mehmon", body="Baxtli bo'linglar"
        )
        await session.commit()
    wish_id = await db.scalar(
        text("SELECT id FROM share_page_wishes WHERE page_id = :p"), {"p": made.id}
    )
    assert wish is not None
    return {
        "db": db,
        "shop": shop,
        "customer": customer,
        "id": made.id,
        "token": made.token,
        "wish": wish_id,
    }


async def hide(page: dict[str, Any], hidden: bool, reason: str | None = "spam") -> object:
    async with bound_session_factory(page["db"])() as session:
        try:
            after = await shop_admin.set_page_hidden(
                session,
                admin=ADMIN,
                page_id=page["id"],
                hidden=hidden,
                reason=reason,
                ip="198.51.100.1",
            )
        except Exception as error:  # noqa: BLE001 - the type is the assertion
            await session.rollback()
            return error
        await session.commit()
        return after


def app_for(db: AsyncConnection) -> Any:
    return build_app(
        session_factory=bound_session_factory(db),
        notify=lambda page_id, delay: None,
        public_base_url="http://pages.test",
    )


def _public_routes(app: Any) -> list[tuple[str, str]]:
    found = []
    for route in app.router.routes():
        canonical = route.resource.canonical if route.resource is not None else ""
        if canonical.startswith("/p/{token}") and route.method in ("GET", "POST"):
            found.append((route.method, canonical))
    return found


async def counters(db: AsyncConnection, page_id: int) -> tuple[Any, ...]:
    return tuple(
        (
            await db.execute(
                text(
                    "SELECT view_count, cta_click_count, answered_at, chosen_place, "
                    " (SELECT count(*) FROM share_page_rsvps WHERE page_id = :p), "
                    " (SELECT count(*) FROM share_page_wishes WHERE page_id = :p) "
                    "FROM share_pages WHERE id = :p"
                ),
                {"p": page_id},
            )
        ).one()
    )


@pytest.fixture
async def walk(page: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Everything a visitor could act on, so that every route has something
    REAL to refuse: the invitation gets a photo, and a Ha/Yo'q page with a
    date plan is answered (so /choose has valid options waiting)."""
    import io
    from datetime import UTC, datetime, timedelta

    from PIL import Image
    from tests.share_pages_harness import every_customer_has_the_gift
    from tests.test_share_pages_service import yesno

    from gulbot.services import share_page_photos

    every_customer_has_the_gift(monkeypatch)
    db = page["db"]
    jpeg = io.BytesIO()
    Image.new("RGB", (40, 30), (90, 120, 200)).save(jpeg, "JPEG")
    slot = (datetime.now(UTC) + timedelta(days=3)).replace(minute=0, second=0, microsecond=0)
    async with bound_session_factory(db)() as session:
        photo = await share_page_photos.store_photo(
            session,
            shop_id=page["shop"],
            customer_id=page["customer"],
            page_id=page["id"],
            raw=jpeg.getvalue(),
        )
        question = await share_pages.create_page(
            session,
            shop_id=page["shop"],
            customer_id=page["customer"],
            bot_username="mod_bot",
            draft=yesno(places=("Kino",), slots=(slot,)),
        )
        await session.flush()
        await share_pages.answer_yes(session, question.token)
        await session.commit()
    assert photo is not None
    options = dict(
        (
            await db.execute(
                text("SELECT kind, id FROM share_page_options WHERE page_id = :p"),
                {"p": question.id},
            )
        ).all()
    )
    return {
        "pages": {"invite": (page["id"], page["token"]), "yesno": (question.id, question.token)},
        "photo": photo.id,
        "options": options,
    }


async def test_a_hidden_page_is_gone_on_every_public_route_and_records_nothing(
    page: dict[str, Any], walk: dict[str, Any]
) -> None:
    db = page["db"]
    for page_id, _ in walk["pages"].values():
        assert isinstance(await hide({"db": db, "id": page_id}, True), dict)
    app = app_for(db)
    routes = _public_routes(app)
    assert len(routes) >= 8, routes  # page, yes, rsvp, choose, wish, go, ics, photo
    before = {k: await counters(db, pid) for k, (pid, _) in walk["pages"].items()}
    body = (
        '{"answer": "yes", "guests": 1, "name": "x", "text": "y", '
        f'"place": {walk["options"]["place"]}, "slot": {walk["options"]["slot"]}}}'
    )
    answered: dict[tuple[str, str, str], int] = {}
    async with TestClient(TestServer(app)) as client:
        for kind, (_, token) in walk["pages"].items():
            for method, path in routes:
                url = re.sub(r"\{photo_id[^}]*\}", str(walk["photo"]), path)
                response = await client.request(
                    method,
                    url.replace("{token}", token),
                    data=body if method == "POST" else None,
                    headers=JSON,
                    allow_redirects=False,
                )
                answered[(kind, method, path)] = response.status
                if path == "/p/{token}/go":
                    assert response.headers.get("Location", "").startswith("/p/"), (
                        "left for the bot"
                    )
    reachable = {k: v for k, v in answered.items() if v not in (302, 400, 404, 410)}
    assert not reachable, reachable
    after = {k: await counters(db, pid) for k, (pid, _) in walk["pages"].items()}
    assert after == before, "a hidden page recorded a visitor's action"


async def test_a_hidden_page_keeps_its_text_and_comes_back_when_shown_again(
    page: dict[str, Any],
) -> None:
    await hide(page, True)
    async with TestClient(TestServer(app_for(page["db"]))) as client:
        hidden = await client.get(f"/p/{page['token']}")
        assert hidden.status == 410
        assert "Aziz" not in await hidden.text()
        venue = await page["db"].scalar(
            text("SELECT venue FROM share_pages WHERE id = :p"), {"p": page["id"]}
        )
        assert venue, "hiding scrubbed the creator's text"
        await hide(page, False, reason=None)
        shown = await client.get(f"/p/{page['token']}")
        assert shown.status == 200 and "Aziz" in await shown.text()
    actions = list(
        (await page["db"].execute(text("SELECT action FROM admin_audit_log ORDER BY id"))).scalars()
    )
    assert actions == ["page_hide", "page_unhide"]


async def test_hiding_needs_a_reason_and_the_database_insists_too(page: dict[str, Any]) -> None:
    refused = await hide(page, True, reason="   ")
    assert isinstance(refused, shop_admin.ActionRefused) and refused.reason == "reason", repr(
        refused
    )
    db = page["db"]
    assert (
        await db.scalar(text("SELECT hidden_at FROM share_pages WHERE id = :p"), {"p": page["id"]})
        is None
    )
    try:
        async with db.begin_nested():
            await db.execute(
                text("UPDATE share_pages SET hidden_at = now() WHERE id = :p"), {"p": page["id"]}
            )
    except Exception as error:  # noqa: BLE001 - the constraint's name is the assertion
        message = str(error)
    else:
        message = ""
    assert "ck_share_pages_hidden_has_reason" in message, message or "accepted"


async def test_a_hidden_wish_leaves_the_wall_and_the_creator_cannot_bring_it_back(
    page: dict[str, Any],
) -> None:
    db = page["db"]
    async with bound_session_factory(db)() as session:
        await shop_admin.hide_wish(
            session, admin=ADMIN, wish_id=page["wish"], reason="abuse", ip=None
        )
        await session.commit()
    async with bound_session_factory(db)() as session:
        await share_page_wishes.set_hidden(
            session,
            shop_id=page["shop"],
            customer_id=page["customer"],
            page_id=page["id"],
            wish_id=page["wish"],
            hidden=False,
        )
        await session.commit()
        shown = await share_page_wishes.visible_wishes(session, page_id=page["id"])
    assert shown == [], shown
    async with TestClient(TestServer(app_for(db))) as client:
        assert "Baxtli" not in await (await client.get(f"/p/{page['token']}")).text()
    (entry,) = (
        await db.execute(text("SELECT action, target_id, reason FROM admin_audit_log"))
    ).all()
    assert tuple(entry) == ("wish_hide", page["wish"], "abuse")
