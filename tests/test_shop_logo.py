"""The shop's own logo on every photo (CP23 addendum, the owner's request).

* an owner sends it to the shop's bot (/logo); it is stored normalised --
  RGBA PNG, transparent borders trimmed, at most 512 px -- for THAT shop;
* only the shop's owners set or remove it; staff, customers, other shops'
  owners cannot;
* every photo of an announcement carries it (the template's first photo in
  its layout's free corner, every other photo too), and every story; the
  owner can switch it off per announcement;
* the geometry -- never over text, stories inside Instagram's visible zone --
  is proven over ALL 150 posts and 150 stories in the template tests.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from aiogram import Bot
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import AnswerCallbackQuery, SendMediaGroup, SendMessage, SendPhoto
from aiogram.types import BufferedInputFile, Chat, Message, Update, User
from PIL import Image
from sqlalchemy.exc import IntegrityError
from tests.bot_harness import (
    TEST_TOKEN,
    RecordingSession,
    bound_session_factory,
    callback_update,
    photo_sizes,
    text_update,
)

from gulbot.announcements.designs import render_post, stamp_logo
from gulbot.announcements.extraction import Fields
from gulbot.bot.callbacks import AnnouncementCB, LogoCB
from gulbot.bot.factory import build_dispatcher
from gulbot.models.announcement import AnnouncementDraft, ShopLogo
from gulbot.models.shop import DEFAULT_WORKING_HOURS, Shop
from gulbot.models.staff import ShopStaff
from gulbot.services import announcements as service
from gulbot.services import shop_logo

OWNER, OTHER, CLERK, CUSTOMER = 929001, 929002, 929003, 929004


def png(size=(600, 300), ground=(0, 0, 0, 0), mark=True) -> bytes:
    image = Image.new("RGBA", size, ground)
    if mark:
        image.paste(Image.new("RGBA", (200, 100), (122, 20, 36, 255)), (100, 50))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def jpeg(size=(900, 1200), colour="#c36481") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, format="JPEG")
    return out.getvalue()


# --- normalising --------------------------------------------------------------------


def test_a_logo_is_trimmed_to_its_mark_and_kept_transparent() -> None:
    data, width, height = shop_logo.normalise(png())
    assert (width, height) == (200, 100)  # the transparent border is gone
    with Image.open(io.BytesIO(data)) as image:
        assert image.format == "PNG" and image.mode == "RGBA"


def test_a_big_logo_is_scaled_to_512() -> None:
    _, width, height = shop_logo.normalise(png(size=(3000, 3000), ground=(255, 255, 255, 255)))
    assert max(width, height) == 512


@pytest.mark.parametrize(
    "data",
    [b"not an image", png(mark=False), png(size=(10, 10), ground=(1, 2, 3, 255)), b""],
)
def test_junk_is_refused(data: bytes) -> None:
    with pytest.raises(shop_logo.LogoRefused):
        shop_logo.normalise(data)


# --- the renderers ------------------------------------------------------------------


def test_every_photo_gets_the_logo_and_none_without_it() -> None:
    logo = Image.open(io.BytesIO(shop_logo.normalise(png())[0])).convert("RGBA")
    plain = render_post(jpeg(), template="lola.classic", price=450_000, colour="", shop_name="A")
    marked = render_post(
        jpeg(), template="lola.classic", price=450_000, colour="", shop_name="A", logo=logo
    )
    assert plain.logo is None and marked.logo is not None
    assert plain.jpeg != marked.jpeg
    stamped = stamp_logo(jpeg(), logo)
    with Image.open(io.BytesIO(stamped)) as image:
        assert image.size == (900, 1200)
    assert stamped != jpeg()


# --- the shop's owners only ----------------------------------------------------------


@pytest_asyncio.fixture
async def world(db, monkeypatch):
    factory = bound_session_factory(db)
    async with factory() as session:
        a = Shop(
            name="A",
            channel_id=-100929001,
            owner_telegram_ids=[OWNER],
            working_hours=DEFAULT_WORKING_HOURS,
        )
        b = Shop(
            name="B",
            channel_id=-100929002,
            owner_telegram_ids=[OTHER],
            working_hours=DEFAULT_WORKING_HOURS,
        )
        session.add_all([a, b])
        await session.flush()
        session.add(ShopStaff(shop_id=a.id, telegram_id=CLERK, added_by=OWNER))
        await session.commit()
        ids = a.id, b.id
    recorder = Recorder()
    bot = Bot(token=TEST_TOKEN, session=recorder)
    downloads: dict[str, bytes] = {
        "logo-file": png(),
        "photo-0": jpeg(),
        "photo-1": jpeg(),
        "photo-2": jpeg(),
    }

    async def download(file_id, *, destination, timeout=30):  # noqa: ASYNC109 aiogram contract
        destination.write(downloads.get(file_id, jpeg()))

    monkeypatch.setattr(bot, "download", download)
    dp = build_dispatcher(session_factory=factory, shop_id=ids[0], storage=MemoryStorage())
    yield factory, ids, bot, recorder, dp
    await bot.session.close()


class Recorder(RecordingSession):
    async def make_request(self, bot, method, timeout=None):  # noqa: ASYNC109 aiogram contract
        if isinstance(method, SendPhoto | SendMediaGroup):
            self.calls.append(method)
            items = method.media if isinstance(method, SendMediaGroup) else [method]
            out = [
                Message(
                    message_id=800 + i,
                    date=datetime.now(UTC),
                    chat=Chat(id=method.chat_id, type="private"),
                    photo=photo_sizes(f"shown-{i}"),
                )
                for i, _ in enumerate(items)
            ]
            return out if isinstance(method, SendMediaGroup) else out[0]
        return await super().make_request(bot, method, timeout)


@pytest.mark.parametrize("who", [CLERK, CUSTOMER, OTHER, 0])
async def test_only_an_owner_sets_or_removes_the_logo(world, who):
    factory, (a, _), *_ = world
    async with factory() as session:
        with pytest.raises(shop_logo.LogoRefused):
            await shop_logo.set_logo(session, shop_id=a, actor=who, data=png())
        await shop_logo.set_logo(session, shop_id=a, actor=OWNER, data=png())
        with pytest.raises(shop_logo.LogoRefused):
            await shop_logo.remove_logo(session, shop_id=a, actor=who)
        assert await shop_logo.logo_image(session, a) is not None


async def test_a_logo_is_one_shops_only(world):
    factory, (a, b), *_ = world
    async with factory() as session:
        await shop_logo.set_logo(session, shop_id=a, actor=OWNER, data=png())
        assert await shop_logo.logo_image(session, b) is None


async def test_postgres_refuses_an_oversized_logo_row(world):
    factory, (a, _), *_ = world
    async with factory() as session:
        session.add(ShopLogo(shop_id=a, image=b"x", width=4000, height=10, uploaded_by=OWNER))
        with pytest.raises(IntegrityError, match="shop_logos_dimensions"):
            await session.flush()


# --- through the bot -------------------------------------------------------------------


def document_update(file_id: str, *, user_id: int, update_id: int = 7) -> Update:
    from aiogram.types import Document

    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=datetime.now(UTC),
            chat=Chat(id=user_id, type="private"),
            from_user=User(id=user_id, is_bot=False, first_name="u"),
            document=Document(
                file_id=file_id,
                file_unique_id=file_id + "-u",
                mime_type="image/png",
                file_size=10_000,
            ),
        ),
    )


async def test_the_owner_sends_a_logo_through_the_bot(world):
    factory, (a, _), bot, recorder, dp = world
    await dp.feed_update(bot, text_update("/logo", user_id=OWNER))
    await dp.feed_update(bot, callback_update(LogoCB(action="new").pack(), user_id=OWNER))
    await dp.feed_update(bot, document_update("logo-file", user_id=OWNER))
    async with factory() as session:
        stored = await session.get(ShopLogo, a)
        assert stored is not None and (stored.width, stored.height) == (200, 100)
    sample = [c for c in recorder.calls if isinstance(c, SendPhoto)][-1]
    assert "Logo saqlandi" in sample.caption


@pytest.mark.parametrize("who", [CLERK, CUSTOMER])
async def test_staff_and_customers_cannot_set_it_through_the_bot(world, who):
    factory, (a, _), bot, recorder, dp = world
    await dp.feed_update(bot, callback_update(LogoCB(action="new").pack(), user_id=who))
    await dp.feed_update(bot, document_update("logo-file", user_id=who))
    answers = [c for c in recorder.calls if isinstance(c, AnswerCallbackQuery)]
    assert answers and answers[-1].show_alert is True
    async with factory() as session:
        assert await session.get(ShopLogo, a) is None


async def confirmed_album(session, shop) -> AnnouncementDraft:
    draft = await service.new_draft(session, shop_id=shop, actor=OWNER)
    draft.photos = ["photo-0", "photo-1", "photo-2"]
    draft.fields = Fields(flowers=["atirgul"], count=51, price=450_000, colour="qizil").data()
    draft.status = "review"
    service.confirm(draft)
    await service.apply_default_template(session, draft)
    await session.flush()
    return draft


async def test_every_photo_of_an_album_carries_the_logo(world):
    factory, (a, _), bot, recorder, dp = world
    async with factory() as session:
        await shop_logo.set_logo(session, shop_id=a, actor=OWNER, data=png())
        draft = await confirmed_album(session, a)
        await session.commit()
    await dp.feed_update(
        bot,
        callback_update(
            AnnouncementCB(action="preview", draft=draft.id, revision=draft.revision).pack(),
            user_id=OWNER,
        ),
    )
    album = [c for c in recorder.calls if isinstance(c, SendMediaGroup)][-1]
    assert all(isinstance(item.media, BufferedInputFile) for item in album.media)


async def test_switched_off_the_photos_go_untouched(world):
    factory, (a, _), bot, recorder, dp = world
    async with factory() as session:
        await shop_logo.set_logo(session, shop_id=a, actor=OWNER, data=png())
        draft = await confirmed_album(session, a)
        await session.commit()
    await dp.feed_update(
        bot,
        callback_update(
            AnnouncementCB(action="logo", draft=draft.id, revision=draft.revision).pack(),
            user_id=OWNER,
        ),
    )
    async with factory() as session:
        draft = await session.get(AnnouncementDraft, draft.id)
        assert draft.logo_on is False
    await dp.feed_update(
        bot,
        callback_update(
            AnnouncementCB(action="preview", draft=draft.id, revision=draft.revision).pack(),
            user_id=OWNER,
        ),
    )
    album = [c for c in recorder.calls if isinstance(c, SendMediaGroup)][-1]
    # Only the template's own first photo is rendered; the rest are the originals.
    assert [isinstance(item.media, str) for item in album.media] == [False, True, True]
    texts = [c.text for c in recorder.calls if isinstance(c, SendMessage)]
    assert any("Logo o'chirildi" in t for t in texts)
