"""A page's photos (CP17): cleaned, bounded, per shop, gone on delete.

The Foto design frames one photo; an invitation keeps a gallery of up to six.
The test photo carries a real EXIF block with a GPS position and a camera
model -- the kind of thing a phone writes into every picture -- and the
assertion is on the stored and the served BYTES: no EXIF, no GPS, no camera.
"""

from __future__ import annotations

import io
from datetime import date, timedelta
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
from tests.bot_harness import bound_session_factory
from tests.share_pages_harness import ShopBot, every_customer_has_the_gift
from tests.test_share_pages_service import invite, make_customer, make_shop, yesno

from gulbot.bot.callbacks import EditFieldCB, PhotoCB
from gulbot.bot.routers import share_page_photo
from gulbot.i18n.catalog import CATALOG
from gulbot.models.share_page import GALLERY_MAX
from gulbot.services import share_page_photos, share_pages
from gulbot.services.share_page_photos import MAX_SIDE, GalleryFull, PhotoRefused, clean_photo
from gulbot.web.app import build_app

pytestmark = pytest.mark.infra


@pytest.fixture(autouse=True)
def _gift(monkeypatch: pytest.MonkeyPatch) -> None:
    """CP18: premium parts need the gift; these tests are about how they work."""
    every_customer_has_the_gift(monkeypatch)


GPS_IFD = 0x8825
MAKE, MODEL = 0x010F, 0x0110


def phone_photo(width: int = 2400, height: int = 1800, orientation: int = 1) -> bytes:
    """A JPEG as a phone writes one: camera make and model, a GPS position."""
    image = Image.new("RGB", (width, height), (200, 120, 140))
    exif = Image.Exif()
    exif[MAKE] = "PhoneMaker"
    exif[MODEL] = "SecretCam 9"
    exif[0x0112] = orientation
    exif[GPS_IFD] = {1: "N", 2: (41.0, 18.0, 0.0), 3: "E", 4: (69.0, 14.0, 0.0)}
    out = io.BytesIO()
    image.save(out, format="JPEG", exif=exif, quality=90)
    return out.getvalue()


def metadata_of(data: bytes) -> dict[str, Any]:
    with Image.open(io.BytesIO(data)) as image:
        return {"exif": dict(image.getexif()), "info": dict(image.info)}


# --- cleaning ------------------------------------------------------------------------------


def test_the_phone_photo_really_carries_gps_before_cleaning() -> None:
    """Guards the guard: the input must contain what we claim to remove."""
    raw = phone_photo()
    assert b"SecretCam 9" in raw
    with Image.open(io.BytesIO(raw)) as image:
        assert GPS_IFD in image.getexif()


def test_cleaning_drops_every_trace_of_metadata() -> None:
    clean = clean_photo(phone_photo())
    assert b"SecretCam" not in clean.data and b"PhoneMaker" not in clean.data
    meta = metadata_of(clean.data)
    assert meta["exif"] == {}
    assert "exif" not in meta["info"] and "icc_profile" not in meta["info"]


def test_cleaning_shrinks_and_keeps_the_picture_upright() -> None:
    clean = clean_photo(phone_photo(2400, 1800))
    assert max(clean.width, clean.height) == MAX_SIDE
    # EXIF orientation 6 (rotate 90 deg): the stored picture is portrait, no tag needed.
    turned = clean_photo(phone_photo(1600, 900, orientation=6))
    assert turned.height > turned.width


@pytest.mark.parametrize("raw", [b"", b"not a picture", b"\xff\xd8\xff" + b"0" * 100])
def test_what_is_not_a_picture_is_refused(raw: bytes) -> None:
    with pytest.raises(PhotoRefused):
        clean_photo(raw)


def test_an_oversized_upload_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(share_page_photos, "MAX_INPUT_BYTES", 1000)
    with pytest.raises(PhotoRefused):
        clean_photo(phone_photo())


def test_a_decompression_bomb_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(share_page_photos, "MAX_PIXELS", 1000)
    with pytest.raises(PhotoRefused):
        clean_photo(phone_photo(100, 100))


# --- storing -------------------------------------------------------------------------------


@pytest.fixture
async def session(db: AsyncConnection) -> AsyncSession:
    return bound_session_factory(db)()


def soon() -> date:
    return date.today() + timedelta(days=20)


async def invitation(
    session: AsyncSession, db: AsyncConnection, user: int = 801, template: str = "foto"
) -> tuple[Any, int, int]:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, user)
    page = await share_pages.create_page(
        session,
        shop_id=shop,
        customer_id=customer,
        bot_username="lola_bot",
        draft=invite(template=template, event_date=soon()),
    )
    return page, shop, customer


async def add(session: AsyncSession, page: Any, shop: int, customer: int) -> Any:
    return await share_page_photos.store_photo(
        session, shop_id=shop, customer_id=customer, page_id=page.id, raw=phone_photo(600, 800)
    )


