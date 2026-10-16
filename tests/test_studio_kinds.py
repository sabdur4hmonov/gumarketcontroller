"""CP27.2: Ha/Yo'q and Uzrnoma in the studio, photos and music (premium).

- The same form makes all three kinds through share_pages.create_page; the
  rules are checked_draft's, shared with the bot (music included).
- Music is one of our own tracks and premium: refused without the CP18 gift,
  and nothing is created; with it, the page carries the track.
- A photo goes through share_page_photos.store_photo: premium, re-encoded
  without EXIF/GPS, at most six on an invitation, one on a Ha/Yo'q page. Its
  size is checked from Content-Length BEFORE the body is read, and its CSRF
  token is the session's (query string, since the gate cannot read multipart).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.test_share_page_photos import metadata_of, phone_photo
from tests.test_studio_web import app_for, form, log_in, world  # noqa: F401  (fixture)

from gulbot.config import TASHKENT
from gulbot.models.share_page import GALLERY_MAX
from gulbot.services import share_page_photos, share_pages
from gulbot.services.share_pages import ApologyDraft, InvalidDraft, YesNoDraft
from gulbot.web import studio as studio_web

pytestmark = pytest.mark.infra

SOON = (datetime.now(UTC).astimezone(TASHKENT) + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M")
LATER = (datetime.now(UTC).astimezone(TASHKENT) + timedelta(days=4)).strftime("%Y-%m-%dT%H:%M")


def yesno_form(csrf: str, **overrides: str) -> dict[str, str]:
    data = {
        "csrf": csrf,
        "kind": "yesno",
        "lang": "uz",
        "template": "romantik",
        "question_preset": "marry",
        "question": "",
        "notify": "1",
        "action": "create",
    }
    data.update(overrides)
    return data


def apology_form(csrf: str, **overrides: str) -> dict[str, str]:
    data = {
        "csrf": csrf,
        "kind": "apology",
        "lang": "ru",
        "template": "konvert",
        "letter": "Прости меня, пожалуйста.",
        "notify": "1",
        "action": "create",
    }
    data.update(overrides)
    return data


async def gift(db: AsyncConnection, shop: int, customer: int) -> None:
    order = await db.scalar(
        text(
            "INSERT INTO orders (shop_id, customer_id, product_name_snapshot, price_uzs_snapshot, "
            " telegram_file_id_snapshot, delivery_date, delivery_hour, delivery_location_text, "
            " landmark, status, submit_token) VALUES (:s, :c, 'Atirgul', 1, 'f', now()::date, "
            " '14:00', 'x', 'y', 'confirmed', :t) RETURNING id"
        ),
        {"s": shop, "c": customer, "t": f"gift-{customer}"},
    )
    await db.execute(
        text("INSERT INTO premium_unlocks (shop_id, customer_id, order_id) VALUES (:s, :c, :o)"),
        {"s": shop, "c": customer, "o": order},
    )


async def page_row(db: AsyncConnection) -> Any:
    return (await db.execute(text("SELECT * FROM share_pages ORDER BY id DESC LIMIT 1"))).one()


# --- the kinds ----------------------------------------------------------------------


async def test_the_tabs_switch_the_form(world: dict[str, Any]) -> None:  # noqa: F811
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        await log_in(client, db, world["a"], world["ca"])
        yesno = await (await client.get("/studio?kind=yesno")).text()
        apology = await (await client.get("/studio?kind=apology")).text()
        odd = await (await client.get("/studio?kind=<x>")).text()
    assert 'name="question_preset"' in yesno and 'name="venue_name_1"' not in yesno
    assert 'name="letter"' in apology and 'name="question_preset"' not in apology
    assert 'name="venue_name_1"' in odd and "<x>" not in odd


async def test_a_yesno_page_with_its_date_plan(world: dict[str, Any]) -> None:  # noqa: F811
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        data = yesno_form(csrf, place_1="Bog‘", place_2="Kafe", slot_1=SOON, slot_2=LATER)
        made = await client.post("/studio/create", data=data, allow_redirects=False)
        assert made.status == 303, await made.text()
    row = await page_row(db)
    assert (row.kind, row.question_preset, row.notify_creator) == ("yesno", "marry", True)
    assert row.question == "Menga turmushga chiqasanmi?"
    options = list(
        await db.scalars(
            text("SELECT kind FROM share_page_options WHERE page_id = :p ORDER BY kind"),
            {"p": row.id},
        )
    )
    assert options == ["place", "place", "slot", "slot"]


async def test_a_custom_question_and_its_mistakes(world: dict[str, Any]) -> None:  # noqa: F811
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        empty = await client.post("/studio/create", data=yesno_form(csrf, question_preset="custom"))
        assert empty.status == 422 and "Savolingizni yozing." in await empty.text()
        half_plan = await client.post("/studio/create", data=yesno_form(csrf, place_1="Bog‘"))
        assert (
            half_plan.status == 422 and "kamida bitta joy va bitta vaqt" in await half_plan.text()
        )
        past = await client.post(
            "/studio/create",
            data=yesno_form(csrf, place_1="Bog‘", slot_1="2020-01-01T10:00"),
        )
        assert past.status == 422
        made = await client.post(
            "/studio/create",
            data=yesno_form(csrf, question_preset="custom", question="Choyga borasanmi?"),
            allow_redirects=False,
        )
        assert made.status == 303
    row = await page_row(db)
    assert (row.question_preset, row.question) == ("custom", "Choyga borasanmi?")


async def test_an_apology_page(world: dict[str, Any]) -> None:  # noqa: F811
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        empty = await client.post("/studio/create", data=apology_form(csrf, letter="   "))
        assert empty.status == 422 and "Maktubingizni yozing." in await empty.text()
        made = await client.post("/studio/create", data=apology_form(csrf), allow_redirects=False)
        assert made.status == 303
        done = await (await client.get(made.headers["Location"])).text()
    row = await page_row(db)
    assert (row.kind, row.lang, row.message) == ("apology", "ru", "Прости меня, пожалуйста.")
    assert "Uzrnoma tayyor" in done


async def test_previews_work_for_every_kind(world: dict[str, Any]) -> None:  # noqa: F811
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        for data, needle in (
            (yesno_form(csrf, place_1="Bog‘", slot_1=SOON), "Menga turmushga chiqasanmi?"),
            (yesno_form(csrf, question_preset="custom"), "Menga turmushga chiqasanmi?"),
            (apology_form(csrf), "Прости меня"),
            (apology_form(csrf, letter=""), "простишь"),
        ):
            response = await client.post("/studio/preview", data=data)
            assert response.status == 200, data
            assert needle in await response.text()
    assert await db.scalar(text("SELECT count(*) FROM share_pages")) == 0


# --- music ----------------------------------------------------------------------------


def test_the_shared_rules_refuse_a_track_that_is_not_ours() -> None:
    draft = ApologyDraft(template="konvert", lang="uz", text="x", notify_creator=True, music="x")
    with pytest.raises(InvalidDraft):
        import asyncio

        asyncio.run(
            share_pages.checked_draft(
                None,  # type: ignore[arg-type]  # refused before any query
                shop_id=1,
                customer_id=1,
                bot_username=None,
                draft=draft,
                now=datetime.now(UTC),
            )
        )


async def test_music_is_premium_and_nothing_is_made_without_the_gift(world: dict[str, Any]) -> None:  # noqa: F811
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        screen = await (await client.get("/studio?kind=yesno")).text()
        assert re.search(r'value="bahor"[^>]*disabled', screen)
        refused = await client.post("/studio/create", data=yesno_form(csrf, music="bahor"))
        assert refused.status == 422
        odd = await client.post("/studio/create", data=yesno_form(csrf, music="<x>"))
        assert odd.status == 422 and "<x>" not in await odd.text()
        assert await db.scalar(text("SELECT count(*) FROM share_pages")) == 0
        await gift(db, world["a"], world["ca"])
        made = await client.post(
            "/studio/create", data=yesno_form(csrf, music="bahor"), allow_redirects=False
        )
        assert made.status == 303
    assert (await page_row(db)).music == "bahor"


async def test_music_on_an_invitation_with_the_gift(world: dict[str, Any]) -> None:  # noqa: F811
    db = world["db"]
    await gift(db, world["a"], world["ca"])
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        made = await client.post(
            "/studio/create", data=form(csrf, music="tantana"), allow_redirects=False
        )
        assert made.status == 303
    assert (await page_row(db)).music == "tantana"


# --- photos ----------------------------------------------------------------------------


async def _made(client: TestClient, csrf: str, data: dict[str, str]) -> int:
    made = await client.post("/studio/create", data=data, allow_redirects=False)
    assert made.status == 303, await made.text()
    return int(made.headers["Location"].rsplit("/", 1)[1])


def _upload(raw: bytes, name: str = "photo.jpg") -> FormData:
    data = FormData()
    data.add_field("photo", raw, filename=name, content_type="image/jpeg")
    return data


async def test_a_photo_is_premium(world: dict[str, Any]) -> None:  # noqa: F811
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        page_id = await _made(client, csrf, form(csrf))
        done = await (await client.get(f"/studio/done/{page_id}")).text()
        assert 'enctype="multipart/form-data"' not in done and "🔒" in done
        refused = await client.post(
            f"/studio/page/{page_id}/photo?csrf={csrf}", data=_upload(phone_photo(400, 300))
        )
        assert refused.status == 422
    assert await db.scalar(text("SELECT count(*) FROM share_page_photos")) == 0


async def test_a_photo_is_cleaned_and_the_gallery_has_a_limit(world: dict[str, Any]) -> None:  # noqa: F811
    db = world["db"]
    await gift(db, world["a"], world["ca"])
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        page_id = await _made(client, csrf, form(csrf))
        for _ in range(GALLERY_MAX):
            sent = await client.post(
                f"/studio/page/{page_id}/photo?csrf={csrf}",
                data=_upload(phone_photo(400, 300)),
                allow_redirects=False,
            )
            assert sent.status == 303, await sent.text()
        full = await client.post(
            f"/studio/page/{page_id}/photo?csrf={csrf}", data=_upload(phone_photo(400, 300))
        )
        assert full.status == 422 and "chegarasiga" in await full.text()
        junk = await client.post(
            f"/studio/page/{page_id}/photos/clear", data={"csrf": csrf}, allow_redirects=False
        )
        assert junk.status == 303
        not_image = await client.post(
            f"/studio/page/{page_id}/photo?csrf={csrf}", data=_upload(b"not a picture")
        )
        assert not_image.status == 422
        sent = await client.post(
            f"/studio/page/{page_id}/photo?csrf={csrf}",
            data=_upload(phone_photo(2400, 1800)),
            allow_redirects=False,
        )
        assert sent.status == 303
    stored = await db.scalar(
        text("SELECT data FROM share_page_photos WHERE page_id = :p"), {"p": page_id}
    )
    meta = metadata_of(bytes(stored))
    assert meta["exif"] == {} and "exif" not in meta["info"]


async def test_a_yesno_page_keeps_one_photo(world: dict[str, Any]) -> None:  # noqa: F811
    db = world["db"]
    await gift(db, world["a"], world["ca"])
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        page_id = await _made(client, csrf, yesno_form(csrf))
        for _ in range(2):
            sent = await client.post(
                f"/studio/page/{page_id}/photo?csrf={csrf}",
                data=_upload(phone_photo(400, 300)),
                allow_redirects=False,
            )
            assert sent.status == 303
    assert (
        await db.scalar(
            text("SELECT count(*) FROM share_page_photos WHERE page_id = :p"), {"p": page_id}
        )
        == 1
    )


async def test_an_oversize_upload_is_refused_before_it_is_read(
    world: dict[str, Any],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = world["db"]
    await gift(db, world["a"], world["ca"])
    reads: list[int] = []
    original = share_page_photos.store_photo

    async def counting(*args: Any, **kwargs: Any) -> Any:
        reads.append(len(kwargs["raw"]))
        return await original(*args, **kwargs)

    monkeypatch.setattr(share_page_photos, "store_photo", counting)
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        page_id = await _made(client, csrf, form(csrf))
        url = f"/studio/page/{page_id}/photo?csrf={csrf}"
        # A declared body over the cap: refused from Content-Length, unread.
        huge = b"\xff\xd8" + b"0" * studio_web.UPLOAD_MAX_BYTES
        assert (await client.post(url, data=_upload(huge))).status == 413
        # Just over the photo's own cap: the read stops at the cap.
        just_over = b"\xff\xd8" + b"0" * share_page_photos.MAX_INPUT_BYTES
        response = await client.post(url, data=_upload(just_over))
        assert response.status == 422 and "juda katta" in await response.text()
    assert reads == [], "an oversize body reached the photo service"


async def test_an_upload_needs_the_sessions_token_and_its_own_page(world: dict[str, Any]) -> None:  # noqa: F811
    db = world["db"]
    await gift(db, world["a"], world["ca"])
    await gift(db, world["b"], world["cb"])
    async with TestClient(TestServer(app_for(db))) as client:
        csrf_b = await log_in(client, db, world["b"], world["cb"])
        theirs = await _made(client, csrf_b, form(csrf_b))
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world["a"], world["ca"])
        mine = await _made(client, csrf, form(csrf))
        for url in (f"/studio/page/{mine}/photo", f"/studio/page/{mine}/photo?csrf=nope"):
            response = await client.post(url, data=_upload(phone_photo(400, 300)))
            assert response.status == 403, url
        response = await client.post(
            f"/studio/page/{theirs}/photo?csrf={csrf}", data=_upload(phone_photo(400, 300))
        )
        assert response.status == 404
        cleared = await client.post(
            f"/studio/page/{theirs}/photos/clear", data={"csrf": csrf}, allow_redirects=False
        )
        assert cleared.status == 404
    assert await db.scalar(text("SELECT count(*) FROM share_page_photos")) == 0


def test_yesno_and_apology_drafts_carry_music() -> None:
    assert YesNoDraft.__dataclass_fields__["music"].default is None
    assert ApologyDraft.__dataclass_fields__["music"].default is None
