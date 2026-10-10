"""Holiday campaigns (CP20).

The owner's brief asked for three proofs, and they come first:

  * NO OPT-IN, NO MESSAGE. A shop running a holiday reaches only customers who
    turned greetings on themselves; the default is off.
  * OPTING OUT STOPS FUTURE ROWS -- at once, not at the next nightly run.
  * THE CAP HOLDS on a week with a holiday and personal dates: a holiday is one
    more date in the same plan, so the 4-per-7-days cap counts both.

Then the rest of what makes it safe to run: the merge window joins a holiday
with a nearby birthday into one message; a lunar holiday is never guessed;
switching a holiday off drops what it planned; one shop's choice or one
customer's consent never speaks for another shop; the message names the
holiday and offers the holiday's own order button; the switches in /shop and
the dates in /admin are audited; the database refuses a row that is neither a
person's date nor a holiday.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import pytest
import pytest_asyncio
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import EditMessageText, SendMessage
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker
from tests.bot_harness import bound_session_factory, callback_update, feed, make_bot, text_update

from gulbot.bot.callbacks import HolidayOptCB, HolidayOrderCB, OrderStartCB
from gulbot.bot.factory import build_dispatcher
from gulbot.holidays import BY_KEY
from gulbot.i18n import t
from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.scheduling.occurrences import (
    TASHKENT,
    OccasionSpec,
    PlannedNotification,
    is_within_send_window,
    plan_notifications,
)
from gulbot.sending.attach import attach_bouquet
from gulbot.sending.dispatcher import run_tick
from gulbot.sending.render import render_reminder
from gulbot.sending.transport import SendResult
from gulbot.services import holiday_campaigns
from gulbot.services.materializer import materialize_shop

pytestmark = pytest.mark.infra

#: Two weeks before 8 March: inside the 45-day horizon, before any -7 offset.
NOW = datetime(2027, 2, 22, 3, 0, tzinfo=UTC)
WOMENS_DAY = BY_KEY["womens_day"]


# --- the planner (pure) ---------------------------------------------------------


def _messages(planned: Sequence[PlannedNotification]) -> dict[str, list[PlannedNotification]]:
    by_key: dict[str, list[PlannedNotification]] = {}
    for row in planned:
        by_key.setdefault(row.merge_key, []).append(row)
    return by_key


def _holiday_spec() -> OccasionSpec:
    return OccasionSpec(occasion_id=WOMENS_DAY.spec_id, month=3, day=8)


def test_a_holiday_two_days_from_a_birthday_is_one_message() -> None:
    planned = plan_notifications(
        [OccasionSpec(occasion_id=7, month=3, day=6), _holiday_spec()], now_utc=NOW
    )
    for key, rows in _messages(planned).items():
        assert {r.occasion_id for r in rows} == {7, WOMENS_DAY.spec_id}, key


def test_the_weekly_cap_counts_holidays_and_personal_dates_together() -> None:
    specs = [
        OccasionSpec(occasion_id=1, month=3, day=2),
        OccasionSpec(occasion_id=2, month=3, day=5),
        _holiday_spec(),
        OccasionSpec(occasion_id=3, month=3, day=11),
    ]
    planned = plan_notifications(specs, now_utc=NOW, weekly_cap=4)
    messages = _messages(planned)
    due = sorted(rows[0].due_at_utc for rows in messages.values())
    for moment in due:
        in_window = [d for d in due if moment - timedelta(days=7) < d <= moment]
        assert len(in_window) <= 4, (moment, in_window)
    # It bit: without the cap there are more messages than with it.
    uncapped = _messages(plan_notifications(specs, now_utc=NOW, weekly_cap=100))
    assert len(uncapped) > len(messages)
    # ...and the day-of reminder for the holiday survived it (urgency first).
    assert any(
        r.offset_days == 0 and r.occasion_id == WOMENS_DAY.spec_id
        for rows in messages.values()
        for r in rows
    )


def test_a_holiday_reminder_is_inside_the_send_window() -> None:
    planned = plan_notifications([_holiday_spec()], now_utc=NOW, send_time=time(7, 0))
    assert planned and all(is_within_send_window(r.due_at_utc) for r in planned)


def test_a_lunar_holiday_is_planned_only_on_a_date_someone_entered() -> None:
    assert holiday_campaigns.holiday_specs({"ramazon_hayit"}, {}) == []
    (spec,) = holiday_campaigns.holiday_specs(
        {"ramazon_hayit"}, {"ramazon_hayit": (date(2027, 3, 9),)}
    )
    planned = plan_notifications([spec], now_utc=NOW, offsets=(0,))
    assert [r.occurrence_date for r in planned] == [date(2027, 3, 9)]


def test_only_the_holidays_a_shop_runs_are_planned() -> None:
    specs = holiday_campaigns.holiday_specs({"navruz"}, {})
    assert [s.occasion_id for s in specs] == [BY_KEY["navruz"].spec_id]


# --- the outbox ---------------------------------------------------------------------


async def _shop(db: AsyncConnection, name: str = "S") -> int:
    return int(
        await db.scalar(
            text(
                "INSERT INTO shops (name, working_hours, owner_telegram_ids) "
                "VALUES (:n, CAST(:wh AS jsonb), ARRAY[CAST(670001 AS bigint)]) RETURNING id"
            ),
            {"n": name, "wh": json.dumps(DEFAULT_WORKING_HOURS)},
        )
    )


async def _customer(db: AsyncConnection, shop: int, tg: int) -> int:
    return int(
        await db.scalar(
            text("INSERT INTO customers (shop_id, telegram_user_id) VALUES (:s, :t) RETURNING id"),
            {"s": shop, "t": tg},
        )
    )


async def _birthday(db: AsyncConnection, shop: int, customer: int, month: int, day: int) -> None:
    recipient = await db.scalar(
        text(
            "INSERT INTO recipients (shop_id, customer_id, label, type) "
            "VALUES (:s, :c, 'Onam', 'mother') RETURNING id"
        ),
        {"s": shop, "c": customer},
    )
    await db.execute(
        text(
            "INSERT INTO occasions (shop_id, customer_id, recipient_id, label, type, kind, "
            " month, day) VALUES (:s, :c, :r, 'Onam', 'mother', 'birthday', :m, :d)"
        ),
        {"s": shop, "c": customer, "r": recipient, "m": month, "d": day},
    )


class World:
    def __init__(self, db: AsyncConnection, shop: int, customer: int) -> None:
        self.db, self.shop, self.customer = db, shop, customer
        self.sessions: async_sessionmaker[AsyncSession] = bound_session_factory(db)

    async def run(self, fn: Any, **kwargs: Any) -> Any:
        async with self.sessions() as session:
            result = await fn(session, **kwargs)
            await session.commit()
        return result

    async def materialize(self, shop: int | None = None, now: datetime = NOW) -> Any:
        return await self.run(materialize_shop, shop_id=shop or self.shop, now_utc=now)

    async def run_holiday(self, holiday: str = "womens_day", on: bool = True) -> None:
        await self.run(
            holiday_campaigns.set_shop_holiday,
            shop_id=self.shop,
            holiday=holiday,
            on=on,
            owner_id=670001,
        )

    async def opt(self, granted: bool, customer: int | None = None, shop: int | None = None) -> int:
        return int(
            await self.run(
                holiday_campaigns.set_opt_in,
                shop_id=shop or self.shop,
                customer_id=customer or self.customer,
                granted=granted,
            )
        )

    async def holiday_rows(self, shop: int | None = None) -> list[Any]:
        found = await self.db.execute(
            text(
                "SELECT customer_id, holiday, occasion_id, offset_days, state, due_at_utc "
                "FROM scheduled_notifications WHERE shop_id = :s AND holiday IS NOT NULL "
                "ORDER BY due_at_utc"
            ),
            {"s": shop or self.shop},
        )
        return list(found)


@pytest_asyncio.fixture
async def world(db: AsyncConnection) -> World:
    shop = await _shop(db)
    return World(db, shop, await _customer(db, shop, 680_001))


async def test_with_no_opt_in_a_shops_holiday_reaches_nobody(world: World) -> None:
    await world.run_holiday()
    await world.materialize()
    assert await world.holiday_rows() == []


async def test_a_customer_with_dates_but_no_opt_in_gets_only_their_dates(world: World) -> None:
    """The customer IS planned -- for their own birthday -- so the opt-in is
    the only thing keeping the shop's holiday out of their plan."""
    await _birthday(world.db, world.shop, world.customer, 3, 15)
    await world.run_holiday()
    result = await world.materialize()
    # Exactly the birthday's three offsets: nothing for the holiday was even
    # planned -- not planned and then pruned in the same run.
    assert (result.inserted, result.pruned_holidays) == (3, 0)
    assert await world.holiday_rows() == []


