"""Real dispatcher + Postgres: access, draft scope, confirmation, publication."""

import io
from datetime import UTC, datetime
from html import unescape

import pytest
import pytest_asyncio
from aiogram import Bot
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import AnswerCallbackQuery, SendMediaGroup, SendMessage, SendPhoto
from aiogram.types import Chat, Message, Update, User
from PIL import Image
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from tests.bot_harness import (
    TEST_TOKEN,
    RecordingSession,
    bound_session_factory,
    callback_update,
    channel_message,
    photo_sizes,
    text_update,
)

from gulbot.announcements.extraction import Fields
from gulbot.bot.callbacks import AnnouncementCB
from gulbot.bot.factory import build_dispatcher
from gulbot.bot.routers.announcements import exact_preview
from gulbot.i18n import t
from gulbot.models.announcement import AnnouncementDraft, AnnouncementPreference
from gulbot.models.product import HashtagAlias, Product
from gulbot.models.shop import DEFAULT_WORKING_HOURS, Shop
from gulbot.models.staff import ShopStaff
from gulbot.services import announcements as service

OWNER, OTHER, CLERK, CUSTOMER = 922001, 922002, 922003, 922004


class Publisher(RecordingSession):
    fail = False

    async def make_request(self, bot, method, timeout=None):  # noqa: ASYNC109 aiogram contract
        if isinstance(method, SendPhoto | SendMediaGroup):
            self.calls.append(method)
            if self.fail:
                raise TimeoutError("ambiguous response")
            channel = int(method.chat_id) < 0
            items = method.media if isinstance(method, SendMediaGroup) else [method]
            messages = [
                Message(
                    message_id=100 + len(self.calls) * 10 + i,
                    date=datetime.now(UTC),
                    chat=Chat(id=method.chat_id, type="channel" if channel else "private"),
                    photo=photo_sizes(f"returned-{len(self.calls)}-{i}"),
                    caption=unescape(item.caption) if item.caption else None,
                    media_group_id="cp22-album" if len(items) > 1 else None,
                )
                for i, item in enumerate(items)
            ]
            return messages if isinstance(method, SendMediaGroup) else messages[0]
        return await super().make_request(bot, method, timeout)


@pytest_asyncio.fixture
async def world(db):
    factory = bound_session_factory(db)
    async with factory() as session:
        a = Shop(
            name="A",
            channel_id=-100922001,
            owner_telegram_ids=[OWNER],
            working_hours=DEFAULT_WORKING_HOURS,
        )
        b = Shop(
            name="B",
            channel_id=-100922002,
            owner_telegram_ids=[OTHER, OWNER],
            working_hours=DEFAULT_WORKING_HOURS,
        )
        session.add_all([a, b])
        await session.flush()
        session.add(ShopStaff(shop_id=a.id, telegram_id=CLERK, added_by=OWNER))
        await session.commit()
        ids = a.id, b.id
    recorder = Publisher()
    bot = Bot(token=TEST_TOKEN, session=recorder)
    dp = build_dispatcher(session_factory=factory, shop_id=ids[0], storage=MemoryStorage())
    yield factory, ids, bot, recorder, dp
    await bot.session.close()


async def prepared(session, shop, actor=OWNER, photos=1):
    draft = await service.new_draft(session, shop_id=shop, actor=actor)
    draft.photos = [f"photo-{i}" for i in range(photos)]
    draft.fields = Fields(flowers=["atirgul"], count=51, price=450000, colour="qizil").data()
    draft.status = "review"
    await session.flush()
    return draft


async def tap(dp, bot, draft, action, *, by=OWNER, value=""):
    data = AnnouncementCB(
        action=action, draft=draft.id, revision=draft.revision, value=value
    ).pack()
    await dp.feed_update(bot, callback_update(data, user_id=by))


async def refused(operation):
    try:
        await operation
        return False
    except service.AnnouncementRefused:
        return True


