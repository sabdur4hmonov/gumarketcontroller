"""CP23 addendum, part 2: "📋 Mening e'lonlarim" -- edit or delete what is posted.

* a price/count/description edit changes the channel caption
  (editMessageCaption) and the catalogue through the SAME path as an edited
  channel post: the product's price and name follow;
* a template switch replaces the photo and caption (editMessageMedia) and
  the product's file id follows;
* a delete removes every message of the post and deactivates its product;
* only the shop's owners and staff, only its own published posts: crafted
  callbacks for another shop's post, or by a customer, change nothing.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from aiogram import Bot
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import (
    AnswerCallbackQuery,
    DeleteMessage,
    EditMessageCaption,
    EditMessageMedia,
    SendMediaGroup,
    SendPhoto,
)
from aiogram.types import Chat, Message
from PIL import Image
from sqlalchemy import select
from tests.bot_harness import (
    TEST_TOKEN,
    RecordingSession,
    bound_session_factory,
    callback_update,
    photo_sizes,
    text_update,
)

from gulbot.announcements.extraction import Fields
from gulbot.announcements.flower_templates import caption
from gulbot.bot.callbacks import PostCB
from gulbot.bot.factory import build_dispatcher
from gulbot.i18n import t
from gulbot.models.announcement import AnnouncementDraft
from gulbot.models.product import Product
from gulbot.models.shop import DEFAULT_WORKING_HOURS, Shop
from gulbot.models.staff import ShopStaff
from gulbot.services import announcements as service
from gulbot.services import published_posts as posts

OWNER, OTHER, CLERK, CUSTOMER = 928001, 928002, 928003, 928004
CHANNEL_A, CHANNEL_B = -100928001, -100928002


class Channel(RecordingSession):
    """A channel that answers sends and edits as Telegram does."""

    def __init__(self) -> None:
        super().__init__()
        self.next_id = 300

    def _message(self, chat_id: int, message_id: int, caption: str | None, photo: str) -> Message:
        return Message(
            message_id=message_id,
            date=datetime.now(UTC),
            chat=Chat(id=chat_id, type="channel" if chat_id < 0 else "private"),
            photo=photo_sizes(photo),
            caption=caption,
        )

    async def make_request(self, bot, method, timeout=None):  # noqa: ASYNC109 aiogram contract
        from html import unescape

        def shown(text: str | None) -> str | None:
            return unescape(text.replace("<b>", "").replace("</b>", "")) if text else text

        if isinstance(method, SendPhoto):
            self.calls.append(method)
            self.next_id += 1
            return self._message(int(method.chat_id), self.next_id, shown(method.caption), "sent")
        if isinstance(method, SendMediaGroup):
            self.calls.append(method)
            out = []
            for i, item in enumerate(method.media):
                self.next_id += 1
                message = self._message(
                    int(method.chat_id), self.next_id, shown(item.caption), f"a{i}"
                )
                out.append(message.model_copy(update={"media_group_id": "album-1"}))
            return out
        if isinstance(method, EditMessageCaption):
            self.calls.append(method)
            return self._message(
                int(method.chat_id), method.message_id, shown(method.caption), "sent"
            )
        if isinstance(method, EditMessageMedia):
            self.calls.append(method)
            return self._message(
                int(method.chat_id), method.message_id, shown(method.media.caption), "replaced"
            )
        if isinstance(method, DeleteMessage):
            self.calls.append(method)
            return True
        return await super().make_request(bot, method, timeout)


def jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (900, 1200), "#c36481").save(out, format="JPEG")
    return out.getvalue()


@pytest_asyncio.fixture
async def world(db, monkeypatch):
    factory = bound_session_factory(db)
    async with factory() as session:
        a = Shop(
            name="A",
            channel_id=CHANNEL_A,
            owner_telegram_ids=[OWNER],
            working_hours=DEFAULT_WORKING_HOURS,
        )
        b = Shop(
            name="B",
            channel_id=CHANNEL_B,
            owner_telegram_ids=[OTHER, OWNER],
            working_hours=DEFAULT_WORKING_HOURS,
        )
        session.add_all([a, b])
        await session.flush()
        session.add(ShopStaff(shop_id=a.id, telegram_id=CLERK, added_by=OWNER))
        await session.commit()
        ids = a.id, b.id
    channel = Channel()
    bot = Bot(token=TEST_TOKEN, session=channel)
    photo = jpeg()

    async def download(file_id, *, destination, timeout=30):  # noqa: ASYNC109 aiogram contract
        destination.write(photo)

    monkeypatch.setattr(bot, "download", download)
    dp = build_dispatcher(session_factory=factory, shop_id=ids[0], storage=MemoryStorage())
    yield factory, ids, bot, channel, dp
    await bot.session.close()


async def published(session, bot, shop: int, *, photos: int = 1) -> AnnouncementDraft:
    """Through the REAL publish service, so the catalogue row exists."""
    draft = await service.new_draft(session, shop_id=shop, actor=OWNER)
    draft.photos = [f"photo-{i}" for i in range(photos)]
    draft.fields = Fields(flowers=["atirgul"], count=51, price=450_000, colour="qizil").data()
    draft.status, draft.template = "preview", "atirgul.classic"
    draft.preview_media = [f"m{i}" for i in range(photos)]
    shop_name = await session.scalar(select(Shop.name).where(Shop.id == shop))
    draft.preview_caption = caption(
        Fields.from_data(draft.fields), template="atirgul.classic", shop_name=shop_name
    )
    await session.flush()
    await service.publish(
        session, bot=bot, shop_id=shop, actor=OWNER, draft_id=draft.id, revision=draft.revision
    )
    await session.commit()
    return draft


async def product_of(session, draft) -> Product:
    first = draft.receipts[0]
    query = select(Product).where(Product.shop_id == draft.shop_id)
    if first["media_group_id"]:
        query = query.where(Product.media_group_id == first["media_group_id"])
    else:
        query = query.where(Product.channel_message_id == first["message_id"])
    return await session.scalar(query.execution_options(populate_existing=True))


# --- the services ------------------------------------------------------------------


@pytest.mark.parametrize("photos", [1, 3])
async def test_a_price_edit_reaches_the_channel_and_the_catalogue(world, photos):
    factory, (a, _), bot, channel, _ = world
    async with factory() as session:
        draft = await published(session, bot, a, photos=photos)
        assert (await product_of(session, draft)).price_uzs == 450_000
        await posts.edit_field(
            session, bot, shop_id=a, actor=OWNER, draft_id=draft.id, field="price", value="520 ming"
        )
        await session.commit()
        [edit] = [c for c in channel.calls if isinstance(c, EditMessageCaption)]
        assert (edit.chat_id, edit.message_id) == (CHANNEL_A, draft.receipts[0]["message_id"])
        assert "Narxi: 520 000 so'm" in edit.caption
        product = await product_of(session, draft)
        assert product.price_uzs == 520_000 and product.active


async def test_a_count_edit_renames_the_product(world):
    factory, (a, _), bot, *_ = world
    async with factory() as session:
        draft = await published(session, bot, a)
        await posts.edit_field(
            session, bot, shop_id=a, actor=CLERK, draft_id=draft.id, field="count", value="101"
        )
        assert (await product_of(session, draft)).name == "Atirgul guldastasi — 101 dona"


async def test_a_template_switch_replaces_photo_caption_and_file_id(world):
    factory, (a, _), bot, channel, _ = world
    async with factory() as session:
        draft = await published(session, bot, a)
        await posts.switch_template(
            session,
            bot,
            shop_id=a,
            actor=OWNER,
            draft_id=draft.id,
            template="atirgul.premium",
            image=jpeg(),
        )
        edits = [c for c in channel.calls if isinstance(c, EditMessageMedia)]
        assert len(edits) == 1
        edit = edits[0]
        assert "✦ Nafis tanlov" in edit.media.caption
        product = await product_of(session, draft)
        assert product.telegram_file_id == "replaced"  # the LARGEST size of the new photo
        row = await session.get(AnnouncementDraft, draft.id)
        assert row.template == "atirgul.premium"


@pytest.mark.parametrize("photos", [1, 3])
async def test_a_delete_removes_every_message_and_deactivates_the_product(world, photos):
    factory, (a, _), bot, channel, _ = world
    async with factory() as session:
        draft = await published(session, bot, a, photos=photos)
        await posts.delete_post(session, bot, shop_id=a, actor=OWNER, draft_id=draft.id)
        await session.commit()
        deleted = [c.message_id for c in channel.calls if isinstance(c, DeleteMessage)]
        assert deleted == [r["message_id"] for r in draft.receipts]
        assert (await product_of(session, draft)).active is False
        assert (await session.get(AnnouncementDraft, draft.id)).status == "deleted"
        assert draft.id not in [d.id for d in await posts.my_posts(session, shop_id=a, actor=OWNER)]


@pytest.mark.parametrize("who", [CUSTOMER, OTHER])
async def test_only_owners_and_staff_touch_a_post(world, who):
    factory, (a, _), bot, channel, _ = world
    async with factory() as session:
        draft = await published(session, bot, a)
        with pytest.raises(service.AnnouncementRefused):
            await posts.edit_field(
                session,
                bot,
                shop_id=a,
                actor=who,
                draft_id=draft.id,
                field="price",
                value="1 000 000",
            )
        with pytest.raises(service.AnnouncementRefused):
            await posts.delete_post(session, bot, shop_id=a, actor=who, draft_id=draft.id)
    assert not any(isinstance(c, EditMessageCaption | DeleteMessage) for c in channel.calls)


async def test_another_shops_post_is_not_found_from_this_shop(world):
    factory, (a, b), bot, channel, _ = world
    async with factory() as session:
        theirs = await published(session, bot, b)
        with pytest.raises(service.AnnouncementRefused):
            await posts.edit_field(
                session,
                bot,
                shop_id=a,
                actor=OWNER,
                draft_id=theirs.id,
                field="price",
                value="1 000 000",
            )
        assert (await product_of(session, theirs)).price_uzs == 450_000


async def test_a_deleted_post_cannot_be_edited_again(world):
    """It still has its receipts; only its status says it is gone."""
    factory, (a, _), bot, channel, _ = world
    async with factory() as session:
        draft = await published(session, bot, a)
        await posts.delete_post(session, bot, shop_id=a, actor=OWNER, draft_id=draft.id)
        with pytest.raises(service.AnnouncementRefused):
            await posts.edit_field(
                session,
                bot,
                shop_id=a,
                actor=OWNER,
                draft_id=draft.id,
                field="price",
                value="1 000 000",
            )
    assert not any(isinstance(c, EditMessageCaption) for c in channel.calls)


async def test_an_unpublished_draft_is_not_a_post(world):
    factory, (a, _), bot, *_ = world
    async with factory() as session:
        draft = await service.new_draft(session, shop_id=a, actor=OWNER)
        with pytest.raises(service.AnnouncementRefused):
            await posts.post_for(session, shop_id=a, actor=OWNER, draft_id=draft.id)


@pytest.mark.parametrize(("field", "value"), [("price", "5"), ("count", "0"), ("colour", "oq")])
async def test_bad_edits_are_refused_before_telegram(world, field, value):
    factory, (a, _), bot, channel, _ = world
    async with factory() as session:
        draft = await published(session, bot, a)
        with pytest.raises(service.AnnouncementRefused):
            await posts.edit_field(
                session, bot, shop_id=a, actor=OWNER, draft_id=draft.id, field=field, value=value
            )
    assert not any(isinstance(c, EditMessageCaption) for c in channel.calls)


# --- through the bot ----------------------------------------------------------------


async def tap(dp, bot, draft_id, action, *, by=OWNER, value=""):
    data = PostCB(action=action, draft=draft_id, value=value).pack()
    await dp.feed_update(bot, callback_update(data, user_id=by))


async def test_the_menu_lists_and_a_typed_price_edits_the_post(world):
    factory, (a, _), bot, channel, dp = world
    async with factory() as session:
        draft = await published(session, bot, a)
    await dp.feed_update(bot, text_update(t("btn.menu.my_posts", "uz"), user_id=OWNER))
    await tap(dp, bot, draft.id, "field", value="price")
    await dp.feed_update(bot, text_update("600 ming", user_id=OWNER, update_id=9))
    async with factory() as session:
        assert (await product_of(session, draft)).price_uzs == 600_000


@pytest.mark.parametrize("who", [CUSTOMER, OTHER])
@pytest.mark.parametrize(
    ("action", "value"),
    [("open", ""), ("field", "price"), ("tpl", "atirgul.gift"), ("delok", ""), ("story", "")],
)
async def test_crafted_post_callbacks_are_refused(world, who, action, value):
    factory, (a, _), bot, channel, dp = world
    async with factory() as session:
        draft = await published(session, bot, a)
    await tap(dp, bot, draft.id, action, by=who, value=value)
    answers = [c for c in channel.calls if isinstance(c, AnswerCallbackQuery)]
    assert answers and answers[-1].show_alert is True
    assert not any(
        isinstance(c, EditMessageCaption | EditMessageMedia | DeleteMessage) for c in channel.calls
    )


async def test_another_shops_post_id_is_refused_through_the_bot(world):
    factory, (_, b), bot, channel, dp = world
    async with factory() as session:
        theirs = await published(session, bot, b)  # OWNER owns B too; this is A's bot
    await tap(dp, bot, theirs.id, "delok")
    answers = [c for c in channel.calls if isinstance(c, AnswerCallbackQuery)]
    assert answers and answers[-1].show_alert is True
    assert not any(isinstance(c, DeleteMessage) for c in channel.calls)