async def test_greetings_are_off_until_the_customer_turns_them_on(world: World) -> None:
    async with world.sessions() as session:
        assert not await holiday_campaigns.opted_in(
            session, shop_id=world.shop, customer_id=world.customer
        )


async def test_an_opted_in_customer_gets_the_holiday_in_the_send_window(world: World) -> None:
    await world.run_holiday()
    await world.opt(True)
    await world.materialize()
    found = await world.holiday_rows()
    assert {r.offset_days for r in found} == {-7, -1, 0}
    assert all(r.holiday == "womens_day" and r.occasion_id is None for r in found)
    assert all(is_within_send_window(r.due_at_utc) for r in found)


async def test_materializing_twice_writes_nothing_new(world: World) -> None:
    await world.run_holiday()
    await world.opt(True)
    first = await world.materialize()
    second = await world.materialize()
    assert first.inserted == 3 and second.inserted == 0
    assert len(await world.holiday_rows()) == 3


async def test_opting_out_drops_pending_rows_at_once_and_plans_no_more(world: World) -> None:
    await world.run_holiday()
    await world.opt(True)
    await world.materialize()
    dropped = await world.opt(False)
    assert dropped == 3
    assert await world.holiday_rows() == []
    await world.materialize()
    assert await world.holiday_rows() == []