async def count_of(db: AsyncConnection, page_id: int) -> int:
    return int(
        await db.scalar(
            text("SELECT count(*) FROM share_page_photos WHERE page_id = :p"), {"p": page_id}
        )
    )


def app_for(db: AsyncConnection) -> Any:
    return build_app(
        session_factory=bound_session_factory(db),
        notify=lambda _id, _delay: None,
        public_base_url="http://127.0.0.1:8088",
    )


async def test_the_photos_are_stored_clean_and_served_only_through_their_page(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, shop, customer = await invitation(session, db)
    other, other_shop, other_customer = await invitation(session, db, user=802)
    first = await add(session, page, shop, customer)
    second = await add(session, page, shop, customer)
    foreign = await add(session, other, other_shop, other_customer)
    assert b"SecretCam" not in first.data
    await session.commit()
    async with TestClient(TestServer(app_for(db))) as client:
        html = await (await client.get(f"/p/{page.token}")).text()
        # The Foto design frames the first photo; the gallery has the second.
        assert f'<img src="/p/{page.token}/photo/{first.id}.jpg" alt="" width="260"' in html
        assert f'<img src="/p/{page.token}/photo/{second.id}.jpg" alt="" width="600"' in html
        assert f"/photo/{first.id}.jpg" not in html.split('class="gallery-grid"')[1]
        served = await client.get(f"/p/{page.token}/photo/{first.id}.jpg")
        assert served.status == 200 and served.content_type == "image/jpeg"
        assert served.headers["Content-Security-Policy"].startswith("default-src 'none'")
        body = await served.read()
        assert metadata_of(body)["exif"] == {} and b"SecretCam" not in body
        # Another page's photo, asked for through this page's token: nothing.
        assert (await client.get(f"/p/{page.token}/photo/{foreign.id}.jpg")).status == 404
        assert (await client.get("/p/" + "x" * 22 + f"/photo/{first.id}.jpg")).status == 404


async def test_any_design_shows_the_gallery_and_only_foto_frames_one(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, shop, customer = await invitation(session, db, template="bog")
    photo = await add(session, page, shop, customer)
    await session.commit()
    async with TestClient(TestServer(app_for(db))) as client:
        html = await (await client.get(f"/p/{page.token}")).text()
    assert 'class="photo"' not in html
    assert f'<img src="/p/{page.token}/photo/{photo.id}.jpg" alt="" width="600"' in html


async def test_an_invitation_keeps_six_photos_and_then_says_it_is_full(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, shop, customer = await invitation(session, db)
    positions = [(await add(session, page, shop, customer)).position for _ in range(GALLERY_MAX)]
    assert positions == [1, 2, 3, 4, 5, 6]
    try:
        await add(session, page, shop, customer)
    except Exception as error:  # noqa: BLE001 - the service refuses, not the DB CHECK
        assert isinstance(error, GalleryFull), repr(error)
    else:
        raise AssertionError("a seventh photo was taken")
    assert await count_of(db, page.id) == GALLERY_MAX
    assert await share_page_photos.clear_photos(
        session, shop_id=shop, customer_id=customer, page_id=page.id
    )
    assert await count_of(db, page.id) == 0
    assert (await add(session, page, shop, customer)).position == 1


async def test_a_yesno_page_keeps_one_photo_a_new_one_replaces_it(
    db: AsyncConnection, session: AsyncSession
) -> None:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 803)
    page = await share_pages.create_page(
        session, shop_id=shop, customer_id=customer, bot_username="b", draft=yesno(template="foto")
    )
    first = await add(session, page, shop, customer)
    second = await add(session, page, shop, customer)
    assert second.position == 1 and second.id != first.id
    assert await count_of(db, page.id) == 1


async def test_nobody_else_can_add_or_clear_photos(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, shop, customer = await invitation(session, db)
    await add(session, page, shop, customer)
    other_shop = await make_shop(db, "B")
    stranger = await make_customer(db, other_shop, 801)
    neighbour = await make_customer(db, shop, 802)
    # (other shop, the owner's id) is what only the shop filter stops.
    for s, c in ((other_shop, stranger), (shop, neighbour), (other_shop, customer)):
        assert await add(session, page, s, c) is None
        assert not await share_page_photos.clear_photos(
            session, shop_id=s, customer_id=c, page_id=page.id
        )
    assert await count_of(db, page.id) == 1


async def test_deleting_the_page_drops_its_photo_files_and_keeps_the_rows(
    db: AsyncConnection, session: AsyncSession
) -> None:
    """CP18 changed this deliberately: the bytes go, the rows stay (size and
    when) for the counts -- the same "deleting scrubs, it does not drop" rule
    CP16 set for the page itself."""
    page, shop, customer = await invitation(session, db)
    photo = await add(session, page, shop, customer)
    await add(session, page, shop, customer)
    await share_pages.delete_page(session, shop_id=shop, customer_id=customer, page_id=page.id)
    await session.flush()
    assert await count_of(db, page.id) == 2
    left = await db.scalar(
        text("SELECT count(*) FROM share_page_photos WHERE page_id = :p AND data IS NOT NULL"),
        {"p": page.id},
    )
    assert left == 0
    assert await share_page_photos.photo_for_token(session, page.token, photo.id) is None


async def test_an_answered_yesno_page_takes_no_new_photo(
    db: AsyncConnection, session: AsyncSession
) -> None:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 804)
    page = await share_pages.create_page(
        session, shop_id=shop, customer_id=customer, bot_username="b", draft=yesno(template="foto")
    )
    await share_pages.answer_yes(session, page.token)
    assert await add(session, page, shop, customer) is None


@pytest.mark.parametrize(
    ("position", "size", "constraint"),
    [
        (1, 2_000_000, "ck_share_page_photos_size_bound"),
        (7, 1000, "ck_share_page_photos_position_range"),
    ],
)
async def test_the_database_refuses_an_unbounded_photo(
    db: AsyncConnection, session: AsyncSession, position: int, size: int, constraint: str
) -> None:
    page, shop, _ = await invitation(session, db)
    with pytest.raises(Exception, match=constraint):
        async with db.begin_nested():
            await db.execute(
                text(
                    "INSERT INTO share_page_photos "
                    "(shop_id, page_id, position, data, width, height, size_bytes) "
                    "VALUES (:s, :p, :pos, :d, 10, 10, :n)"
                ),
                {"s": shop, "p": page.id, "pos": position, "d": b"x", "n": size},
            )


# --- through the bot ---------------------------------------------------------------------


@pytest.fixture
def telegram_photos(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Telegram's download, replaced: every file id is a phone photo."""
    fetched: list[str] = []

    async def download(_bot: object, file_id: str) -> bytes:
        fetched.append(file_id)
        return phone_photo(600, 800)

    monkeypatch.setattr(share_page_photo, "download_photo", download)
    return fetched


async def bot_page(db: AsyncConnection, bot: ShopBot, user: int, draft: object) -> Any:
    await bot.say(CATALOG["btn.menu.help"]["uz"], user=user)
    customer = await db.scalar(
        text("SELECT id FROM customers WHERE shop_id = :s AND telegram_user_id = :u"),
        {"s": bot.shop_id, "u": user},
    )
    session = bound_session_factory(db)()
    page = await share_pages.create_page(
        session,
        shop_id=bot.shop_id,
        customer_id=int(customer),
        bot_username="lola_bot",
        draft=draft,  # type: ignore[arg-type]
    )
    await session.commit()
    return page


async def test_a_gallery_is_filled_and_cleared_through_the_bot(
    db: AsyncConnection, telegram_photos: list[str]
) -> None:
    bot = ShopBot(db, await make_shop(db, "Lola"), bot_id=730_001, username="lola_bot")
    page = await bot_page(db, bot, 730, invite(template="bog", event_date=soon()))
    await bot.tap(EditFieldCB(page_id=page.id, field="photo").pack(), user=730)
    assert "0/6" in bot.last()
    for n in range(1, 4):
        await bot.photo(f"file-{n}", user=730)
    assert telegram_photos == ["file-1", "file-2", "file-3"]  # the largest size, not the thumb
    assert "3/6" in bot.last() and await count_of(db, page.id) == 3
    await bot.tap(PhotoCB(action="clear").pack(), user=730)
    assert await count_of(db, page.id) == 0
    await bot.photo("file-4", user=730)
    await bot.tap(PhotoCB(action="done").pack(), user=730)
    assert await count_of(db, page.id) == 1
    assert any(f"/p/{page.token}" in body for body in bot.texts())
    # Done means done: a photo now is not taken.
    await bot.photo("file-5", user=730)
    assert await count_of(db, page.id) == 1


async def test_clear_out_of_step_or_on_another_shops_page_changes_nothing(
    db: AsyncConnection, telegram_photos: list[str]
) -> None:
    a = ShopBot(db, await make_shop(db, "A"), bot_id=730_002, username="a_bot")
    b = ShopBot(db, await make_shop(db, "B"), bot_id=730_003, username="b_bot")
    page = await bot_page(db, a, 731, invite(event_date=soon()))
    await a.tap(EditFieldCB(page_id=page.id, field="photo").pack(), user=731)
    await a.photo("file-1", user=731)
    await a.tap(PhotoCB(action="done").pack(), user=731)
    await a.tap(PhotoCB(action="clear").pack(), user=731)  # not in the photo step any more
    # Mid-way through another edit of the same page: still not the photo step.
    await a.tap(EditFieldCB(page_id=page.id, field="title").pack(), user=731)
    await a.tap(PhotoCB(action="clear").pack(), user=731)
    await b.say(CATALOG["btn.menu.help"]["uz"], user=731)
    await b.tap(EditFieldCB(page_id=page.id, field="photo").pack(), user=731)
    assert b.last() == CATALOG["pages.gone"]["uz"]
    await b.tap(PhotoCB(action="clear").pack(), user=731)
    await b.photo("file-2", user=731)
    assert await count_of(db, page.id) == 1