@pytest.mark.parametrize(
    "actor,allowed", [(OWNER, True), (CLERK, True), (OTHER, False), (CUSTOMER, False)]
)
async def test_explicit_staff_access_and_menu(world, actor, allowed):
    factory, (a, b), bot, recorder, dp = world
    async with factory() as session:
        assert await service.may_publish(session, shop_id=a, actor=actor) is allowed
        # Shop B has NO staff list: CP19's open empty-list rule MUST NOT leak.
        assert await service.may_publish(session, shop_id=b, actor=actor) is (
            actor in {OWNER, OTHER}
        )
    await dp.feed_update(bot, text_update("/start", user_id=actor))
    # Returning users can reach menu after language picker; entry guard works
    # whether or not they ever saw a menu button.
    await dp.feed_update(bot, text_update(t("btn.language.uz", "uz"), user_id=actor, update_id=2))
    menus = [
        call.reply_markup
        for call in recorder.calls
        if isinstance(call, SendMessage)
        and call.reply_markup
        and hasattr(call.reply_markup, "keyboard")
    ]
    labels = [button.text for menu in menus for row in menu.keyboard for button in row]
    assert (t("btn.menu.announcement", "uz") in labels) is allowed


@pytest.mark.parametrize("actor", [OTHER, CUSTOMER])
@pytest.mark.parametrize(
    "action",
    [
        "edit",
        "confirm",
        "captions",
        "images",
        "caption",
        "image",
        "favourite",
        "preview",
        "publish",
        "review",
        "flower",
        "colour",
        "styles",
    ],
)
async def test_every_crafted_callback_refused(world, actor, action):
    factory, (a, _), bot, recorder, dp = world
    async with factory() as session:
        draft = await prepared(session, a)
        await session.commit()
        draft_id, rev = draft.id, draft.revision
    await tap(dp, bot, draft, action, by=actor, value="price")
    answers = [c for c in recorder.calls if isinstance(c, AnswerCallbackQuery)]
    assert answers and answers[-1].show_alert is True
    assert not any(isinstance(c, SendPhoto | SendMediaGroup) for c in recorder.calls)
    async with factory() as session:
        row = await session.get(AnnouncementDraft, draft_id)
        assert row.status == "review" and row.revision == rev


@pytest.mark.parametrize(
    "action",
    [
        "edit",
        "confirm",
        "captions",
        "images",
        "caption",
        "image",
        "favourite",
        "preview",
        "publish",
        "review",
        "flower",
        "colour",
        "styles",
    ],
)
async def test_shared_owner_cannot_use_other_shop_draft_in_this_bot(world, action):
    factory, (_, b), bot, recorder, dp = world
    async with factory() as session:
        draft = await prepared(session, b)
        await session.commit()
        draft_id, revision = draft.id, draft.revision
    await tap(dp, bot, draft, action, value="price")
    answers = [call for call in recorder.calls if isinstance(call, AnswerCallbackQuery)]
    assert answers and answers[-1].show_alert
    assert not any(isinstance(call, SendPhoto | SendMediaGroup) for call in recorder.calls)
    async with factory() as session:
        draft = await session.get(AnnouncementDraft, draft_id)
        assert draft.status == "review" and draft.revision == revision


async def test_draft_scope_includes_shop_and_author(world):
    factory, (a, b), _, _, _ = world
    async with factory() as session:
        draft = await prepared(session, a)
        for shop, actor in [(b, OWNER), (a, CLERK)]:
            assert await refused(
                service.draft_for(session, shop_id=shop, actor=actor, draft_id=draft.id)
            )
        assert await refused(
            service.draft_for(
                session, shop_id=a, actor=OWNER, draft_id=draft.id, revision=draft.revision + 1
            )
        )