async def test_opting_out_keeps_what_was_already_sent(world: World) -> None:
    await world.run_holiday()
    await world.opt(True)
    await world.materialize()
    await world.db.execute(
        text(
            "UPDATE scheduled_notifications SET state = 'sent', sent_at = now() "
            "WHERE holiday IS NOT NULL AND offset_days = -7"
        )
    )
    await world.opt(False)
    assert [(r.offset_days, r.state) for r in await world.holiday_rows()] == [(-7, "sent")]


async def test_switching_a_holiday_off_drops_what_it_planned(world: World) -> None:
    await world.run_holiday()
    await world.run_holiday("navruz")
    await world.opt(True)
    await world.materialize(now=datetime(2027, 3, 1, 3, 0, tzinfo=UTC))
    await world.run_holiday("womens_day", on=False)
    assert {r.holiday for r in await world.holiday_rows()} == {"navruz"}
    await world.materialize(now=datetime(2027, 3, 1, 3, 0, tzinfo=UTC))
    assert {r.holiday for r in await world.holiday_rows()} == {"navruz"}


async def test_the_nightly_run_prunes_a_holiday_switched_off_behind_its_back(world: World) -> None:
    """The backstop: a shop_holidays row removed without the service."""
    await world.run_holiday()
    await world.opt(True)
    await world.materialize()
    await world.db.execute(text("DELETE FROM shop_holidays WHERE shop_id = :s"), {"s": world.shop})
    result = await world.materialize()
    assert result.pruned_holidays == 3
    assert await world.holiday_rows() == []


async def test_the_cap_holds_on_a_week_with_a_holiday_and_personal_dates(world: World) -> None:
    await _birthday(world.db, world.shop, world.customer, 3, 2)
    await _birthday(world.db, world.shop, world.customer, 3, 5)
    await _birthday(world.db, world.shop, world.customer, 3, 11)
    await world.run_holiday()
    await world.opt(True)
    await world.materialize()
    found = await world.db.execute(
        text(
            "SELECT DISTINCT merge_key, due_at_utc FROM scheduled_notifications "
            "WHERE customer_id = :c ORDER BY due_at_utc"
        ),
        {"c": world.customer},
    )
    due = [row.due_at_utc for row in found]
    assert due, "nothing was planned"
    for moment in due:
        assert len([d for d in due if moment - timedelta(days=7) < d <= moment]) <= 4
    assert any(r.offset_days == 0 for r in await world.holiday_rows())


async def test_a_lunar_date_entered_late_is_planned_and_a_correction_replans(
    world: World,
) -> None:
    await world.run_holiday("ramazon_hayit")
    await world.opt(True)
    await world.materialize()
    assert await world.holiday_rows() == []  # no date, no guess
    await world.run(
        holiday_campaigns.set_lunar_date,
        holiday="ramazon_hayit",
        falls_on=date(2027, 3, 10),
        admin=1,
    )
    await world.materialize()
    first = {r.due_at_utc.astimezone(TASHKENT).date() for r in await world.holiday_rows()}
    assert date(2027, 3, 10) in first
    await world.run(
        holiday_campaigns.set_lunar_date,
        holiday="ramazon_hayit",
        falls_on=date(2027, 3, 12),
        admin=1,
    )
    assert await world.holiday_rows() == []  # the old plan is gone at once
    await world.materialize()
    second = {r.due_at_utc.astimezone(TASHKENT).date() for r in await world.holiday_rows()}
    assert date(2027, 3, 12) in second and date(2027, 3, 10) not in second


