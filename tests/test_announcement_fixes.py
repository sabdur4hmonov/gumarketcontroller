"""CP23 addendum, part 1: the owner fixes what speech recognition got wrong.

* the confirmation screen shows what was HEARD and what was understood, ⚠
  on the fields extraction was unsure of, and the post exactly as the
  channel would get it -- after EVERY fix;
* four ways to fix, each ending on that screen with the corrected values:
  "✏️ Matnni tuzatish" (the SAME extraction on corrected text), the field
  buttons, "🎤 Qaytadan gapirish", and "❌ Bekor qilish" (nothing kept);
  nothing is published before confirmation;
* the shop LEARNS short mishearings (heard -> corrected) and applies them
  before the lexicon next time -- for that shop only; a change of mind or a
  rewritten description is never learned; deleting an entry stops it.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from aiogram import Bot
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import AnswerCallbackQuery, SendMediaGroup, SendMessage, SendPhoto
from sqlalchemy import select
from tests.bot_harness import (
    TEST_TOKEN,
    RecordingSession,
    bound_session_factory,
    callback_update,
    text_update,
)

from gulbot.announcements.extraction import Fields, extract
from gulbot.announcements.learning import (
    Learned,
    apply_learned,
    classify,
    diff_corrections,
    from_button,
)
from gulbot.bot.callbacks import AnnouncementCB
from gulbot.bot.factory import build_dispatcher
from gulbot.models.announcement import AnnouncementCorrection, AnnouncementDraft
from gulbot.models.shop import DEFAULT_WORKING_HOURS, Shop
from gulbot.models.staff import ShopStaff
from gulbot.services import announcement_learning
from gulbot.services import announcements as service

OWNER, OTHER, CLERK, CUSTOMER = 927001, 927002, 927003, 927004
HEARD = "Qizil atirgil ellik bitta dona, narxi to'rt yuz ellik ming so'm"
FIXED = "Qizil atirgul ellik bitta dona, narxi to'rt yuz ellik ming so'm"


# --- pure: what is heard, what is learned -------------------------------------------


def test_unsure_fields_are_marked_and_the_words_heard_kept() -> None:
    fields = extract("Qizil atirgil ellik bitta dona, 450 ming")
    assert fields.flowers == ["atirgul"]
    assert set(fields.uncertain) == {"flowers", "price"}  # a guessed flower, an unlabelled price
    assert ["flower", "atirgil", "atirgul", "low"] in fields.heard
    sure = extract("Qizil atirgul ellik bitta dona, narxi 450 ming so'm")
    assert sure.uncertain == []


def test_a_mishearing_is_learned() -> None:
    assert diff_corrections(HEARD, FIXED) == [Learned("atirgil", "atirgul", "flower")]


@pytest.mark.parametrize(
    ("heard", "corrected"),
    [
        ("Qizil atirgul 51 dona", "Qizil lola 51 dona"),  # a change of mind, not a mishearing
        ("Qizil atirgul 51 dona", "Oq atirgul 51 dona"),  # a different colour, also understood
        ("narxi besh yuz ming", "narxi to'rt yuz ming"),  # a different number, understood too
        ("bugun yetkazamiz", "ertaga yetkazib beramiz albatta tez"),  # prose, not a word
        (
            "Qizil atirgil ellik dona",
            "Bu guldasta juda chiroyli bo'ldi deb aytdi mijoz atirgul ellik dona",
        ),  # a rewritten description: the replaced span is too long
    ],
)
def test_nothing_else_is_learned(heard: str, corrected: str) -> None:
    assert diff_corrections(heard, corrected) == []


def test_a_garbled_price_phrase_is_learned_as_a_number() -> None:
    assert diff_corrections("narxi tort yuz elik ming", "narxi 450 ming") == [
        Learned("tort yuz elik", "450", "number")
    ]


def test_short_means_short() -> None:
    assert classify("atirgil", "atirgul") == Learned("atirgil", "atirgul", "flower")
    assert classify("a b c d", "atirgul") is None
    assert classify("x" * 41, "atirgul") is None


def test_learned_words_are_replaced_whole_words_only() -> None:
    text, applied = apply_learned("Atirgil, atirgillar, atirgil!", {"atirgil": "atirgul"})
    assert text == "atirgul, atirgillar, atirgul!"
    assert applied == ["Atirgil → atirgul", "atirgil → atirgul"]


def test_a_button_teaches_only_a_wrong_guess() -> None:
    heard = [["flower", "atirgil", "atirgul", "low"], ["colour", "oq", "oq", "high"]]
    assert from_button(heard, "flower", "atirgul", "pion") == Learned("atirgil", "pion", "flower")
    assert from_button(heard, "colour", "oq", "pushti") is None  # oq was heard clearly


# --- the bot ------------------------------------------------------------------------


@pytest_asyncio.fixture
async def world(db):
    factory = bound_session_factory(db)
    async with factory() as session:
        a = Shop(
            name="A",
            channel_id=-100927001,
            owner_telegram_ids=[OWNER],
            working_hours=DEFAULT_WORKING_HOURS,
        )
        b = Shop(
            name="B",
            channel_id=-100927002,
            owner_telegram_ids=[OTHER, OWNER],
            working_hours=DEFAULT_WORKING_HOURS,
        )
        session.add_all([a, b])
        await session.flush()
        session.add(ShopStaff(shop_id=a.id, telegram_id=CLERK, added_by=OWNER))
        await session.commit()
        ids = a.id, b.id
    recorder = RecordingSession()
    bot = Bot(token=TEST_TOKEN, session=recorder)
    dp = build_dispatcher(session_factory=factory, shop_id=ids[0], storage=MemoryStorage())
    yield factory, ids, bot, recorder, dp
    await bot.session.close()


async def heard(session, shop: int, text: str = HEARD, actor: int = OWNER) -> AnnouncementDraft:
    draft = await service.new_draft(session, shop_id=shop, actor=actor)
    draft.photos = ["photo-0"]
    await service.parse_description(session, draft, text)
    await session.flush()
    return draft


async def tap(dp, bot, draft, action, *, by=OWNER, value=""):
    data = AnnouncementCB(
        action=action, draft=draft.id, revision=draft.revision, value=value
    ).pack()
    await dp.feed_update(bot, callback_update(data, user_id=by))


async def say(dp, bot, text, *, by=OWNER, update_id=50):
    await dp.feed_update(bot, text_update(text, user_id=by, update_id=update_id))


async def opened(dp, bot, factory, shop, text=HEARD):
    """A draft in review, with the bot's FSM pointing at it (as after a photo)."""
    from aiogram.fsm.storage.base import StorageKey

    async with factory() as session:
        draft = await heard(session, shop, text)
        await session.commit()
    key = StorageKey(bot_id=bot.id, chat_id=OWNER, user_id=OWNER)
    await dp.storage.set_state(key, "Announcement:review")
    await dp.storage.set_data(key, {"announcement_id": draft.id})
    return draft


