"""A Ha/Yo'q page as a real date invitation (CP17 Part 1).

The creator offers places and times; after Ha the recipient picks one of each;
the creator gets EXACTLY ONE message stating precisely what was chosen -- or,
if the recipient said Ha and left, a plain "nothing chosen yet" and then one
single follow-up when they do choose. Every message once, however often the
task runs.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from aiogram import Bot
from aiogram.methods import SendMessage
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
from tests.bot_harness import RecordingSession, bound_session_factory
from tests.share_pages_harness import ShopBot
from tests.test_share_pages_service import make_customer, make_shop, yesno

from gulbot.bot.callbacks import (
    InviteDayCB,
    InviteHourCB,
    InviteMinuteCB,
    InviteMonthCB,
    PageChoiceCB,
    PageConfirmCB,
    PageLangCB,
    PageMenuCB,
    PageQuestionCB,
    PageTemplateCB,
    PlanCB,
)
from gulbot.bot.registry import BotRegistry
from gulbot.i18n.catalog import CATALOG
from gulbot.sending import page_notify
from gulbot.services import share_pages
from gulbot.services.share_pages import CHOICE_WAIT, ChoiceRefused, EditRefused, InvalidDraft
from gulbot.web.app import CHOICE_CHECK_DELAY, _option_id, build_app

pytestmark = pytest.mark.infra

TASHKENT = ZoneInfo("Asia/Tashkent")


def evening(days: int, hour: int = 19) -> datetime:
    local = datetime.now(TASHKENT).replace(hour=hour, minute=0, second=0, microsecond=0)
    return (local + timedelta(days=days)).astimezone(UTC)


PLACES = ("Kino", "Bog'da sayr")
SLOTS = (evening(3), evening(5, 20))


@pytest.fixture
async def session(db: AsyncConnection) -> AsyncSession:
    return bound_session_factory(db)()


async def plan_page(
    session: AsyncSession, db: AsyncConnection, *, user: int = 901, notify: bool = True
) -> tuple[Any, int, int]:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, user)
    page = await share_pages.create_page(
        session,
        shop_id=shop,
        customer_id=customer,
        bot_username="lola_bot",
        draft=yesno(
            question_preset="date",
            question="Uchrashuvga chiqamizmi?",
            places=PLACES,
            slots=SLOTS,
            notify_creator=notify,
        ),
    )
    return page, shop, customer


async def ids(session: AsyncSession, page: Any) -> tuple[list[int], list[int]]:
    places, slots = await share_pages.plan_of(session, page_id=page.id)
    return [p.id for p in places], [s.id for s in slots]


async def raised(call: Any) -> BaseException:
    """What the SERVICE raised -- asserted by type in the test, so a database
    CHECK firing behind a missing guard is a failed assertion, not a pass."""
    try:
        await call
    except Exception as error:  # noqa: BLE001 - the type is the assertion
        return error
    raise AssertionError("nothing was refused")


# --- making the plan ---------------------------------------------------------------------


async def test_a_plan_is_stored_in_the_creators_order(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, _, _ = await plan_page(session, db)
    places, slots = await share_pages.plan_of(session, page_id=page.id)
    assert [p.place for p in places] == list(PLACES)
    assert [s.slot_at for s in slots] == sorted(SLOTS)
    assert await share_pages.has_plan(session, page_id=page.id)


@pytest.mark.parametrize(
    ("places", "slots"),
    [
        (("Kino",), ()),  # places without times
        ((), (evening(2),)),  # times without places
        (tuple(f"P{n}" for n in range(6)), (evening(2),)),  # six places
        (("Kino",), tuple(evening(d) for d in range(2, 8))),  # six times
        (("Kino", "Kino"), (evening(2),)),  # a repeated place
        (("Kino",), (evening(2), evening(2))),  # a repeated time
        (("  ",), (evening(2),)),  # an empty place
        (("Kino",), (datetime.now(UTC) - timedelta(hours=1),)),  # a past time
        (("Kino",), (evening(400),)),  # beyond the window
    ],
)
async def test_a_plan_the_pickers_could_not_make_is_refused(
    db: AsyncConnection, session: AsyncSession, places: tuple[str, ...], slots: tuple[datetime, ...]
) -> None:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 902)
    error = await raised(
        share_pages.create_page(
            session,
            shop_id=shop,
            customer_id=customer,
            bot_username="b",
            draft=yesno(places=places, slots=slots),
        )
    )
    assert isinstance(error, InvalidDraft), repr(error)


# --- the recipient's choice ------------------------------------------------------------


async def test_the_first_choice_is_kept(db: AsyncConnection, session: AsyncSession) -> None:
    page, _, _ = await plan_page(session, db)
    place_ids, slot_ids = await ids(session, page)
    with pytest.raises(ChoiceRefused):  # not before Ha
        await share_pages.choose(session, page.token, place_id=place_ids[0], slot_id=slot_ids[0])
    await share_pages.answer_yes(session, page.token)
    first = await share_pages.choose(
        session, page.token, place_id=place_ids[0], slot_id=slot_ids[1]
    )
    again = await share_pages.choose(
        session, page.token, place_id=place_ids[1], slot_id=slot_ids[0]
    )
    assert first.first and not again.first
    assert (again.place, again.slot_at) == ("Kino", sorted(SLOTS)[1])


async def test_options_from_another_page_or_kind_are_refused(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, _, _ = await plan_page(session, db, user=903)
    other, _, _ = await plan_page(session, db, user=904)
    await share_pages.answer_yes(session, page.token)
    mine_places, mine_slots = await ids(session, page)
    their_places, their_slots = await ids(session, other)
    for place, slot in (
        (their_places[0], mine_slots[0]),  # another page's place
        (mine_places[0], their_slots[0]),  # another page's time
        (mine_slots[0], mine_places[0]),  # the kinds swapped
        (mine_slots[0], mine_slots[1]),  # a time offered as the place
        (mine_places[0], mine_places[1]),  # a place offered as the time
        (999_999_999, mine_slots[0]),
    ):
        with pytest.raises(ChoiceRefused, match="options"):
            await share_pages.choose(session, page.token, place_id=place, slot_id=slot)
    chosen = await db.scalar(
        text("SELECT chosen_at FROM share_pages WHERE id = :i"), {"i": page.id}
    )
    assert chosen is None


async def test_nothing_can_be_chosen_before_ha(db: AsyncConnection, session: AsyncSession) -> None:
    page, _, _ = await plan_page(session, db, user=905)
    places, slots = await ids(session, page)
    error = await raised(
        share_pages.choose(session, page.token, place_id=places[0], slot_id=slots[0])
    )
    assert isinstance(error, ChoiceRefused) and error.reason == "page", repr(error)


async def test_the_plan_is_the_creators_own_and_locks_with_the_answer(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, shop, customer = await plan_page(session, db, user=906)
    other_shop = await make_shop(db, "B")
    stranger = await make_customer(db, other_shop, 906)
    neighbour = await make_customer(db, shop, 907)
    # (other shop, the owner's id): what only the shop filter stops.
    for s, c in ((other_shop, stranger), (shop, neighbour), (other_shop, customer)):
        with pytest.raises(EditRefused, match="gone"):
            await share_pages.set_plan(
                session, shop_id=s, customer_id=c, page_id=page.id, places=("X",), slots=SLOTS
            )
    edited = await share_pages.set_plan(
        session, shop_id=shop, customer_id=customer, page_id=page.id, places=("Teatr",), slots=SLOTS
    )
    assert [p.place for p in (await share_pages.plan_of(session, page_id=edited.id))[0]] == [
        "Teatr"
    ]
    await share_pages.answer_yes(session, page.token)
    with pytest.raises(EditRefused, match="locked"):
        await share_pages.set_plan(
            session, shop_id=shop, customer_id=customer, page_id=page.id, places=("Y",), slots=SLOTS
        )
    assert [p.place for p in (await share_pages.plan_of(session, page_id=page.id))[0]] == ["Teatr"]


async def test_deleting_the_page_deletes_its_plan(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, shop, customer = await plan_page(session, db, user=908)
    await share_pages.delete_page(session, shop_id=shop, customer_id=customer, page_id=page.id)
    left = await db.scalar(
        text("SELECT count(*) FROM share_page_options WHERE page_id = :p"), {"p": page.id}
    )
    assert left == 0


@pytest.mark.parametrize("value", [True, False, "1", 1.0, None, [1]])
def test_an_option_id_is_a_plain_integer_only(value: object) -> None:
    from aiohttp import web

    with pytest.raises(web.HTTPBadRequest):
        _option_id(value)
    assert _option_id(7) == 7


# --- the creator's messages --------------------------------------------------------------


class Bots:
    def __init__(self) -> None:
        self.session = RecordingSession()

    def registry(self) -> BotRegistry:
        return BotRegistry(token_for=lambda _shop: "111111:" + "A" * 35, bot_factory=self.bot)

    def bot(self, token: str | None) -> Bot:
        return Bot(token=token or "x", session=self.session)

    def sent(self) -> list[str]:
        return [c.text for c in self.session.calls if isinstance(c, SendMessage)]


@pytest.fixture
def bots(monkeypatch: pytest.MonkeyPatch) -> Bots:
    recorded = Bots()

    async def registry_for(_session: Any, **_kw: Any) -> BotRegistry:
        return recorded.registry()

    monkeypatch.setattr(page_notify, "registry_for", registry_for)
    return recorded


async def notify(db: AsyncConnection, page: Any, now: datetime | None = None) -> str:
    return await page_notify.notify_page_answer(
        page.id, session_factory=bound_session_factory(db), now=now
    )


async def test_a_choice_made_in_time_gives_one_message_with_the_choice(
    db: AsyncConnection, session: AsyncSession, bots: Bots
) -> None:
    page, _, _ = await plan_page(session, db)
    await share_pages.answer_yes(session, page.token)
    await session.commit()
    assert await notify(db, page) == page_notify.OUTCOME_NOTHING  # the recipient is still choosing
    place_ids, slot_ids = await ids(session, page)
    await share_pages.choose(session, page.token, place_id=place_ids[0], slot_id=slot_ids[0])
    await session.commit()
    assert await notify(db, page) == page_notify.OUTCOME_SENT
    for _ in range(3):  # the delayed check, a retry, a second worker
        assert (
            await notify(db, page, now=datetime.now(UTC) + CHOICE_WAIT * 2)
            == page_notify.OUTCOME_NOTHING
        )
    [message] = bots.sent()
    when = page_notify.when_text(sorted(SLOTS)[0], "uz", "Asia/Tashkent")
    assert message.startswith(f"🎉 Ha! Joy: Kino. Sana: {when}.")


async def test_ha_without_a_choice_says_so_plainly_then_follows_up_once(
    db: AsyncConnection, session: AsyncSession, bots: Bots
) -> None:
    page, _, _ = await plan_page(session, db)
    await share_pages.answer_yes(session, page.token)
    await session.commit()
    later = datetime.now(UTC) + CHOICE_WAIT + timedelta(seconds=1)
    assert await notify(db, page, now=later) == page_notify.OUTCOME_SENT
    assert await notify(db, page, now=later) == page_notify.OUTCOME_NOTHING
    place_ids, slot_ids = await ids(session, page)
    await share_pages.choose(session, page.token, place_id=place_ids[1], slot_id=slot_ids[1])
    await session.commit()
    assert await notify(db, page) == page_notify.OUTCOME_SENT
    assert await notify(db, page) == page_notify.OUTCOME_NOTHING
    first, follow_up = bots.sent()
    assert "hali tanlashmadi" in first
    assert follow_up.startswith("📍 Joy va vaqt tanlandi! Joy: Bog'da sayr.")


async def test_without_a_plan_ha_is_still_one_message(
    db: AsyncConnection, session: AsyncSession, bots: Bots
) -> None:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 905)
    page = await share_pages.create_page(
        session, shop_id=shop, customer_id=customer, bot_username="b", draft=yesno()
    )
    await share_pages.answer_yes(session, page.token)
    await session.commit()
    assert await notify(db, page) == page_notify.OUTCOME_SENT
    assert await notify(db, page) == page_notify.OUTCOME_NOTHING
    assert len(bots.sent()) == 1


@pytest.mark.parametrize(
    ("lang", "expected"),
    [("uz", "12-oktabr, 19:00"), ("ru", "12 октября, 19:00"), ("en", "12 October, 19:00")],
)
def test_the_date_reads_naturally_in_the_creators_language(lang: str, expected: str) -> None:
    moment = datetime(2026, 10, 12, 19, 0, tzinfo=TASHKENT)
    assert page_notify.when_text(moment, lang, "Asia/Tashkent") == expected


# --- the public page ------------------------------------------------------------------------

JSON_HEADERS = {"X-Requested-With": "gulbot", "Content-Type": "application/json"}


async def test_the_page_offers_the_plan_after_ha_and_queues_the_checks(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, _, _ = await plan_page(session, db)
    await session.commit()
    queued: list[tuple[int, float]] = []

    async def queue(page_id: int, delay: float) -> None:
        queued.append((page_id, delay))

    app = build_app(
        session_factory=bound_session_factory(db),
        notify=queue,
        public_base_url="http://127.0.0.1:8088",
    )
    place_ids, slot_ids = await ids(session, page)
    async with TestClient(TestServer(app)) as client:
        html = await (await client.get(f"/p/{page.token}")).text()
        assert 'data-plan="1"' in html and "Kino" in html and "Bog&#39;da sayr" in html
        assert (
            await client.post(f"/p/{page.token}/yes", data="{}", headers=JSON_HEADERS)
        ).status == 200
        assert queued == [(page.id, 0), (page.id, CHOICE_CHECK_DELAY)]
        crafted = await client.post(
            f"/p/{page.token}/choose",
            data=json.dumps({"place": slot_ids[0], "slot": place_ids[0]}),
            headers=JSON_HEADERS,
        )
        assert crafted.status == 400
        response = await client.post(
            f"/p/{page.token}/choose",
            data=json.dumps({"place": place_ids[0], "slot": slot_ids[0]}),
            headers=JSON_HEADERS,
        )
        assert response.status == 200
        body = await response.json()
        assert body["line"].startswith("Joy: Kino · Vaqt: ")
        assert queued[-1] == (page.id, 0)
        refused = await client.post(
            f"/p/{page.token}/choose", data='{"place": "1", "slot": 2}', headers=JSON_HEADERS
        )
        assert refused.status == 400
        no_header = await client.post(f"/p/{page.token}/choose", json={"place": 1, "slot": 2})
        assert no_header.status == 403


# --- through the bot ------------------------------------------------------------------------


async def test_a_date_invitation_end_to_end_in_the_bot(db: AsyncConnection) -> None:
    bot = ShopBot(db, await make_shop(db, "Lola"), bot_id=930_001, username="lola_bot")
    user = 930
    target = (datetime.now(TASHKENT) + timedelta(days=10)).date()
    await bot.say(CATALOG["btn.menu.pages"]["uz"], user=user)
    await bot.tap(PageMenuCB(action="yesno").pack(), user=user)
    await bot.tap(PageLangCB(lang="uz").pack(), user=user)
    await bot.tap(PageQuestionCB(preset="date").pack(), user=user)
    await bot.tap(PlanCB(action="add").pack(), user=user)
    await bot.say("Kino", user=user)
    await bot.tap(PlanCB(action="more_place").pack(), user=user)
    await bot.say("Bog'da sayr", user=user)
    await bot.tap(PlanCB(action="places_done").pack(), user=user)
    for hour in (19, 20):
        await bot.tap(InviteMonthCB(year=target.year, month=target.month).pack(), user=user)
        await bot.tap(InviteDayCB(day=target.day).pack(), user=user)
        await bot.tap(InviteHourCB(hour=hour).pack(), user=user)
        await bot.tap(InviteMinuteCB(minute=0).pack(), user=user)
        if hour == 19:
            await bot.tap(PlanCB(action="more_slot").pack(), user=user)
    await bot.tap(PlanCB(action="slots_done").pack(), user=user)
    await bot.tap(PageTemplateCB(template="romantik").pack(), user=user)
    await bot.tap(PageChoiceCB(field="notify", value="yes").pack(), user=user)
    assert any("📍 Reja: Kino, Bog'da sayr" in body for body in bot.texts())
    await bot.tap(PageConfirmCB(action="create").pack(), user=user)
    rows = (
        await db.execute(
            text(
                "SELECT o.kind, o.place, o.slot_at FROM share_page_options o "
                "JOIN share_pages p ON p.id = o.page_id WHERE p.shop_id = :s "
                "ORDER BY o.kind, o.position"
            ),
            {"s": bot.shop_id},
        )
    ).all()
    assert [(r[0], r[1]) for r in rows] == [
        ("place", "Kino"),
        ("place", "Bog'da sayr"),
        ("slot", None),
        ("slot", None),
    ]
    assert [r[2].astimezone(TASHKENT).hour for r in rows[2:]] == [19, 20]


async def test_a_crafted_plan_button_out_of_step_changes_nothing(db: AsyncConnection) -> None:
    bot = ShopBot(db, await make_shop(db, "Lola"), bot_id=930_002, username="lola_bot")
    user = 931
    await bot.say(CATALOG["btn.menu.pages"]["uz"], user=user)
    await bot.tap(PageMenuCB(action="yesno").pack(), user=user)
    await bot.tap(PageLangCB(lang="uz").pack(), user=user)
    await bot.tap(PageQuestionCB(preset="date").pack(), user=user)
    # "slots done" with no places and no times, before the plan has started:
    await bot.tap(PlanCB(action="slots_done").pack(), user=user)
    await bot.tap(PlanCB(action="places_done").pack(), user=user)
    context = bot.dispatcher.fsm.get_context(bot=bot.bot, chat_id=user, user_id=user)
    assert await context.get_state() == "YesNoPage:asking_plan"
