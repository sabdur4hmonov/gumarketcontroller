"""CP27.3: "Mening taklifnomalarim" -- list, manage, edit, delete, counts.

- The list and every page screen show THIS creator's own live pages in THIS
  shop; a page id of another customer or another shop is 404 on every route,
  and nothing about it changes.
- Counts only: views, Ha answered, RSVP coming / guests / not coming. A guest's
  name never reaches a studio screen.
- An edit keeps the same row and the same public link, and goes through the
  bot's own services (update_page, set_plan, set_venues): an answered Ha/Yo'q
  page is locked, a premium design needs the gift.
- Delete asks once, then scrubs exactly as the bot's delete does.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.test_studio_kinds import gift, yesno_form
from tests.test_studio_web import app_for, form, log_in, world  # noqa: F401  (fixture)

from gulbot.services import share_pages
from gulbot.services.share_pages import VenueDraft

pytestmark = pytest.mark.infra

GUEST = "Mehmonjon-maxfiy"


async def _made(client: TestClient, data: dict[str, str]) -> int:
    made = await client.post("/studio/create", data=data, allow_redirects=False)
    assert made.status == 303, await made.text()
    return int(made.headers["Location"].rsplit("/", 1)[1])


async def _token(db: AsyncConnection, page_id: int) -> str:
    return str(await db.scalar(text("SELECT token FROM share_pages WHERE id = :p"), {"p": page_id}))


def edit_form(csrf: str, **overrides: str) -> dict[str, str]:
    return form(csrf, action="save", **overrides)


async def test_the_list_shows_only_my_live_pages(world: dict[str, Any]) -> None:  # noqa: F811
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        csrf_b = await log_in(client, db, world["b"], world["cb"])
        theirs = await _made(client, form(csrf_b, name_1="Begona"))
    other_here = int(
        await db.scalar(
            text(
                "INSERT INTO customers (shop_id, telegram_user_id, phone) "
                "VALUES (:s, 779001, '+998900000001') RETURNING id"
            ),
            {"s": world["a"]},
        )
    )
    async with TestClient(TestServer(app_for(db))) as client:
        csrf_o = await log_in(client, db, world["a"], other_here)
        neighbour = await _made(client, form(csrf_o, name_1="Qoshni"))
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        mine = await _made(client, form(csrf, name_1="Zarina"))
        gone = await _made(client, yesno_form(csrf))
        await client.post(f"/studio/page/{gone}/delete", data={"csrf": csrf, "confirm": "1"})
        listing = await (await client.get("/studio/pages")).text()
    assert f'href="/studio/page/{mine}"' in listing and "Zarina" in listing
    for absent in (theirs, neighbour, gone):
        assert f'href="/studio/page/{absent}"' not in listing
    assert "Begona" not in listing and "Qoshni" not in listing


async def test_a_page_shows_counts_only(world: dict[str, Any]) -> None:  # noqa: F811
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        page_id = await _made(client, form(csrf))
        await db.execute(
            text("UPDATE share_pages SET view_count = 7 WHERE id = :p"), {"p": page_id}
        )
        for n, (answer, guests, name) in enumerate(
            (("yes", 2, GUEST), ("yes", 3, None), ("no", 0, GUEST))
        ):
            await db.execute(
                text(
                    "INSERT INTO share_page_rsvps (shop_id, page_id, voter_key, answer, "
                    "guests, guest_name) VALUES (:s, :p, :k, :a, :g, :n)"
                ),
                {"s": world["a"], "p": page_id, "k": f"v{n}", "a": answer, "g": guests, "n": name},
            )
        screen = await (await client.get(f"/studio/page/{page_id}")).text()
    assert re.search(r'data-count="views">\s*7<', screen)
    assert re.search(r'data-count="coming">\s*2<', screen)
    assert re.search(r'data-count="guests">\s*5<', screen)
    assert re.search(r'data-count="not_coming">\s*1<', screen)
    assert GUEST not in screen


async def test_an_edit_keeps_the_same_link_and_replaces_the_places(world: dict[str, Any]) -> None:  # noqa: F811
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        page_id = await _made(client, form(csrf))
        before = await _token(db, page_id)
        prefilled = await (await client.get(f"/studio/page/{page_id}/edit")).text()
        assert 'value="Aziz"' in prefilled and 'value="Kelin tomon"' in prefilled
        assert f'action="/studio/page/{page_id}/edit"' in prefilled
        saved = await client.post(
            f"/studio/page/{page_id}/edit",
            data=edit_form(
                csrf,
                name_1="Sardor",
                template="tungi",
                venue_count="1",
                venue_kind_1="restoran",
                venue_name_1="Bahor restorani",
                venue_address_1="Yunusobod",
                venue_map_1="https://maps.app.goo.gl/xyz",
            ),
            allow_redirects=False,
        )
        assert saved.status == 303, await saved.text()
    row = (
        await db.execute(
            text("SELECT token, name_1, template, venue FROM share_pages WHERE id = :p"),
            {"p": page_id},
        )
    ).one()
    assert (row.token, row.name_1, row.template) == (before, "Sardor", "tungi")
    assert row.venue == "Bahor restorani, Yunusobod"
    places = list(
        await db.scalars(
            text("SELECT name FROM share_page_venues WHERE page_id = :p"), {"p": page_id}
        )
    )
    assert places == ["Bahor restorani"]


async def test_set_venues_keeps_a_pin_the_new_link_does_not_name(world: dict[str, Any]) -> None:  # noqa: F811
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        page_id = await _made(client, form(csrf))  # place 1's link names 41.311081,69.240562
    from tests.bot_harness import bound_session_factory

    async with bound_session_factory(db)() as session:
        page = await share_pages.set_venues(
            session,
            shop_id=world["a"],
            customer_id=world["ca"],
            page_id=page_id,
            venues=(VenueDraft(kind="uy", name="Uy", map_url="https://maps.app.goo.gl/q"),),
        )
        assert str(page.location_lat) == "41.311081"
        with pytest.raises(share_pages.EditRefused):
            await share_pages.set_venues(
                session, shop_id=world["a"], customer_id=world["ca"], page_id=page_id, venues=()
            )


async def test_an_answered_yesno_page_is_locked(world: dict[str, Any]) -> None:  # noqa: F811
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        page_id = await _made(client, yesno_form(csrf))
        edit = await (await client.get(f"/studio/page/{page_id}/edit")).text()
        assert 'name="question_preset" value="marry" checked' in edit
        changed = await client.post(
            f"/studio/page/{page_id}/edit",
            data=yesno_form(csrf, action="save", question_preset="custom", question="Yangi?"),
            allow_redirects=False,
        )
        assert changed.status == 303
        await db.execute(
            text("UPDATE share_pages SET answered_at = now() WHERE id = :p"), {"p": page_id}
        )
        locked = await client.post(
            f"/studio/page/{page_id}/edit",
            data=yesno_form(csrf, action="save", question_preset="custom", question="Boshqa?"),
        )
        assert locked.status == 422 and "javob berilgan" in (await locked.text()).lower()
    assert (
        await db.scalar(text("SELECT question FROM share_pages WHERE id = :p"), {"p": page_id})
        == "Yangi?"
    )


async def test_an_edit_to_a_premium_design_needs_the_gift(world: dict[str, Any]) -> None:  # noqa: F811
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        page_id = await _made(client, form(csrf))
        refused = await client.post(
            f"/studio/page/{page_id}/edit", data=edit_form(csrf, template="deco")
        )
        assert refused.status == 422
        assert (
            await db.scalar(text("SELECT template FROM share_pages WHERE id = :p"), {"p": page_id})
            == "milliy"
        )
        await gift(db, world["a"], world["ca"])
        done = await client.post(
            f"/studio/page/{page_id}/edit",
            data=edit_form(csrf, template="deco", music="bahor"),
            allow_redirects=False,
        )
        assert done.status == 303
    row = (
        await db.execute(
            text("SELECT template, music FROM share_pages WHERE id = :p"), {"p": page_id}
        )
    ).one()
    assert (row.template, row.music) == ("deco", "bahor")


async def test_the_picker_returns_to_the_edit_form(world: dict[str, Any]) -> None:  # noqa: F811
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        page_id = await _made(client, form(csrf))
        back = await (
            await client.post(
                "/studio/design", data=form(csrf, edit_id=str(page_id), choose="tungi")
            )
        ).text()
    assert f'action="/studio/page/{page_id}/edit"' in back
    assert 'name="template" value="tungi"' in back


async def test_delete_asks_once_then_scrubs(world: dict[str, Any]) -> None:  # noqa: F811
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        page_id = await _made(client, form(csrf))
        token = await _token(db, page_id)
        asked = await client.post(f"/studio/page/{page_id}/delete", data={"csrf": csrf})
        assert asked.status == 200 and 'name="confirm" value="1"' in await asked.text()
        assert (
            await db.scalar(
                text("SELECT deleted_at FROM share_pages WHERE id = :p"), {"p": page_id}
            )
            is None
        )
        deleted = await client.post(
            f"/studio/page/{page_id}/delete",
            data={"csrf": csrf, "confirm": "1"},
            allow_redirects=False,
        )
        assert deleted.status == 303 and deleted.headers["Location"] == "/studio/pages"
        public = await client.get(f"/p/{token}")
        assert public.status == 410
        assert (await client.get(f"/studio/page/{page_id}")).status == 404
    row = (
        await db.execute(
            text("SELECT name_1, venue FROM share_pages WHERE id = :p"), {"p": page_id}
        )
    ).one()
    assert (row.name_1, row.venue) == (None, None)
    assert (
        await db.scalar(
            text("SELECT count(*) FROM share_page_venues WHERE page_id = :p"), {"p": page_id}
        )
        == 0
    )


async def test_another_creators_page_is_404_everywhere(world: dict[str, Any]) -> None:  # noqa: F811
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        csrf_b = await log_in(client, db, world["b"], world["cb"])
        theirs = await _made(client, form(csrf_b, name_1="Begona"))
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        for method, path, data in (
            ("GET", f"/studio/page/{theirs}", None),
            ("GET", f"/studio/page/{theirs}/edit", None),
            ("POST", f"/studio/page/{theirs}/edit", edit_form(csrf, name_1="Buzildi")),
            ("POST", f"/studio/page/{theirs}/delete", {"csrf": csrf, "confirm": "1"}),
        ):
            response = await client.request(method, path, data=data, allow_redirects=False)
            assert response.status == 404, (method, path, response.status)
            assert "Begona" not in await response.text()
    row = (
        await db.execute(
            text("SELECT name_1, deleted_at FROM share_pages WHERE id = :p"), {"p": theirs}
        )
    ).one()
    assert (row.name_1, row.deleted_at) == ("Begona", None)


async def test_no_phone_guest_or_token_on_the_new_screens(world: dict[str, Any]) -> None:  # noqa: F811
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        page_id = await _made(client, form(csrf))
        await db.execute(
            text(
                "INSERT INTO share_page_rsvps (shop_id, page_id, voter_key, answer, guests, "
                "guest_name) VALUES (:s, :p, 'k', 'yes', 1, :n)"
            ),
            {"s": world["a"], "p": page_id, "n": GUEST},
        )
        bodies = [
            await (await client.get(path)).text()
            for path in ("/studio/pages", f"/studio/page/{page_id}", f"/studio/page/{page_id}/edit")
        ]
        bodies.append(
            await (await client.post(f"/studio/page/{page_id}/delete", data={"csrf": csrf})).text()
        )
    everything = "\n".join(bodies)
    for planted in ("+998901110071", "+998902220072", "+998903330073", GUEST):
        assert planted not in everything