def last_review(recorder) -> SendMessage:
    reviews = [
        c
        for c in recorder.calls
        if isinstance(c, SendMessage)
        and c.reply_markup is not None
        and any(
            AnnouncementCB.unpack(b.callback_data).action == "confirm"
            for row in c.reply_markup.inline_keyboard
            for b in row
            if b.callback_data
        )
    ]
    assert reviews, "no confirmation screen was shown"
    return reviews[-1]


def nothing_published(recorder) -> bool:
    return not any(isinstance(c, SendPhoto | SendMediaGroup) for c in recorder.calls)


async def test_the_review_shows_heard_understood_unsure_and_the_post(world):
    factory, (a, _), bot, recorder, dp = world
    draft = await opened(dp, bot, factory, a)
    await tap(dp, bot, draft, "review")
    text = last_review(recorder).text
    assert "Eshitilgan matn" in text and "atirgil" in text  # what was heard
    assert "⚠ 🌹 Gullar: atirgul" in text  # a guess, marked
    assert "<blockquote>Atirgul guldastasi — 51 dona" in text  # the post as it would go
    assert nothing_published(recorder)


async def test_retext_extracts_again_learns_and_returns_to_the_review(world):
    factory, (a, b), bot, recorder, dp = world
    draft = await opened(dp, bot, factory, a)
    await tap(dp, bot, draft, "retext")
    await say(dp, bot, FIXED)
    review = last_review(recorder).text
    assert "Eslab qolindi: «atirgil» → «atirgul»" in review
    assert "⚠ 🌹" not in review
    async with factory() as session:
        row = await session.get(AnnouncementDraft, draft.id)
        assert row.status == "review" and Fields.from_data(row.fields).raw == FIXED
        # Next time, in THIS shop, the mishearing is fixed before the lexicon...
        again = await heard(session, a)
        assert Fields.from_data(again.fields).learned == ["atirgil → atirgul"]
        assert "flowers" not in Fields.from_data(again.fields).uncertain
        # ...and never in another shop.
        elsewhere = await heard(session, b)
        assert Fields.from_data(elsewhere.fields).learned == []
        assert "flowers" in Fields.from_data(elsewhere.fields).uncertain
    assert nothing_published(recorder)


