"""CP23 phase 3 in the bot: "📲 Instagram'ga joylash", only when switched on.

Off (the default) the story arrives without the button, and a crafted tap is
answered "off" in the shop's language. On and connected, the tap stores the
story for Meta and queues ONE publishing task with the upload's URL token.
The same refusals as every announcement callback: author only, own shop
only, published posts only, real layouts only.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from aiogram import Bot
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import AnswerCallbackQuery, SendMessage
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import select
from tests.bot_harness import TEST_TOKEN, bound_session_factory
from tests.test_story_images import (
    CLERK,
    CUSTOMER,
    OTHER,
    OWNER,
    SHAPES,
    Recorder,
    published,
    tap,
)

import gulbot.services.shop_tokens as shop_tokens_module
import gulbot.worker.instagram_tasks as instagram_tasks
from gulbot.bot.callbacks import AnnouncementCB
from gulbot.bot.factory import build_dispatcher
from gulbot.models.instagram import InstagramConnection, InstagramStoryUpload
from gulbot.models.shop import DEFAULT_WORKING_HOURS, Shop
from gulbot.models.staff import ShopStaff
from gulbot.services import instagram


@pytest_asyncio.fixture
async def world(db, settings, monkeypatch):
    factory = bound_session_factory(db)
    async with factory() as session:
        a = Shop(
            name="Gulshan",
            channel_id=-100926001,
            owner_telegram_ids=[OWNER],
            working_hours=DEFAULT_WORKING_HOURS,
        )
        b = Shop(
            name="B",
            channel_id=-100926002,
            owner_telegram_ids=[OTHER, OWNER],
            working_hours=DEFAULT_WORKING_HOURS,
        )
        session.add_all([a, b])
        await session.flush()
        session.add(ShopStaff(shop_id=a.id, telegram_id=CLERK, added_by=OWNER))
        await session.commit()
        ids = a.id, b.id
    recorder = Recorder()
    bot = Bot(token=TEST_TOKEN, session=recorder)

    async def download(file_id, *, destination, timeout=30):  # noqa: ASYNC109 aiogram contract
        destination.write(SHAPES["portrait"])

    monkeypatch.setattr(bot, "download", download)
    queued: list[tuple[int, str]] = []

    async def enqueue(upload_id: int, token: str) -> None:
        queued.append((upload_id, token))

    monkeypatch.setattr(instagram_tasks, "enqueue_story", enqueue)
    key = SecretStr(Fernet.generate_key().decode())
    monkeypatch.setattr(
        shop_tokens_module,
        "get_settings",
        lambda: settings.model_copy(update={"shop_token_encryption_key": key}),
    )
    dp = build_dispatcher(session_factory=factory, shop_id=ids[0], storage=MemoryStorage())
    yield factory, ids, bot, recorder, dp, queued
    await bot.session.close()


def switch_on(monkeypatch, settings) -> None:
    on = settings.model_copy(
        update={
            "instagram_publishing_enabled": True,
            "instagram_app_id": "123",
            "instagram_app_secret": SecretStr("s"),
            "public_base_url": "https://pages.test",
        }
    )
    monkeypatch.setattr(instagram, "get_settings", lambda: on)


async def connect(session, shop_id: int) -> None:
    session.add(
        InstagramConnection(
            shop_id=shop_id,
            ig_user_id="17841400000000001",
            username="gulshan",
            token_encrypted=shop_tokens_module.encrypt_access_token("IGAAtokenTOKENtoken000001"),
            token_expires_at=datetime.now(UTC) + timedelta(days=50),
            connected_by=OWNER,
        )
    )
    await session.flush()


def last_buttons(recorder) -> list[AnnouncementCB]:
    markup = [c for c in recorder.calls if isinstance(c, SendMessage)][-1].reply_markup
    if markup is None:
        return []
    return [AnnouncementCB.unpack(b.callback_data) for row in markup.inline_keyboard for b in row]


async def test_off_the_story_has_no_button_and_a_tap_says_off(world):
    factory, (a, _), bot, recorder, dp, queued = world
    assert not instagram.enabled()
    async with factory() as session:
        draft = await published(session, a)
        await connect(session, a)
        await session.commit()
    await tap(dp, bot, draft, "storyl", value="arch")
    assert last_buttons(recorder) == []
    await tap(dp, bot, draft, "igpub", value="arch")
    answer = [c for c in recorder.calls if isinstance(c, AnswerCallbackQuery)][-1]
    assert answer.show_alert and answer.text == instagram.message("off", "uz")[:180]
    assert queued == []


async def test_on_but_not_connected_there_is_no_button(world, monkeypatch, settings):
    factory, (a, _), bot, recorder, dp, queued = world
    switch_on(monkeypatch, settings)
    async with factory() as session:
        draft = await published(session, a)
        await session.commit()
    await tap(dp, bot, draft, "storyl", value="arch")
    assert last_buttons(recorder) == []


async def test_on_and_connected_the_tap_queues_one_story(world, monkeypatch, settings):
    factory, (a, _), bot, recorder, dp, queued = world
    switch_on(monkeypatch, settings)
    async with factory() as session:
        draft = await published(session, a)
        await connect(session, a)
        await session.commit()
    await tap(dp, bot, draft, "storyl", value="arch")
    assert [(b.action, b.value) for b in last_buttons(recorder)] == [("igpub", "arch")]
    await tap(dp, bot, draft, "igpub", value="arch")
    [(upload_id, token)] = queued
    async with factory() as session:
        upload = await session.get(InstagramStoryUpload, upload_id)
        assert (upload.shop_id, upload.draft_id, upload.layout) == (a, draft.id, "arch")
        assert upload.token_hash == hashlib.sha256(token.encode()).hexdigest()
        assert upload.image and upload.image[:2] == b"\xff\xd8"  # a JPEG
    texts = [c.text for c in recorder.calls if isinstance(c, SendMessage)]
    assert texts[-1] == instagram.message("queued", "uz")


@pytest.mark.parametrize("actor", [OTHER, CUSTOMER, CLERK])
async def test_only_the_author_can_publish(world, monkeypatch, settings, actor):
    factory, (a, _), bot, recorder, dp, queued = world
    switch_on(monkeypatch, settings)
    async with factory() as session:
        draft = await published(session, a)
        await connect(session, a)
        await session.commit()
    await tap(dp, bot, draft, "igpub", by=actor, value="arch")
    answer = [c for c in recorder.calls if isinstance(c, AnswerCallbackQuery)][-1]
    assert answer.show_alert is True and queued == []


@pytest.mark.parametrize(
    ("case", "value"), [("other_shop", "arch"), ("unpublished", "arch"), ("bad_layout", "evil")]
)
async def test_crafted_taps_queue_nothing(world, monkeypatch, settings, case, value):
    factory, (a, b), bot, recorder, dp, queued = world
    switch_on(monkeypatch, settings)
    async with factory() as session:
        shop = b if case == "other_shop" else a
        draft = await published(
            session, shop, status="preview" if case == "unpublished" else "published"
        )
        await connect(session, shop)
        await session.commit()
    await tap(dp, bot, draft, "igpub", value=value)
    answer = [c for c in recorder.calls if isinstance(c, AnswerCallbackQuery)][-1]
    assert answer.show_alert is True and queued == []
    async with factory() as session:
        assert (await session.scalars(select(InstagramStoryUpload))).all() == []