async def test_staff_revocation_and_pause_refused(world):
    factory, (a, _), bot, _, _ = world
    async with factory() as session:
        draft = await prepared(session, a, CLERK)
        clerk = await session.get(ShopStaff, (a, CLERK))
        await session.delete(clerk)
        await session.flush()
        assert await refused(service.draft_for(session, shop_id=a, actor=CLERK, draft_id=draft.id))
        shop = await session.get(Shop, a)
        shop.status = "paused"
        await session.flush()
        assert not await service.may_publish(session, shop_id=a, actor=OWNER)
        assert await refused(service.new_draft(session, shop_id=a, actor=OWNER))


async def test_preference_tenancy(world):
    factory, (a, b), _, _, _ = world
    async with factory() as session:
        draft = await prepared(session, a)
        draft.caption_style, draft.image_style = "premium", "gold-corners"
        await service.save_favourite(
            session, shop_id=a, actor=CLERK, draft=await prepared(session, a, CLERK)
        )
        await service.save_favourite(session, shop_id=a, actor=OWNER, draft=draft)
        assert await refused(service.save_favourite(session, shop_id=b, actor=OWNER, draft=draft))
        assert (await service.new_draft(session, shop_id=a, actor=CLERK)).caption_style == "premium"
        assert (await service.new_draft(session, shop_id=b, actor=OWNER)).caption_style == "classic"


async def test_shop_aliases_do_not_cross_tenants(world):
    factory, (a, b), _, _, _ = world
    async with factory() as session:
        session.add_all(
            [
                HashtagAlias(shop_id=a, alias_normalized="gulcha", canonical_hashtag="atirgul"),
                HashtagAlias(shop_id=b, alias_normalized="gulcha", canonical_hashtag="tyulpan"),
            ]
        )
        await session.flush()
        for shop, expected in [(a, "atirgul"), (b, "tyulpan")]:
            draft = await prepared(session, shop)
            await service.parse_description(
                session, draft, "qizil gulcha ellik bitta dona narxi 450 ming so'm"
            )
            assert draft.fields["flowers"] == [expected]


@pytest.mark.parametrize("model", [AnnouncementDraft, AnnouncementPreference])
async def test_new_tables_require_real_shop(world, model):
    factory, _, _, _, _ = world
    async with factory() as session:
        blocked = False
        try:
            async with session.begin_nested():
                row = model(
                    shop_id=99999999999,
                    **(
                        {"author_id": OWNER}
                        if model is AnnouncementDraft
                        else {"caption_style": "classic", "image_style": "none"}
                    ),
                )
                session.add(row)
                await session.flush()
        except IntegrityError:
            blocked = True
        assert blocked, "A draft/preference cannot belong to a nonexistent shop"


@pytest.mark.parametrize("status", ["collecting", "confirmed", "transcribing", "published"])
async def test_confirmation_requires_review(world, status):
    factory, (a, _), _, _, _ = world
    async with factory() as session:
        draft = await prepared(session, a)
        draft.status = status
        rejected = False
        try:
            service.confirm(draft)
        except service.AnnouncementRefused:
            rejected = True
        assert rejected
        assert draft.status == status


async def test_incomplete_parse_cannot_be_confirmed(world):
    factory, (a, _), _, _, _ = world
    async with factory() as session:
        draft = await prepared(session, a)
        draft.fields["price"] = None
        rejected = False
        try:
            service.confirm(draft)
        except ValueError:
            rejected = True
        assert rejected
        assert draft.status == "review"