async def test_a_fixed_holiday_cannot_be_given_a_lunar_date(world: World) -> None:
    with pytest.raises(holiday_campaigns.UnknownHoliday):
        await world.run(
            holiday_campaigns.set_lunar_date, holiday="navruz", falls_on=date(2027, 3, 1), admin=1
        )


# --- one shop never speaks for another ----------------------------------------------


async def test_a_holiday_one_shop_runs_does_nothing_at_another(world: World) -> None:
    other = await _shop(world.db, "B")
    theirs = await _customer(world.db, other, 680_001)  # the same person, B's customer
    await world.run_holiday()
    await world.opt(True, customer=theirs, shop=other)  # opted in at B, which runs nothing
    await world.materialize(other)
    assert await world.holiday_rows(other) == []


async def test_consent_at_one_shop_is_not_consent_at_another(world: World) -> None:
    other = await _shop(world.db, "B")
    theirs = await _customer(world.db, other, 680_001)
    await world.run(
        holiday_campaigns.set_shop_holiday,
        shop_id=other,
        holiday="womens_day",
        on=True,
        owner_id=670001,
    )
    await world.opt(True)  # at A only
    await world.materialize(other)
    assert await world.holiday_rows(other) == []
    async with world.sessions() as session:
        assert await holiday_campaigns.opted_in_customers(session, shop_id=other) == set()
        assert not await holiday_campaigns.opted_in(session, shop_id=other, customer_id=theirs)


async def test_switching_a_holiday_off_at_one_shop_leaves_another_shops_plan(
    world: World,
) -> None:
    other = await _shop(world.db, "B")
    theirs = await _customer(world.db, other, 680_002)
    for shop, customer in ((world.shop, world.customer), (other, theirs)):
        await world.run(
            holiday_campaigns.set_shop_holiday,
            shop_id=shop,
            holiday="womens_day",
            on=True,
            owner_id=670001,
        )
        await world.opt(True, customer=customer, shop=shop)
        await world.materialize(shop)
    await world.run_holiday(on=False)
    assert await world.holiday_rows() == []
    assert len(await world.holiday_rows(other)) == 3


# --- the message ----------------------------------------------------------------------


class RecordingTransport:
    def __init__(self) -> None:
        self.texts: list[str] = []
        self.photos: list[str] = []
        self.markups: list[Any] = []

    async def send_text(
        self, *, chat_id: int, text: str, reply_markup: object = None
    ) -> SendResult:
        self.texts.append(text)
        return SendResult.sent(len(self.texts) + len(self.photos))

    async def send_photo(
        self, *, chat_id: int, file_id: str, caption: str, reply_markup: object = None
    ) -> SendResult:
        self.photos.append(caption)
        self.markups.append(reply_markup)
        return SendResult.sent(len(self.texts) + len(self.photos))


async def _due_at(world: World, *, offset: int) -> datetime:
    """When the holiday row at this offset is due -- read, not assumed: the
    send time comes from the customer's and the shop's settings."""
    due = await world.db.scalar(
        text(
            "SELECT min(due_at_utc) FROM scheduled_notifications "
            "WHERE customer_id = :c AND holiday IS NOT NULL AND offset_days = :o"
        ),
        {"c": world.customer, "o": offset},
    )
    assert due is not None, "nothing planned at that offset"
    return due  # type: ignore[no-any-return]


async def _tick(world: World, now: datetime) -> RecordingTransport:
    """Beat until nothing is due, as the every-minute tick would: an earlier
    offset that went stale is expired by one pass and the due one is sent by
    the next."""
    transport = RecordingTransport()
    results = []
    for _ in range(3):
        async with world.sessions() as session:

            async def attach(group):  # type: ignore[no-untyped-def]
                return await attach_bouquet(session, group, render=render_reminder)

            result = await run_tick(
                session, transport=transport, render=render_reminder, now_utc=now, attach=attach
            )
            await session.commit()
        results.append(result)
        if result.groups == 0:
            break
    transport.result = results  # type: ignore[attr-defined]
    return transport


async def _product(world: World) -> int:
    return int(
        await world.db.scalar(
            text(
                "INSERT INTO products (shop_id, name, telegram_file_id, source, "
                " channel_message_id, price_uzs, price_confidence, finalized_at) "
                "VALUES (:s, 'Lola', 'f-lola', 'channel', 9, 300000, 'high', now()) RETURNING id"
            ),
            {"s": world.shop},
        )
    )


