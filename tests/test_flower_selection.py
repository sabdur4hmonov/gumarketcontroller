"""CP23 phase 1: choosing a flower template, remembered per flower, per shop.

* after confirmation the draft gets the template the owner would expect:
  the shop's favourite for THIS flower, else (a shop that saved a CP22
  style before CP23) the CP22 family unchanged, else the flower's classic;
* "templates" shows the detected flower's ten layouts first, as previews
  rendered on the owner's own photo; "families" offers every flower and
  CP22's own styles;
* a favourite is per (shop, flower) and never crosses shops;
* every new callback is refused to anyone but the shop's owners and staff,
  and refused on another shop's draft.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from html import unescape

import pytest
import pytest_asyncio
from aiogram import Bot
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import AnswerCallbackQuery, SendMediaGroup, SendMessage, SendPhoto
from aiogram.types import BufferedInputFile, Chat, Message
from PIL import Image
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from tests.bot_harness import (
    TEST_TOKEN,
    RecordingSession,
    bound_session_factory,
    callback_update,
    photo_sizes,
)

from gulbot.announcements.extraction import Fields
from gulbot.announcements.flower_templates import caption as flower_caption
from gulbot.announcements.layouts import LAYOUT_IDS, LAYOUTS
from gulbot.announcements.themes import THEMES
from gulbot.bot.callbacks import AnnouncementCB
from gulbot.bot.factory import build_dispatcher
from gulbot.models.announcement import (
    LAYOUT_IDS as MODEL_LAYOUTS,
)
from gulbot.models.announcement import (
    THEME_IDS as MODEL_THEMES,
)
from gulbot.models.announcement import (
    AnnouncementDraft,
    AnnouncementPreference,
    AnnouncementThemeFavourite,
)
from gulbot.models.shop import DEFAULT_WORKING_HOURS, Shop
from gulbot.models.staff import ShopStaff
from gulbot.services import announcements as service

OWNER, OTHER, CLERK, CUSTOMER = 923001, 923002, 923003, 923004


def jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (900, 1200), "#c36481").save(out, format="JPEG")
    return out.getvalue()


class Recorder(RecordingSession):
    async def make_request(self, bot, method, timeout=None):  # noqa: ASYNC109 aiogram contract
        if isinstance(method, SendPhoto | SendMediaGroup):
            self.calls.append(method)
            items = method.media if isinstance(method, SendMediaGroup) else [method]
            messages = [
                Message(
                    message_id=500 + len(self.calls) * 10 + i,
                    date=datetime.now(UTC),
                    chat=Chat(id=method.chat_id, type="private"),
                    photo=photo_sizes(f"shown-{len(self.calls)}-{i}"),
                    caption=unescape(item.caption) if item.caption else None,
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
            name="A",
            channel_id=-100923001,
            owner_telegram_ids=[OWNER],
            working_hours=DEFAULT_WORKING_HOURS,
        )
        b = Shop(
            name="B",
            channel_id=-100923002,
            owner_telegram_ids=[OTHER, OWNER],
            working_hours=DEFAULT_WORKING_HOURS,
            lang="ru",
        )
        session.add_all([a, b])
        await session.flush()
        session.add(ShopStaff(shop_id=a.id, telegram_id=CLERK, added_by=OWNER))
        await session.commit()
        ids = a.id, b.id
    recorder = Recorder()
    bot = Bot(token=TEST_TOKEN, session=recorder)
    photo = jpeg()

    async def download(file_id, *, destination, timeout=30):  # noqa: ASYNC109 aiogram contract
        destination.write(photo)

    monkeypatch.setattr(bot, "download", download)
    dp = build_dispatcher(session_factory=factory, shop_id=ids[0], storage=MemoryStorage())
    yield factory, ids, bot, recorder, dp
    await bot.session.close()


async def prepared(session, shop, *, flowers=("atirgul",), actor=OWNER, raw=""):
    draft = await service.new_draft(session, shop_id=shop, actor=actor)
    draft.photos = ["photo-0"]
    draft.fields = Fields(
        flowers=list(flowers), count=51, price=450_000, colour="qizil", raw=raw
    ).data()
    draft.status = "review"
    await session.flush()
    return draft


async def confirmed(session, shop, **kwargs):
    draft = await prepared(session, shop, **kwargs)
    service.confirm(draft)
    await service.apply_default_template(session, draft)
    await session.flush()
    return draft


async def tap(dp, bot, draft, action, *, by=OWNER, value=""):
    data = AnnouncementCB(
        action=action, draft=draft.id, revision=draft.revision, value=value
    ).pack()
    await dp.feed_update(bot, callback_update(data, user_id=by))


# --- the data the database checks -------------------------------------------------


def test_the_database_checks_name_exactly_the_themes_and_layouts() -> None:
    assert tuple(THEMES) == MODEL_THEMES
    assert MODEL_LAYOUTS == LAYOUT_IDS


@pytest.mark.parametrize(("theme", "layout"), [("nope", "classic"), ("atirgul", "nope")])
async def test_a_favourite_outside_the_lists_is_refused_by_postgres(world, theme, layout):
    factory, (a, _), *_ = world
    async with factory() as session:
        session.add(AnnouncementThemeFavourite(shop_id=a, theme=theme, layout=layout))
        with pytest.raises(
            IntegrityError, match="announcement_theme_favourites_(theme|layout)_known"
        ):
            await session.flush()


async def test_a_draft_template_must_have_the_shape(world):
    factory, (a, _), *_ = world
    async with factory() as session:
        draft = await prepared(session, a)
        await session.commit()
        with pytest.raises(IntegrityError, match="template_shape"):
            await session.execute(
                text("UPDATE announcement_drafts SET template = 'x:y' WHERE id = :i"),
                {"i": draft.id},
            )


# --- which template after confirmation -------------------------------------------


@pytest.mark.parametrize(
    ("flowers", "raw", "expected"),
    [
        (("atirgul",), "", "atirgul.classic"),
        (("tyulpan",), "", "lola.classic"),
        (("atirgul", "tyulpan"), "", "aralash.classic"),
        (("pion",), "pionlar qutida", "quti.classic"),
    ],
)
async def test_a_new_shop_gets_the_detected_flowers_classic(world, flowers, raw, expected):
    factory, (a, _), *_ = world
    async with factory() as session:
        draft = await confirmed(session, a, flowers=flowers, raw=raw)
        assert draft.template == expected


async def test_the_favourite_is_remembered_per_flower(world):
    factory, (a, _), *_ = world
    async with factory() as session:
        rose = await confirmed(session, a, flowers=("atirgul",))
        service.choose_template(rose, "atirgul.premium")
        await service.save_favourite(session, shop_id=a, actor=OWNER, draft=rose)
        tulip = await confirmed(session, a, flowers=("tyulpan",))
        service.choose_template(tulip, "lola.festive")
        await service.save_favourite(session, shop_id=a, actor=OWNER, draft=tulip)
        await session.flush()
        assert (await confirmed(session, a, flowers=("atirgul",))).template == "atirgul.premium"
        assert (await confirmed(session, a, flowers=("tyulpan",))).template == "lola.festive"
        assert (await confirmed(session, a, flowers=("pion",))).template == "pion.classic"
        rows = (await session.scalars(select(AnnouncementThemeFavourite))).all()
        assert {(r.shop_id, r.theme, r.layout) for r in rows} == {
            (a, "atirgul", "premium"),
            (a, "lola", "festive"),
        }


async def test_a_favourite_never_crosses_shops(world):
    factory, (a, b), *_ = world
    async with factory() as session:
        rose = await confirmed(session, a)
        service.choose_template(rose, "atirgul.gift")
        await service.save_favourite(session, shop_id=a, actor=OWNER, draft=rose)
        await session.flush()
        assert (await confirmed(session, b)).template == "atirgul.classic"
        # And the actor may not save shop A's draft as shop B's favourite.
        with pytest.raises(service.AnnouncementRefused):
            await service.save_favourite(session, shop_id=b, actor=OWNER, draft=rose)


async def test_a_saved_cp22_style_keeps_the_cp22_family(world):
    factory, (a, _), *_ = world
    async with factory() as session:
        session.add(
            AnnouncementPreference(shop_id=a, caption_style="premium", image_style="gold-corners")
        )
        await session.flush()
        draft = await confirmed(session, a)
        assert draft.template is None
        assert (draft.caption_style, draft.image_style) == ("premium", "gold-corners")
        # A flower favourite outranks it for that flower only.
        session.add(AnnouncementThemeFavourite(shop_id=a, theme="atirgul", layout="minimal"))
        await session.flush()
        assert (await confirmed(session, a)).template == "atirgul.minimal"
        assert (await confirmed(session, a, flowers=("pion",))).template is None


async def test_an_explicit_choice_survives_a_reconfirm(world):
    factory, (a, _), *_ = world
    async with factory() as session:
        draft = await confirmed(session, a)
        service.choose_template(draft, "gerbera.playful")
        service.invalidate(draft)  # back to review, as an edit does
        service.confirm(draft)
        await service.apply_default_template(session, draft)
        assert draft.template == "gerbera.playful"
        service.choose_style(draft, kind="caption", value="festive")
        assert draft.template is None and draft.template_picked


async def test_choosing_refuses_unknown_and_unconfirmed(world):
    factory, (a, _), *_ = world
    async with factory() as session:
        draft = await prepared(session, a)
        with pytest.raises(service.AnnouncementRefused):
            service.choose_template(draft, "atirgul.classic")  # not confirmed yet
        service.confirm(draft)
        with pytest.raises(service.AnnouncementRefused):
            service.choose_template(draft, "atirgul.nope")
        with pytest.raises(service.AnnouncementRefused):
            service.choose_template(draft, "nope.classic")


async def test_the_caption_language_starts_from_the_shop_and_cycles(world):
    factory, (a, b), *_ = world
    async with factory() as session:
        assert (await prepared(session, a)).caption_lang == "uz"
        draft = await confirmed(session, b)
        assert draft.caption_lang == "ru"
        seen = []
        for _ in range(3):
            service.next_caption_lang(draft)
            seen.append(draft.caption_lang)
        assert seen == ["uz", "uz_cyrl", "ru"]


# --- through the dispatcher ---------------------------------------------------------


async def test_templates_show_the_flowers_ten_on_the_owners_photo(world):
    factory, (a, _), bot, recorder, dp = world
    async with factory() as session:
        draft = await confirmed(session, a, flowers=("tyulpan",))
        await session.commit()
    await tap(dp, bot, draft, "templates")
    albums = [c for c in recorder.calls if isinstance(c, SendMediaGroup)]
    assert len(albums) == 1 and len(albums[0].media) == 10
    assert [m.caption for m in albums[0].media] == [
        f"{i}. {LAYOUTS[layout].label[0]}" for i, layout in enumerate(LAYOUT_IDS, 1)
    ]
    assert all(isinstance(m.media, BufferedInputFile) for m in albums[0].media)
    keyboards = [
        c.reply_markup for c in recorder.calls if isinstance(c, SendMessage) and c.reply_markup
    ]
    values = [
        AnnouncementCB.unpack(b.callback_data).value
        for row in keyboards[-1].inline_keyboard
        for b in row
        if b.callback_data
    ]
    assert values[:10] == [f"lola.{layout}" for layout in LAYOUT_IDS]


async def test_families_offer_every_flower_and_the_cp22_styles(world):
    factory, (a, _), bot, recorder, dp = world
    async with factory() as session:
        draft = await confirmed(session, a)
        await session.commit()
    await tap(dp, bot, draft, "families")
    markup = [c.reply_markup for c in recorder.calls if isinstance(c, SendMessage)][-1]
    actions = [
        AnnouncementCB.unpack(b.callback_data) for row in markup.inline_keyboard for b in row
    ]
    assert [cb.value for cb in actions if cb.action == "templates"] == list(THEMES)
    assert any(cb.action == "legacy" for cb in actions)


async def test_picking_then_previewing_uses_the_template(world):
    factory, (a, _), bot, recorder, dp = world
    async with factory() as session:
        draft = await confirmed(session, a)
        await session.commit()
    await tap(dp, bot, draft, "tpl", value="atirgul.price_first")
    async with factory() as session:
        draft = await session.get(AnnouncementDraft, draft.id)
        assert draft.template == "atirgul.price_first"
    await tap(dp, bot, draft, "preview")
    async with factory() as session:
        draft = await session.get(AnnouncementDraft, draft.id)
        fields = Fields.from_data(draft.fields)
        expected = flower_caption(fields, template="atirgul.price_first", shop_name="A", lang="uz")
        assert draft.status == "preview" and draft.preview_caption == expected
    shown = [c for c in recorder.calls if isinstance(c, SendPhoto)][-1]
    assert isinstance(shown.photo, BufferedInputFile)  # the rendered overlay, not the original


NEW_ACTIONS = [
    ("templates", ""),
    ("templates", "lola"),
    ("tpl", "lola.gift"),
    ("families", ""),
    ("lang", ""),
    ("legacy", ""),
]


@pytest.mark.parametrize("actor", [OTHER, CUSTOMER])
@pytest.mark.parametrize(("action", "value"), NEW_ACTIONS)
async def test_every_new_crafted_callback_is_refused(world, actor, action, value):
    factory, (a, _), bot, recorder, dp = world
    async with factory() as session:
        draft = await confirmed(session, a)
        await session.commit()
        before = (draft.template, draft.caption_lang, draft.revision)
    await tap(dp, bot, draft, action, by=actor, value=value)
    answers = [c for c in recorder.calls if isinstance(c, AnswerCallbackQuery)]
    assert answers and answers[-1].show_alert is True
    assert not any(isinstance(c, SendPhoto | SendMediaGroup) for c in recorder.calls)
    async with factory() as session:
        row = await session.get(AnnouncementDraft, draft.id)
        assert (row.template, row.caption_lang, row.revision) == before


@pytest.mark.parametrize(("action", "value"), NEW_ACTIONS)
async def test_another_shops_draft_is_refused_for_every_new_action(world, action, value):
    factory, (_, b), bot, recorder, dp = world
    async with factory() as session:
        draft = await confirmed(session, b)  # OWNER owns B too; this bot is shop A's
        await session.commit()
        before = (draft.template, draft.caption_lang, draft.revision)
    await tap(dp, bot, draft, action, value=value)
    answers = [c for c in recorder.calls if isinstance(c, AnswerCallbackQuery)]
    assert answers and answers[-1].show_alert is True
    assert not any(isinstance(c, SendPhoto | SendMediaGroup) for c in recorder.calls)
    async with factory() as session:
        row = await session.get(AnnouncementDraft, draft.id)
        assert (row.template, row.caption_lang, row.revision) == before


async def test_a_crafted_template_value_is_refused(world):
    factory, (a, _), bot, recorder, dp = world
    async with factory() as session:
        draft = await confirmed(session, a)
        await session.commit()
    await tap(dp, bot, draft, "tpl", value="atirgul.evil")
    await tap(dp, bot, draft, "templates", value="evil")
    answers = [c for c in recorder.calls if isinstance(c, AnswerCallbackQuery)]
    assert [a.show_alert for a in answers[-2:]] == [True, True]
    async with factory() as session:
        assert (await session.get(AnnouncementDraft, draft.id)).template == "atirgul.classic"