async def test_unconfirmed_preview_and_missing_exact_preview_refused(world):
    factory, (a, _), bot, recorder, _ = world
    async with factory() as session:
        draft = await prepared(session, a)
        message = Message(
            message_id=1, date=datetime.now(UTC), chat=Chat(id=OWNER, type="private")
        ).as_(bot)
        assert await refused(exact_preview(bot, message, session, draft))
        assert not recorder.calls
        # Even a forged/stale cached preview cannot replace field confirmation.
        draft.preview_media = ["unconfirmed-photo"]
        draft.preview_caption = "Atirgul\nNarxi: 450 000 so'm\n#atirgul #buket"
        assert await refused(
            service.publish(
                session, bot=bot, shop_id=a, actor=OWNER, draft_id=draft.id, revision=draft.revision
            )
        )
        assert not recorder.calls
        service.confirm(draft)
        assert await refused(
            service.publish(
                session, bot=bot, shop_id=a, actor=OWNER, draft_id=draft.id, revision=draft.revision
            )
        )
        assert not recorder.calls


async def test_receipts_cannot_index_another_shop(world):
    factory, (a, b), _, _, _ = world
    async with factory() as session:
        draft = await prepared(session, a)
        draft.receipts = [
            {
                "shop_id": b,
                "chat_id": -100922002,
                "message_id": 123,
                "file_id": "other-shop-photo",
                "media_group_id": None,
                "caption": "Atirgul buketi\nNarxi: 450 000 so'm\n#atirgul #buket",
            }
        ]
        assert await refused(service.index_receipts(session, draft))
        assert not (await session.scalars(select(Product).where(Product.shop_id == b))).all()


@pytest.mark.parametrize("photos", [1, 2, 10])
async def test_exact_preview_publish_index_and_duplicate_updates(world, photos):
    factory, (a, _), bot, recorder, dp = world
    async with factory() as session:
        draft = await prepared(session, a, photos=photos)
        with pytest.raises(service.AnnouncementRefused):
            await service.publish(
                session, bot=bot, shop_id=a, actor=OWNER, draft_id=draft.id, revision=draft.revision
            )
        service.confirm(draft)
        await exact_preview(
            bot,
            Message(message_id=1, date=datetime.now(UTC), chat=Chat(id=OWNER, type="private")).as_(
                bot
            ),
            session,
            draft,
        )
        preview_media, preview_caption = list(draft.preview_media), draft.preview_caption
        link = await service.publish(
            session, bot=bot, shop_id=a, actor=OWNER, draft_id=draft.id, revision=draft.revision
        )
        assert link.startswith("https://t.me/c/922001/")
        sent = recorder.calls[-1]
        assert isinstance(sent, SendPhoto | SendMediaGroup)
        assert (
            sent.media[0].caption if isinstance(sent, SendMediaGroup) else sent.caption
        ) == preview_caption
        assert (
            str(sent.media[0].media) if isinstance(sent, SendMediaGroup) else str(sent.photo)
        ) == preview_media[0]
        count = len(recorder.calls)
        assert (
            await service.publish(
                session, bot=bot, shop_id=a, actor=OWNER, draft_id=draft.id, revision=draft.revision
            )
            == link
        )
        assert len(recorder.calls) == count
        await service.index_receipts(session, draft)  # Later own channel updates use the same code.
        await session.flush()
        products = (await session.scalars(select(Product).where(Product.shop_id == a))).all()
        assert len(products) == 1
        assert products[0].price_uzs == 450000 and products[0].finalized_at
        assert products[0].name == "Atirgul buketi — 51 dona"
        receipts = list(draft.receipts)

    async def schedule(*, shop_id, media_group_id):
        assert shop_id == a

    dp["schedule_finalize"] = schedule
    for i, data in enumerate(receipts):
        # Telegram may deliver these after sendPhoto/sendMediaGroup returned.
        await dp.feed_update(
            bot,
            Update(
                update_id=1000 + i,
                channel_post=channel_message(
                    message_id=data["message_id"],
                    caption=data["caption"],
                    file_id=data["file_id"],
                    media_group_id=data["media_group_id"],
                    chat_id=data["chat_id"],
                ),
            ),
        )
    async with factory() as session:
        draft = await session.get(AnnouncementDraft, draft.id)
        await service.index_receipts(session, draft)  # The delayed album finalizer.
        products = (await session.scalars(select(Product).where(Product.shop_id == a))).all()
        assert len(products) == 1 and products[0].price_uzs == 450000
        assert products[0].finalized_at