async def test_the_reminder_names_the_holiday_and_offers_its_own_button(world: World) -> None:
    product = await _product(world)
    await world.run_holiday()
    await world.opt(True)
    await world.materialize()
    day_before = await _due_at(world, offset=-1)
    transport = await _tick(world, day_before)
    assert len(transport.photos) == 1, transport.result  # type: ignore[attr-defined]
    (caption,) = transport.photos
    assert t("holiday.womens_day", "uz") in caption
    (markup,) = transport.markups
    (button,) = markup.inline_keyboard[0]
    assert button.callback_data == HolidayOrderCB(product_id=product).pack()


async def test_a_holiday_next_to_a_birthday_goes_out_as_one_message(world: World) -> None:
    await _birthday(world.db, world.shop, world.customer, 3, 7)
    await world.run_holiday()
    await world.opt(True)
    await world.materialize()
    day_before = await _due_at(world, offset=-1)
    transport = await _tick(world, day_before)
    assert len(transport.texts) == 1, transport.result  # type: ignore[attr-defined]
    (text_,) = transport.texts  # no product: bare text, one message
    assert t("holiday.womens_day", "uz") in text_ and "Onang" in text_


async def test_a_birthday_that_comes_first_keeps_the_persons_button(world: World) -> None:
    product = await _product(world)
    await _birthday(world.db, world.shop, world.customer, 3, 7)
    await world.run_holiday()
    await world.opt(True)
    await world.materialize()
    day_before = await _due_at(world, offset=-1)
    transport = await _tick(world, day_before)
    (markup,) = transport.markups
    (button,) = markup.inline_keyboard[0]
    assert str(button.callback_data).startswith(OrderStartCB.__prefix__ + ":"), button
    assert OrderStartCB.unpack(str(button.callback_data)).product_id == product


# --- the customer's switch, in the bot ------------------------------------------------


async def _bot(world: World) -> Any:
    bot, recorder = make_bot()
    dispatcher = build_dispatcher(
        session_factory=world.sessions,
        shop_id=world.shop,
        storage=MemoryStorage(),
        schedule_finalize=lambda **kwargs: None,
    )
    return dispatcher, bot, recorder


async def _consents(world: World) -> list[bool]:
    found = await world.db.execute(
        text(
            "SELECT granted FROM consent_events WHERE customer_id = :c "
            "AND type = 'holiday_greetings' ORDER BY id"
        ),
        {"c": world.customer},
    )
    return [bool(r.granted) for r in found]


async def test_the_settings_screen_says_off_and_the_customer_turns_it_on_and_off(
    world: World,
) -> None:
    dispatcher, bot, recorder = await _bot(world)
    await feed(dispatcher, bot, text_update(t("btn.settings.holidays", "uz"), user_id=680_001))
    shown = [c for c in recorder.calls if isinstance(c, SendMessage)]
    assert shown[-1].text == t("settings.holidays.off", "uz")
    await feed(
        dispatcher,
        bot,
        callback_update(HolidayOptCB(choice="on").pack(), user_id=680_001, update_id=2),
    )
    await feed(
        dispatcher,
        bot,
        callback_update(HolidayOptCB(choice="off").pack(), user_id=680_001, update_id=3),
    )
    assert await _consents(world) == [True, False]
    edits = [c for c in recorder.calls if isinstance(c, EditMessageText)]
    assert [e.text for e in edits] == [
        t("settings.holidays.on", "uz"),
        t("settings.holidays.off", "uz"),
    ]


async def test_a_crafted_answer_is_not_recorded(world: World) -> None:
    dispatcher, bot, _ = await _bot(world)
    await feed(dispatcher, bot, callback_update(HolidayOptCB(choice="yes").pack(), user_id=680_001))
    assert await _consents(world) == []


# --- the owner's switch in /shop, the admin's dates in /admin -------------------------


