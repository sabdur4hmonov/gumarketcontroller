"""CP23 phase 2: Instagram Story images, 15 flower themes x 10 story layouts.

* every one of the 150 variants is 1080x1920 and keeps EVERY text inside
  Instagram's safe zone (below the top ~250 px, above the bottom ~340 px),
  inside its panel, with a 9-digit price never cut -- on portrait and
  landscape photos;
* after publication the owner is offered "📸 Instagram istoriya": ten
  previews on the post's own photo, then the chosen story sent as a
  DOCUMENT (no recompression) and as a photo, with instructions;
* only the post's author among the shop's owners and staff can ask, only
  for a PUBLISHED post, only in that shop's bot, only for a real layout.
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
    SendDocument,
    SendMediaGroup,
    SendMessage,
    SendPhoto,
)
from aiogram.types import BufferedInputFile, Chat, Message
from PIL import Image
from tests.bot_harness import (
    TEST_TOKEN,
    RecordingSession,
    bound_session_factory,
    callback_update,
    photo_sizes,
)

from gulbot.announcements.extraction import Fields
from gulbot.announcements.flower_templates import money
from gulbot.announcements.stories import (
    ALL_STORIES,
    SAFE_BOTTOM,
    SAFE_TOP,
    STORY_LAYOUT_IDS,
    STORY_LAYOUTS,
    render_story,
)
from gulbot.announcements.themes import LANGS, THEMES
from gulbot.bot.callbacks import AnnouncementCB
from gulbot.bot.factory import build_dispatcher
from gulbot.bot.routers.announcements import STORY_HELP
from gulbot.models.shop import DEFAULT_WORKING_HOURS, Shop
from gulbot.models.staff import ShopStaff
from gulbot.services import announcements as service

OWNER, OTHER, CLERK, CUSTOMER = 924001, 924002, 924003, 924004
LONG_SHOP = "Gullar olami — Chilonzor filiali, Toshkent shahri, Bunyodkor ko'chasi 12"


def jpeg(width: int, height: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), "#c36481").save(out, format="JPEG")
    return out.getvalue()


SHAPES = {"portrait": jpeg(900, 1200), "landscape": jpeg(1600, 900)}


def apart(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    """Two boxes that do not overlap."""
    return a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]


#: A wide shop logo (the hardest shape for a square slot), as the shop
#: service stores it: RGBA, opaque mark on a transparent ground.
LOGO = Image.new("RGBA", (480, 140), (0, 0, 0, 0))
LOGO.paste(Image.new("RGBA", (460, 120), (122, 20, 36, 255)), (10, 10))


# --- the images, all 150 ------------------------------------------------------------


def test_fifteen_themes_ten_story_layouts() -> None:
    assert len(STORY_LAYOUTS) == 10
    assert len(ALL_STORIES) == len(set(ALL_STORIES)) == 150
    assert {story.partition(".")[0] for story in ALL_STORIES} == set(THEMES)


@pytest.mark.parametrize("shape", sorted(SHAPES))
@pytest.mark.parametrize("story", ALL_STORIES)
def test_every_story_keeps_its_text_in_the_safe_zone(story: str, shape: str) -> None:
    theme, _, layout = story.partition(".")
    lang = LANGS[ALL_STORIES.index(story) % 3]
    rendered = render_story(
        SHAPES[shape],
        theme=theme,
        layout=layout,
        price=999_999_999,
        colour="pushti",
        shop_name=LONG_SHOP,
        lang=lang,
        logo=LOGO,
    )
    assert (rendered.width, rendered.height) == (1080, 1920)
    # The shop's logo: where Instagram shows it, and never over any text.
    assert rendered.logo is not None
    lx0, ly0, lx1, ly1 = rendered.logo
    assert lx0 >= 0 and lx1 <= 1080 and ly0 >= SAFE_TOP and ly1 <= SAFE_BOTTOM, rendered.logo
    for box in rendered.boxes:
        assert apart(rendered.logo, box.container), (box.role, rendered.logo, box.container)
    roles = [box.role for box in rendered.boxes]
    assert {"name", "price", "shop"} <= set(roles)
    for box in rendered.boxes:
        x0, y0, x1, y1 = box.container
        assert y0 >= SAFE_TOP and y1 <= SAFE_BOTTOM, box
        assert x0 >= 0 and x1 <= 1080, box
        d0, e0, d1, e1 = box.drawn
        assert x0 <= d0 and y0 <= e0 and d1 <= x1 and e1 <= y1, box
        if box.role == "price":
            assert box.text == money(999_999_999, lang) and not box.truncated
    with Image.open(io.BytesIO(rendered.jpeg)) as image:
        assert image.size == (1080, 1920) and image.format == "JPEG"
        assert not image.getexif()


def test_a_preview_is_the_same_design_smaller() -> None:
    small = render_story(
        SHAPES["portrait"],
        theme="lola",
        layout="arch",
        price=1,
        colour="",
        shop_name="A",
        scale=0.25,
    )
    assert (small.width, small.height) == (270, 480)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"theme": "nope", "layout": "arch"},
        {"theme": "lola", "layout": "nope"},
        {"theme": "lola", "layout": "arch", "scale": 2.0},
    ],
)
def test_story_refuses_bad_input(kwargs) -> None:
    with pytest.raises(ValueError):
        render_story(SHAPES["portrait"], price=1, colour="", shop_name="A", **kwargs)


# --- through the bot ---------------------------------------------------------------


class Recorder(RecordingSession):
    async def make_request(self, bot, method, timeout=None):  # noqa: ASYNC109 aiogram contract
        if isinstance(method, SendPhoto | SendMediaGroup):
            self.calls.append(method)
            channel = int(method.chat_id) < 0
            items = method.media if isinstance(method, SendMediaGroup) else [method]
            messages = [
                Message(
                    message_id=700 + len(self.calls) * 10 + i,
                    date=datetime.now(UTC),
                    chat=Chat(id=method.chat_id, type="channel" if channel else "private"),
                    photo=photo_sizes(f"sent-{len(self.calls)}-{i}"),
                    caption=item.caption,
                )
                for i, item in enumerate(items)
            ]
            return messages if isinstance(method, SendMediaGroup) else messages[0]
        return await super().make_request(bot, method, timeout)


@pytest_asyncio.fixture
async def world(db, monkeypatch):
    factory = bound_session_factory(db)
    async with factory() as session:
        a = Shop(
            name="Gulshan",
            channel_id=-100924001,
            owner_telegram_ids=[OWNER],
            working_hours=DEFAULT_WORKING_HOURS,
        )
        b = Shop(
            name="B",
            channel_id=-100924002,
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
    photo = SHAPES["portrait"]

    async def download(file_id, *, destination, timeout=30):  # noqa: ASYNC109 aiogram contract
        destination.write(photo)

    monkeypatch.setattr(bot, "download", download)
    dp = build_dispatcher(session_factory=factory, shop_id=ids[0], storage=MemoryStorage())
    yield factory, ids, bot, recorder, dp
    await bot.session.close()


async def published(session, shop, *, actor=OWNER, status="published"):
    draft = await service.new_draft(session, shop_id=shop, actor=actor)
    draft.photos = ["photo-0"]
    draft.fields = Fields(flowers=["tyulpan"], count=25, price=300_000, colour="sariq").data()
    draft.template = "lola.festive"
    draft.status = status
    draft.receipts = (
        [
            {
                "shop_id": shop,
                "chat_id": -100924001,
                "message_id": 5,
                "file_id": "f",
                "media_group_id": None,
                "caption": "x",
            }
        ]
        if status == "published"
        else []
    )
    await session.flush()
    return draft


async def tap(dp, bot, draft, action, *, by=OWNER, value=""):
    data = AnnouncementCB(
        action=action, draft=draft.id, revision=draft.revision, value=value
    ).pack()
    await dp.feed_update(bot, callback_update(data, user_id=by))


async def test_publishing_offers_the_story(world):
    factory, (a, _), bot, recorder, dp = world
    async with factory() as session:
        draft = await published(session, a, status="preview")
        fields = Fields.from_data(draft.fields)
        from gulbot.announcements.flower_templates import caption

        draft.preview_media = ["shown-photo"]
        draft.preview_caption = caption(fields, template="lola.festive", shop_name="Gulshan")
        await session.commit()
    await tap(dp, bot, draft, "publish")
    replies = [c for c in recorder.calls if isinstance(c, SendMessage) and "Joylandi" in c.text]
    assert replies, "no publish reply"
    [[story_button]] = replies[-1].reply_markup.inline_keyboard
    assert AnnouncementCB.unpack(story_button.callback_data).action == "story"


async def test_the_ten_story_previews_then_the_chosen_story(world):
    factory, (a, _), bot, recorder, dp = world
    async with factory() as session:
        draft = await published(session, a)
        await session.commit()
    await tap(dp, bot, draft, "story")
    albums = [c for c in recorder.calls if isinstance(c, SendMediaGroup)]
    assert len(albums) == 1
    album = albums[0]
    assert len(album.media) == 10
    assert all(isinstance(m.media, BufferedInputFile) for m in album.media)
    keyboard = [c for c in recorder.calls if isinstance(c, SendMessage)][-1].reply_markup
    picks = [
        AnnouncementCB.unpack(b.callback_data) for row in keyboard.inline_keyboard for b in row
    ]
    assert [(p.action, p.value) for p in picks] == [
        ("storyl", layout) for layout in STORY_LAYOUT_IDS
    ]

    await tap(dp, bot, draft, "storyl", value="magazine")
    documents = [c for c in recorder.calls if isinstance(c, SendDocument)]
    assert len(documents) == 1, "the story must arrive as a document"
    document = documents[0]
    photo = [c for c in recorder.calls if isinstance(c, SendPhoto)][-1]
    assert isinstance(document.document, BufferedInputFile)
    assert document.document.filename == "istoriya-lola-magazine.jpg"
    assert photo.photo.data == document.document.data  # the same bytes, twice
    with Image.open(io.BytesIO(document.document.data)) as image:
        assert image.size == (1080, 1920)
    assert [c for c in recorder.calls if isinstance(c, SendMessage)][-1].text == STORY_HELP


@pytest.mark.parametrize("actor", [OTHER, CUSTOMER, CLERK])
@pytest.mark.parametrize(("action", "value"), [("story", ""), ("storyl", "arch")])
async def test_only_the_author_gets_a_story(world, actor, action, value):
    factory, (a, _), bot, recorder, dp = world
    async with factory() as session:
        draft = await published(session, a)  # authored by OWNER
        await session.commit()
    await tap(dp, bot, draft, action, by=actor, value=value)
    answers = [c for c in recorder.calls if isinstance(c, AnswerCallbackQuery)]
    assert answers and answers[-1].show_alert is True
    assert not any(isinstance(c, SendPhoto | SendMediaGroup | SendDocument) for c in recorder.calls)


async def test_staff_can_make_a_story_of_their_own_post(world):
    factory, (a, _), bot, recorder, dp = world
    async with factory() as session:
        draft = await published(session, a, actor=CLERK)
        await session.commit()
    await tap(dp, bot, draft, "storyl", by=CLERK, value="duo")
    assert any(isinstance(c, SendDocument) for c in recorder.calls)


@pytest.mark.parametrize(("action", "value"), [("story", ""), ("storyl", "arch")])
async def test_another_shops_post_is_refused(world, action, value):
    factory, (_, b), bot, recorder, dp = world
    async with factory() as session:
        draft = await published(session, b)  # OWNER owns B too; this is shop A's bot
        await session.commit()
    await tap(dp, bot, draft, action, value=value)
    answers = [c for c in recorder.calls if isinstance(c, AnswerCallbackQuery)]
    assert answers and answers[-1].show_alert is True
    assert not any(isinstance(c, SendMediaGroup | SendDocument) for c in recorder.calls)


@pytest.mark.parametrize("status", ["confirmed", "preview", "publishing", "ambiguous"])
async def test_no_story_before_the_post_exists(world, status):
    factory, (a, _), bot, recorder, dp = world
    async with factory() as session:
        draft = await published(session, a, status=status)
        await session.commit()
    await tap(dp, bot, draft, "storyl", value="arch")
    await tap(dp, bot, draft, "story")
    answers = [c for c in recorder.calls if isinstance(c, AnswerCallbackQuery)]
    assert [a.show_alert for a in answers[-2:]] == [True, True]
    assert not any(isinstance(c, SendMediaGroup | SendDocument) for c in recorder.calls)


async def test_a_crafted_story_layout_is_refused(world):
    factory, (a, _), bot, recorder, dp = world
    async with factory() as session:
        draft = await published(session, a)
        await session.commit()
    await tap(dp, bot, draft, "storyl", value="evil")
    answers = [c for c in recorder.calls if isinstance(c, AnswerCallbackQuery)]
    assert answers and answers[-1].show_alert is True
    assert not any(isinstance(c, SendDocument) for c in recorder.calls)


async def test_a_cp22_family_post_gets_its_flowers_story(world):
    factory, (a, _), *_ = world
    async with factory() as session:
        draft = await published(session, a)
        draft.template = None
        assert service.story_theme(draft) == "lola"
        draft.template = "pion.gift"
        assert service.story_theme(draft) == "pion"