async def test_failed_send_never_blindly_retries(world):
    factory, (a, _), bot, recorder, _ = world
    async with factory() as session:
        draft = await prepared(session, a)
        service.confirm(draft)
        await exact_preview(
            bot,
            Message(message_id=1, date=datetime.now(UTC), chat=Chat(id=OWNER, type="private")).as_(
                bot
            ),
            session,
            draft,
        )
        recorder.fail = True
        with pytest.raises(service.AnnouncementRefused):
            await service.publish(
                session, bot=bot, shop_id=a, actor=OWNER, draft_id=draft.id, revision=draft.revision
            )
        assert draft.status == "ambiguous"
        calls = len(recorder.calls)
        with pytest.raises(service.AnnouncementRefused):
            await service.publish(
                session, bot=bot, shop_id=a, actor=OWNER, draft_id=draft.id, revision=draft.revision
            )
        assert len(recorder.calls) == calls


async def test_complete_text_flow_through_dispatcher(world):
    factory, (a, _), bot, recorder, dp = world
    await dp.feed_update(bot, text_update(t("btn.menu.announcement", "uz"), user_id=OWNER))
    photo = Message(
        message_id=2,
        date=datetime.now(UTC),
        chat=Chat(id=OWNER, type="private"),
        from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
        photo=photo_sizes("uploaded"),
    )
    await dp.feed_update(bot, Update(update_id=2, message=photo))
    await dp.feed_update(
        bot,
        text_update(
            "qizil atirgul ellik bitta dona narxi 450 ming so'm", user_id=OWNER, update_id=3
        ),
    )

    async def row():
        async with factory() as session:
            return await session.scalar(
                select(AnnouncementDraft).where(AnnouncementDraft.shop_id == a)
            )

    draft = await row()
    assert draft.fields["price"] == 450000 and draft.fields["count"] == 51
    await tap(dp, bot, draft, "confirm")
    draft = await row()
    assert draft.status == "confirmed"
    await tap(dp, bot, draft, "caption", value="festive")
    await tap(dp, bot, await row(), "preview")
    draft = await row()
    assert draft.status == "preview" and "🎉" in draft.preview_caption
    await tap(dp, bot, draft, "publish")
    assert (await row()).status == "published"
    assert any(
        "Joylandi: https://t.me/c/" in c.text for c in recorder.calls if isinstance(c, SendMessage)
    )


async def test_manual_edits_invalidate_confirmed_preview(world, monkeypatch):
    factory, (a, _), bot, _, dp = world
    # CP23: a shop with no saved CP22 style now previews a flower template,
    # which draws on the first photo, so the fake bot must hand one over.
    jpeg = io.BytesIO()
    Image.new("RGB", (900, 1200), "#c36481").save(jpeg, format="JPEG")

    async def download(file_id, *, destination, timeout=30):  # noqa: ASYNC109 aiogram contract
        destination.write(jpeg.getvalue())

    monkeypatch.setattr(bot, "download", download)
    async with factory() as session:
        draft = await prepared(session, a)
        await session.commit()
    await tap(dp, bot, draft, "edit", value="price")
    await dp.feed_update(bot, text_update("yarim million", user_id=OWNER))
    async with factory() as session:
        draft = await session.get(AnnouncementDraft, draft.id)
        assert draft.fields["price"] == 500000 and draft.status == "review"
        rev = draft.revision
    await tap(dp, bot, draft, "confirm")
    async with factory() as session:
        draft = await session.get(AnnouncementDraft, draft.id)
    await tap(dp, bot, draft, "preview")
    async with factory() as session:
        draft = await session.get(AnnouncementDraft, draft.id)
        assert draft.status == "preview"
    await tap(dp, bot, draft, "colour", value="oq")
    async with factory() as session:
        draft = await session.get(AnnouncementDraft, draft.id)
        assert draft.fields["colour"] == "oq"
        assert draft.status == "review" and not draft.preview_media and not draft.preview_caption
        assert draft.revision > rev