async def test_the_owner_switches_holidays_in_the_panel_and_it_is_audited(world: World) -> None:
    from tests.test_shop_panel import app_for, log_in

    db = world.db
    other = await _shop(db, "B")
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await log_in(client, db, world.shop, 670001)
        screen = await (await client.get("/shop/holidays")).text()
        assert t("holiday.navruz", "uz") in screen
        response = await client.post(
            "/shop/holidays",
            data={"csrf": csrf, "holiday": "navruz", "on": "1"},
            allow_redirects=False,
        )
        assert response.status == 303
        refused = await client.post(
            "/shop/holidays",
            data={"csrf": csrf, "holiday": "christmas", "on": "1"},
            allow_redirects=False,
        )
        assert "refused" in refused.headers["Location"]
    async with world.sessions() as session:
        assert await holiday_campaigns.enabled_holidays(session, shop_id=world.shop) == {"navruz"}
        assert await holiday_campaigns.enabled_holidays(session, shop_id=other) == set()
    actions = (
        await db.execute(
            text(
                "SELECT action, detail FROM shop_audit_log WHERE shop_id = :s "
                "AND action LIKE 'holiday%'"
            ),
            {"s": world.shop},
        )
    ).all()
    assert [(a.action, a.detail) for a in actions] == [("holiday_on", {"holiday": "navruz"})]


async def test_the_admin_enters_a_lunar_date_and_it_is_audited(world: World) -> None:
    from tests.test_admin_auth import app_for, logged_in

    db = world.db
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await logged_in(client, db)
        assert (await client.get("/admin/holidays")).status == 200
        ok = await client.post(
            "/admin/holidays",
            data={"csrf": csrf, "holiday": "qurbon_hayit", "date": "2027-05-16"},
            allow_redirects=False,
        )
        fixed = await client.post(
            "/admin/holidays",
            data={"csrf": csrf, "holiday": "navruz", "date": "2027-03-21"},
            allow_redirects=False,
        )
        bad = await client.post(
            "/admin/holidays",
            data={"csrf": csrf, "holiday": "qurbon_hayit", "date": "soon"},
            allow_redirects=False,
        )
    assert ok.headers["Location"].endswith("done=ok")
    assert "refused" in fixed.headers["Location"] and "refused" in bad.headers["Location"]
    async with world.sessions() as session:
        assert await holiday_campaigns.lunar_dates(session) == {
            "qurbon_hayit": (date(2027, 5, 16),)
        }
    entry = (
        await db.execute(
            text("SELECT after FROM admin_audit_log WHERE action = 'holiday_date_set'")
        )
    ).scalar_one()
    assert entry == {"holiday": "qurbon_hayit", "date": "2027-05-16"}


# --- the database ---------------------------------------------------------------------


async def _refused(db: AsyncConnection, sql: str, params: dict[str, Any]) -> str:
    try:
        async with db.begin_nested():
            await db.execute(text(sql), params)
    except (IntegrityError, DBAPIError) as refused:
        return str(refused.orig)
    raise AssertionError("the database accepted it")


async def test_a_row_must_be_a_persons_date_or_a_holiday_never_both_or_neither(
    world: World,
) -> None:
    insert = (
        "INSERT INTO scheduled_notifications (shop_id, customer_id, occasion_id, holiday, "
        " occurrence_year, offset_days, due_at_utc, channel) "
        "VALUES (:s, :c, NULL, :h, 2027, 0, now(), 'telegram')"
    )
    neither = await _refused(world.db, insert, {"s": world.shop, "c": world.customer, "h": None})
    assert "ck_scheduled_notifications_occasion_or_holiday" in neither
    unknown = await _refused(world.db, insert, {"s": world.shop, "c": world.customer, "h": "xmas"})
    assert "ck_scheduled_notifications_holiday_known" in unknown


async def test_one_holiday_row_per_customer_year_and_offset(world: World) -> None:
    insert = (
        "INSERT INTO scheduled_notifications (shop_id, customer_id, holiday, occurrence_year, "
        " offset_days, due_at_utc, channel) "
        "VALUES (:s, :c, 'navruz', 2027, 0, now(), 'telegram')"
    )
    await world.db.execute(text(insert), {"s": world.shop, "c": world.customer})
    twice = await _refused(world.db, insert, {"s": world.shop, "c": world.customer})
    assert "uq_scheduled_notifications_holiday" in twice


async def test_only_a_lunar_holiday_has_entered_dates(world: World) -> None:
    refused = await _refused(
        world.db,
        "INSERT INTO holiday_dates (holiday, year, falls_on, set_by) "
        "VALUES ('navruz', 2027, '2027-03-21', 1)",
        {},
    )
    assert "ck_holiday_dates_lunar_only" in refused
    wrong_year = await _refused(
        world.db,
        "INSERT INTO holiday_dates (holiday, year, falls_on, set_by) "
        "VALUES ('qurbon_hayit', 2027, '2028-05-05', 1)",
        {},
    )
    assert "ck_holiday_dates_date_in_its_year" in wrong_year