async def test_a_field_edit_returns_to_the_review_with_the_new_value(world):
    factory, (a, _), bot, recorder, dp = world
    draft = await opened(dp, bot, factory, a)
    await tap(dp, bot, draft, "edit", value="price")
    await say(dp, bot, "500 ming")
    assert "💰 Narxi: 500000 so'm" in last_review(recorder).text
    assert "Narxi: 500 000 so'm" in last_review(recorder).text  # in the post preview too
    assert nothing_published(recorder)


async def test_replacing_a_guessed_flower_by_button_teaches_it(world):
    factory, (a, _), bot, recorder, dp = world
    draft = await opened(dp, bot, factory, a)
    await tap(dp, bot, draft, "flower", value="atirgul")  # remove the guess
    async with factory() as session:
        draft = await session.get(AnnouncementDraft, draft.id)
    await tap(dp, bot, draft, "flower", value="pion")  # add the right one
    async with factory() as session:
        rows = (await session.scalars(select(AnnouncementCorrection))).all()
        assert [(r.shop_id, r.heard, r.corrected) for r in rows] == [(a, "atirgil", "pion")]


async def test_description_is_editable(world):
    factory, (a, _), bot, recorder, dp = world
    draft = await opened(dp, bot, factory, a)
    await tap(dp, bot, draft, "edit", value="description")
    await say(dp, bot, "Yetkazib berish bepul")
    assert "✍ Tavsif: Yetkazib berish bepul" in last_review(recorder).text


async def test_revoice_prompts_for_a_new_voice_and_keeps_review(world):
    factory, (a, _), bot, recorder, dp = world
    draft = await opened(dp, bot, factory, a)
    await tap(dp, bot, draft, "revoice")
    prompts = [c.text for c in recorder.calls if isinstance(c, SendMessage)]
    assert "Yangi ovozli xabar" in prompts[-1]


@pytest.mark.parametrize("status", ["collecting", "review", "confirmed", "preview"])
async def test_cancel_keeps_nothing_at_every_step(world, status):
    factory, (a, _), bot, recorder, dp = world
    draft = await opened(dp, bot, factory, a)
    async with factory() as session:
        row = await session.get(AnnouncementDraft, draft.id)
        row.status = status
        await session.commit()
    await tap(dp, bot, draft, "cancel")
    async with factory() as session:
        assert await session.get(AnnouncementDraft, draft.id) is None
    assert (
        "Hech narsa saqlanmadi"
        in [c.text for c in recorder.calls if isinstance(c, SendMessage)][-1]
    )