async def test_photo_limit_and_voice_immediate_ack(world, monkeypatch):
    from aiogram.types import Voice

    from gulbot.worker import stt_tasks

    factory, (a, _), bot, recorder, dp = world
    await dp.feed_update(bot, text_update(t("btn.menu.announcement", "uz"), user_id=OWNER))
    for i in range(11):
        message = Message(
            message_id=i + 2,
            date=datetime.now(UTC),
            chat=Chat(id=OWNER, type="private"),
            from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
            photo=photo_sizes(f"photo-{i}"),
            media_group_id="upload-album",
        )
        await dp.feed_update(bot, Update(update_id=i + 2, message=message))
    async with factory() as session:
        draft = await session.scalar(
            select(AnnouncementDraft).where(AnnouncementDraft.shop_id == a)
        )
        assert len(draft.photos) == 10
    jobs = []

    async def queue(**kwargs):
        assert any(
            c.text == "Ovoz qayta ishlanmoqda..."
            for c in recorder.calls
            if isinstance(c, SendMessage)
        )
        jobs.append(kwargs)
        return "fake-job"

    monkeypatch.setattr(stt_tasks, "enqueue_transcription", queue)
    message = Message(
        message_id=20,
        date=datetime.now(UTC),
        chat=Chat(id=OWNER, type="private"),
        from_user=User(id=OWNER, is_bot=False, first_name="Owner"),
        voice=Voice(
            file_id="voice-file", file_unique_id="voice-unique", duration=30, mime_type="audio/ogg"
        ),
    )
    await dp.feed_update(bot, Update(update_id=20, message=message))
    assert len(jobs) == 1 and jobs[0]["shop_id"] == a and jobs[0]["actor"] == OWNER
    assert jobs[0]["file_id"] == "voice-file"
    async with factory() as session:
        draft = await session.get(AnnouncementDraft, draft.id)
        assert draft.status == "transcribing" and draft.acknowledgement_id


@pytest.mark.parametrize("fail", [False, True])
async def test_worker_fake_transcription_edits_ack_and_deletes_audio(
    world, monkeypatch, tmp_path, fail
):
    from aiogram.methods import EditMessageText

    from gulbot.announcements.stt import Transcript
    from gulbot.config import Settings
    from gulbot.worker import stt_tasks

    factory, (a, _), bot, recorder, _ = world
    async with factory() as session:
        draft = await prepared(session, a)
        draft.status, draft.acknowledgement_id = "transcribing", 999
        await session.commit()
        monkeypatch.setattr(
            stt_tasks, "get_settings", lambda: Settings(stt_audio_dir=str(tmp_path))
        )

        async def download(file_id, *, destination, timeout):  # noqa: ASYNC109 aiogram contract
            destination.write_bytes(b"fake voice")

        monkeypatch.setattr(bot, "download", download)

        def transcriber(source, wav, settings):
            assert source.read_bytes() == b"fake voice"
            if fail:
                raise ValueError("fake recognizer error")
            return Transcript("qizil atirgul ellik bitta dona narxi 450 ming so'm", "fake")

        monkeypatch.setattr(stt_tasks, "transcribe", transcriber)
        await stt_tasks.process(session, bot, draft, "voice-file")
        assert not list(tmp_path.iterdir())
        edits = [c for c in recorder.calls if isinstance(c, EditMessageText)]
        assert edits and edits[-1].message_id == 999
        assert draft.status == "review"
        if fail:
            assert "matn" in edits[-1].text
        else:
            assert "450000" in edits[-1].text and edits[-1].reply_markup
            assert draft.fields["price"] == 450000 and draft.fields["count"] == 51