@pytest.mark.parametrize("status", ["published", "publishing", "ambiguous"])
async def test_cancel_never_touches_a_post_that_went_out(world, status):
    factory, (a, _), bot, recorder, dp = world
    draft = await opened(dp, bot, factory, a)
    async with factory() as session:
        row = await session.get(AnnouncementDraft, draft.id)
        row.status = status
        await session.commit()
    await tap(dp, bot, draft, "cancel")
    async with factory() as session:
        row = await session.get(AnnouncementDraft, draft.id)
        assert row is not None, "a post that went out was deleted by cancel"
        assert row.status == status


@pytest.mark.parametrize("actor", [OTHER, CUSTOMER, CLERK])
@pytest.mark.parametrize("action", ["retext", "revoice", "cancel", "learned", "unlearn"])
async def test_new_actions_refuse_anyone_but_the_author(world, actor, action):
    factory, (a, _), bot, recorder, dp = world
    draft = await opened(dp, bot, factory, a)
    await tap(dp, bot, draft, action, by=actor, value="1")
    answers = [c for c in recorder.calls if isinstance(c, AnswerCallbackQuery)]
    assert answers and answers[-1].show_alert is True
    async with factory() as session:
        assert await session.get(AnnouncementDraft, draft.id) is not None


async def test_a_learned_entry_is_listed_and_deleting_it_stops_it(world):
    factory, (a, _), bot, recorder, dp = world
    async with factory() as session:
        await announcement_learning.remember(
            session, shop_id=a, taught_by=OWNER, items=[Learned("atirgil", "atirgul", "flower")]
        )
        await session.commit()
    draft = await opened(dp, bot, factory, a)
    await tap(dp, bot, draft, "learned")
    listing = [c for c in recorder.calls if isinstance(c, SendMessage)][-1]
    assert "«atirgil» → «atirgul»" in listing.text
    [first] = [
        b
        for row in listing.reply_markup.inline_keyboard
        for b in row
        if AnnouncementCB.unpack(b.callback_data).action == "unlearn"
    ]
    await dp.feed_update(bot, callback_update(first.callback_data, user_id=OWNER))
    async with factory() as session:
        assert (await session.scalars(select(AnnouncementCorrection))).all() == []
        assert Fields.from_data((await heard(session, a)).fields).learned == []


async def test_another_shops_entry_cannot_be_deleted(world):
    factory, (a, b), bot, recorder, dp = world
    async with factory() as session:
        await announcement_learning.remember(
            session, shop_id=b, taught_by=OTHER, items=[Learned("pionn", "pion", "flower")]
        )
        await session.commit()
        theirs = (await session.scalars(select(AnnouncementCorrection))).one()
    draft = await opened(dp, bot, factory, a)
    await tap(dp, bot, draft, "unlearn", value=str(theirs.id))
    async with factory() as session:
        assert await session.get(AnnouncementCorrection, theirs.id) is not None


async def test_the_table_is_capped_per_shop(world, monkeypatch):
    factory, (a, b), *_ = world
    monkeypatch.setattr(announcement_learning, "CORRECTIONS_CAP", 3)
    async with factory() as session:
        for i in range(5):
            await announcement_learning.remember(
                session,
                shop_id=a,
                taught_by=OWNER,
                items=[Learned(f"xato{i}", "atirgul", "flower")],
            )
        await announcement_learning.remember(
            session, shop_id=b, taught_by=OTHER, items=[Learned("pionn", "pion", "flower")]
        )
        stored = (
            await session.scalars(
                select(AnnouncementCorrection.heard).where(AnnouncementCorrection.shop_id == a)
            )
        ).all()
        assert sorted(stored) == ["xato2", "xato3", "xato4"]  # the oldest DELETED, not hidden
        assert await announcement_learning.learned_for(session, b) == {"pionn": "pion"}
