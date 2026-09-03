"""Reminder and flower preferences.

CP3.6 STORES these fields. Nothing consumes them: wiring (offsets, send_time)
into the materializer is CP5's job, and `test_cp36_does_not_reach_into_cp5`
keeps that boundary honest.
"""

from __future__ import annotations

from datetime import time
from pathlib import Path

import pytest
import pytest_asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import (
    RecordingSession,
    bound_session_factory,
    callback_update,
    feed,
    make_bot,
    text_update,
)
from tests.test_tenancy import _make_customer, _make_shop

from gulbot.bot.callbacks import (
    ConfirmCB,
    DayCB,
    FlowerCB,
    MonthCB,
    OccasionTypeCB,
    RecipientCB,
    ReminderCountCB,
    SendTimeCB,
    YearSkipCB,
    YesNoCB,
)
from gulbot.bot.factory import build_dispatcher
from gulbot.i18n.catalog import CATALOG
from gulbot.models.customer import (
    DEFAULT_REMINDER_COUNT,
    DEFAULT_SEND_TIME,
    REMINDER_COUNT_OFFSETS,
    SEND_TIME_CHOICES,
)
from gulbot.models.recipient import FLOWER_PRESETS

REPO_ROOT = Path(__file__).resolve().parents[1]
USER_ID = 940_001


# --- constants -------------------------------------------------------------


def test_flower_presets_are_the_agreed_set() -> None:
    assert FLOWER_PRESETS == ("atirgul", "tyulpan", "lola")


def test_reminder_count_maps_to_the_agreed_offsets() -> None:
    """CP5 consumes this mapping; CP3.6 only records it."""
    assert REMINDER_COUNT_OFFSETS == {1: (0,), 2: (-1, 0), 3: (-7, -1, 0)}


def test_send_time_slots_are_the_agreed_three() -> None:
    assert {
        "morning": time(9, 0),
        "noon": time(13, 0),
        "evening": time(20, 0),
    } == SEND_TIME_CHOICES


def test_defaults_for_customers_who_skipped() -> None:
    assert DEFAULT_REMINDER_COUNT == 3
    assert time(20, 0) == DEFAULT_SEND_TIME


def test_send_time_slots_avoid_the_callback_separator() -> None:
    """aiogram packs callback data with ":", so "09:00" cannot be a value."""
    for slot in SEND_TIME_CHOICES:
        assert ":" not in slot
        assert SendTimeCB(value=slot).pack().count(":") == 1


# --- the database refuses bad values ---------------------------------------


@pytest.mark.infra
@pytest.mark.parametrize("preset", FLOWER_PRESETS)
async def test_postgres_accepts_every_flower_preset(db: AsyncConnection, preset: str) -> None:
    shop = await _make_shop(db, "S")
    customer = await _make_customer(db, shop, tg_id=1)
    await db.execute(
        text(
            "INSERT INTO recipients (shop_id, customer_id, label, type, preferred_hashtag) "
            "VALUES (:s, :c, 'X', 'custom', :h)"
        ),
        {"s": shop, "c": customer, "h": preset},
    )


@pytest.mark.infra
async def test_postgres_accepts_null_preferred_hashtag(db: AsyncConnection) -> None:
    """ "Boshqa" is a real answer, not a missing one."""
    shop = await _make_shop(db, "S")
    customer = await _make_customer(db, shop, tg_id=1)
    await db.execute(
        text(
            "INSERT INTO recipients (shop_id, customer_id, label, type, preferred_hashtag) "
            "VALUES (:s, :c, 'X', 'custom', NULL)"
        ),
        {"s": shop, "c": customer},
    )


@pytest.mark.infra
@pytest.mark.parametrize("bad", ["roza", "ROSE", "atirgul ", "", "chinnigul"])
async def test_postgres_refuses_an_unknown_flower(db: AsyncConnection, bad: str) -> None:
    shop = await _make_shop(db, "S")
    customer = await _make_customer(db, shop, tg_id=1)
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await db.execute(
                text(
                    "INSERT INTO recipients "
                    "(shop_id, customer_id, label, type, preferred_hashtag) "
                    "VALUES (:s, :c, 'X', 'custom', :h)"
                ),
                {"s": shop, "c": customer, "h": bad},
            )
    assert "ck_recipients_preferred_hashtag_known" in str(excinfo.value)


@pytest.mark.infra
@pytest.mark.parametrize("count", [1, 2, 3])
async def test_postgres_accepts_valid_reminder_counts(db: AsyncConnection, count: int) -> None:
    shop = await _make_shop(db, "S")
    customer = await _make_customer(db, shop, tg_id=1)
    await db.execute(
        text("UPDATE customers SET reminder_count = :n WHERE id = :c"),
        {"n": count, "c": customer},
    )


@pytest.mark.infra
@pytest.mark.parametrize("count", [0, 4, -1, 99])
async def test_postgres_refuses_invalid_reminder_counts(db: AsyncConnection, count: int) -> None:
    shop = await _make_shop(db, "S")
    customer = await _make_customer(db, shop, tg_id=1)
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await db.execute(
                text("UPDATE customers SET reminder_count = :n WHERE id = :c"),
                {"n": count, "c": customer},
            )
    assert "ck_customers_reminder_count_known" in str(excinfo.value)


@pytest.mark.infra
@pytest.mark.parametrize("slot", [time(9, 0), time(13, 0), time(20, 0)])
async def test_postgres_accepts_the_three_send_times(db: AsyncConnection, slot: time) -> None:
    shop = await _make_shop(db, "S")
    customer = await _make_customer(db, shop, tg_id=1)
    await db.execute(
        text("UPDATE customers SET preferred_send_time = :t WHERE id = :c"),
        {"t": slot, "c": customer},
    )


@pytest.mark.infra
@pytest.mark.parametrize("slot", [time(8, 0), time(21, 30), time(0, 0), time(13, 1)])
async def test_postgres_refuses_other_send_times(db: AsyncConnection, slot: time) -> None:
    """A free-form time would defeat the point of a fixed picker."""
    shop = await _make_shop(db, "S")
    customer = await _make_customer(db, shop, tg_id=1)
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await db.execute(
                text("UPDATE customers SET preferred_send_time = :t WHERE id = :c"),
                {"t": slot, "c": customer},
            )
    assert "ck_customers_preferred_send_time_known" in str(excinfo.value)


@pytest.mark.infra
async def test_preferences_start_null(db: AsyncConnection) -> None:
    """NULL is how CP5 will tell "skipped" from "chose 3"."""
    shop = await _make_shop(db, "S")
    customer = await _make_customer(db, shop, tg_id=1)
    row = (
        await db.execute(
            text("SELECT reminder_count, preferred_send_time FROM customers WHERE id = :c"),
            {"c": customer},
        )
    ).one()
    assert row.reminder_count is None
    assert row.preferred_send_time is None


# --- the flow --------------------------------------------------------------


@pytest_asyncio.fixture
async def bot_and_session() -> tuple[Bot, RecordingSession]:
    bot, session = make_bot()
    try:
        yield bot, session
    finally:
        await bot.session.close()


@pytest_asyncio.fixture
async def dispatcher(db: AsyncConnection, shop_id: int) -> Dispatcher:
    return build_dispatcher(
        session_factory=bound_session_factory(db),
        shop_id=shop_id,
        storage=MemoryStorage(),
    )


class Driver:
    def __init__(self, dispatcher: Dispatcher, bot: Bot, recorder: RecordingSession):
        self.dispatcher, self.bot, self.recorder = dispatcher, bot, recorder
        self.n = 0

    async def text(self, value: str) -> None:
        self.n += 1
        await feed(self.dispatcher, self.bot, text_update(value, user_id=USER_ID, update_id=self.n))

    async def tap(self, data: str) -> None:
        self.n += 1
        await feed(
            self.dispatcher, self.bot, callback_update(data, user_id=USER_ID, update_id=self.n)
        )

    async def add_person(self, preset: str, month: int, day: int) -> None:
        await self.tap(OccasionTypeCB(type=preset).pack())
        await self.tap(MonthCB(month=month).pack())
        await self.tap(DayCB(day=day).pack())
        await self.tap(YearSkipCB(action="skip").pack())
        await self.tap(ConfirmCB(action="save").pack())

    @property
    def sent(self) -> list[str]:
        return self.recorder.sent_texts


@pytest_asyncio.fixture
async def driver(dispatcher: Dispatcher, bot_and_session: tuple[Bot, RecordingSession]) -> Driver:
    bot, recorder = bot_and_session
    d = Driver(dispatcher, bot, recorder)
    await d.text("/start")
    await d.text(CATALOG["btn.language.uz"]["uz"])
    return d


async def _recipient(db: AsyncConnection) -> dict:
    row = (
        await db.execute(
            text(
                "SELECT r.id, r.label, r.preferred_hashtag FROM recipients r "
                "JOIN customers c ON c.id = r.customer_id "
                "WHERE c.telegram_user_id = :t ORDER BY r.id LIMIT 1"
            ),
            {"t": USER_ID},
        )
    ).mappings()
    return dict(row.one())


async def _customer_prefs(db: AsyncConnection) -> dict:
    row = (
        await db.execute(
            text(
                "SELECT reminder_count, preferred_send_time FROM customers "
                "WHERE telegram_user_id = :t"
            ),
            {"t": USER_ID},
        )
    ).mappings()
    return dict(row.one())


@pytest.mark.infra
async def test_flower_question_is_asked_after_the_last_date(driver: Driver) -> None:
    await driver.add_person("mother", 3, 8)
    driver.recorder.calls.clear()
    await driver.tap(YesNoCB(scope="dates", answer="no").pack())

    expected = CATALOG["prefs.ask_flower"]["uz"].format(label=CATALOG["occtype.mother"]["uz"])
    assert expected in driver.sent


@pytest.mark.infra
@pytest.mark.parametrize("preset", FLOWER_PRESETS)
async def test_flower_choice_is_stored(driver: Driver, db: AsyncConnection, preset: str) -> None:
    await driver.add_person("mother", 3, 8)
    await driver.tap(YesNoCB(scope="dates", answer="no").pack())
    await driver.tap(FlowerCB(choice=preset).pack())

    assert (await _recipient(db))["preferred_hashtag"] == preset


@pytest.mark.infra
async def test_boshqa_stores_null(driver: Driver, db: AsyncConnection) -> None:
    await driver.add_person("mother", 3, 8)
    await driver.tap(YesNoCB(scope="dates", answer="no").pack())
    await driver.tap(FlowerCB(choice="skip").pack())

    assert (await _recipient(db))["preferred_hashtag"] is None


@pytest.mark.infra
async def test_flower_answer_leads_on_to_the_next_person_question(
    driver: Driver,
) -> None:
    await driver.add_person("mother", 3, 8)
    await driver.tap(YesNoCB(scope="dates", answer="no").pack())
    driver.recorder.calls.clear()
    await driver.tap(FlowerCB(choice="atirgul").pack())

    assert CATALOG["recipients.ask_more_people"]["uz"] in driver.sent


@pytest.mark.infra
async def test_flower_question_is_not_repeated_for_a_person_who_has_one(
    driver: Driver, db: AsyncConnection
) -> None:
    """Adding a later date to the same person must not re-ask."""
    await driver.add_person("mother", 3, 8)
    await driver.tap(YesNoCB(scope="dates", answer="no").pack())
    await driver.tap(FlowerCB(choice="lola").pack())
    await driver.tap(YesNoCB(scope="people", answer="no").pack())
    await driver.tap(ReminderCountCB(value="skip").pack())
    await driver.tap(SendTimeCB(value="skip").pack())

    recipient_id = (await _recipient(db))["id"]
    await driver.text(CATALOG["btn.menu.occasions"]["uz"])
    await driver.tap(RecipientCB(action="add_date", recipient_id=recipient_id).pack())
    await driver.tap(MonthCB(month=12).pack())
    await driver.tap(DayCB(day=25).pack())
    await driver.tap(YearSkipCB(action="skip").pack())
    await driver.tap(ConfirmCB(action="save").pack())

    driver.recorder.calls.clear()
    await driver.tap(YesNoCB(scope="dates", answer="no").pack())

    assert CATALOG["recipients.ask_more_people"]["uz"] in driver.sent
    assert (await _recipient(db))["preferred_hashtag"] == "lola"


@pytest.mark.infra
async def test_each_person_gets_their_own_flower_question(
    driver: Driver, db: AsyncConnection
) -> None:
    await driver.add_person("mother", 3, 8)
    await driver.tap(YesNoCB(scope="dates", answer="no").pack())
    await driver.tap(FlowerCB(choice="atirgul").pack())
    await driver.tap(YesNoCB(scope="people", answer="yes").pack())
    await driver.add_person("father", 5, 9)
    await driver.tap(YesNoCB(scope="dates", answer="no").pack())
    await driver.tap(FlowerCB(choice="tyulpan").pack())

    rows = (
        await db.execute(
            text(
                "SELECT r.preferred_hashtag FROM recipients r "
                "JOIN customers c ON c.id = r.customer_id "
                "WHERE c.telegram_user_id = :t ORDER BY r.id"
            ),
            {"t": USER_ID},
        )
    ).scalars()
    assert list(rows) == ["atirgul", "tyulpan"]


# --- customer-level preferences --------------------------------------------


@pytest.mark.infra
async def test_reminder_questions_come_after_the_last_person(driver: Driver) -> None:
    await driver.add_person("mother", 3, 8)
    await driver.tap(YesNoCB(scope="dates", answer="no").pack())
    await driver.tap(FlowerCB(choice="skip").pack())
    driver.recorder.calls.clear()
    await driver.tap(YesNoCB(scope="people", answer="no").pack())

    assert CATALOG["prefs.ask_reminder_count"]["uz"] in driver.sent


@pytest.mark.infra
@pytest.mark.parametrize("count", [1, 2, 3])
async def test_reminder_count_is_stored(driver: Driver, db: AsyncConnection, count: int) -> None:
    await driver.add_person("mother", 3, 8)
    await driver.tap(YesNoCB(scope="dates", answer="no").pack())
    await driver.tap(FlowerCB(choice="skip").pack())
    await driver.tap(YesNoCB(scope="people", answer="no").pack())
    await driver.tap(ReminderCountCB(value=str(count)).pack())

    assert (await _customer_prefs(db))["reminder_count"] == count


@pytest.mark.infra
@pytest.mark.parametrize(
    ("slot", "expected"),
    [("morning", time(9, 0)), ("noon", time(13, 0)), ("evening", time(20, 0))],
)
async def test_send_time_is_stored(
    driver: Driver, db: AsyncConnection, slot: str, expected: time
) -> None:
    await driver.add_person("mother", 3, 8)
    await driver.tap(YesNoCB(scope="dates", answer="no").pack())
    await driver.tap(FlowerCB(choice="skip").pack())
    await driver.tap(YesNoCB(scope="people", answer="no").pack())
    await driver.tap(ReminderCountCB(value="3").pack())
    await driver.tap(SendTimeCB(value=slot).pack())

    assert (await _customer_prefs(db))["preferred_send_time"] == expected


@pytest.mark.infra
async def test_skipping_both_leaves_them_null(driver: Driver, db: AsyncConnection) -> None:
    """Onboarding must never block on these, and skipped must stay legible."""
    await driver.add_person("mother", 3, 8)
    await driver.tap(YesNoCB(scope="dates", answer="no").pack())
    await driver.tap(FlowerCB(choice="skip").pack())
    await driver.tap(YesNoCB(scope="people", answer="no").pack())
    await driver.tap(ReminderCountCB(value="skip").pack())
    driver.recorder.calls.clear()
    await driver.tap(SendTimeCB(value="skip").pack())

    prefs = await _customer_prefs(db)
    assert prefs["reminder_count"] is None
    assert prefs["preferred_send_time"] is None
    assert CATALOG["recipients.onboarding_done"]["uz"] in driver.sent


@pytest.mark.infra
async def test_preferences_are_asked_only_once(driver: Driver) -> None:
    """A customer who answered is not asked again when adding someone later."""
    await driver.add_person("mother", 3, 8)
    await driver.tap(YesNoCB(scope="dates", answer="no").pack())
    await driver.tap(FlowerCB(choice="skip").pack())
    await driver.tap(YesNoCB(scope="people", answer="no").pack())
    await driver.tap(ReminderCountCB(value="2").pack())
    await driver.tap(SendTimeCB(value="morning").pack())

    await driver.text(CATALOG["btn.menu.occasions"]["uz"])
    from gulbot.bot.callbacks import AddOccasionCB

    await driver.tap(AddOccasionCB(action="start").pack())
    await driver.add_person("father", 5, 9)
    await driver.tap(YesNoCB(scope="dates", answer="no").pack())
    await driver.tap(FlowerCB(choice="skip").pack())
    driver.recorder.calls.clear()
    await driver.tap(YesNoCB(scope="people", answer="no").pack())

    assert CATALOG["prefs.ask_reminder_count"]["uz"] not in driver.sent
    assert CATALOG["menu.title"]["uz"] in driver.sent


@pytest.mark.infra
async def test_answering_the_count_but_skipping_the_time(
    driver: Driver, db: AsyncConnection
) -> None:
    await driver.add_person("mother", 3, 8)
    await driver.tap(YesNoCB(scope="dates", answer="no").pack())
    await driver.tap(FlowerCB(choice="skip").pack())
    await driver.tap(YesNoCB(scope="people", answer="no").pack())
    await driver.tap(ReminderCountCB(value="1").pack())
    await driver.tap(SendTimeCB(value="skip").pack())

    prefs = await _customer_prefs(db)
    assert prefs["reminder_count"] == 1
    assert prefs["preferred_send_time"] is None


@pytest.mark.infra
async def test_cannot_set_a_flower_on_another_customers_recipient(
    driver: Driver, db: AsyncConnection, shop_id: int
) -> None:
    from gulbot.services.preferences import set_preferred_hashtag

    other = await _make_customer(db, shop_id, tg_id=940_999)
    victim = (
        await db.execute(
            text(
                "INSERT INTO recipients (shop_id, customer_id, label, type) "
                "VALUES (:s, :c, 'Theirs', 'friend') RETURNING id"
            ),
            {"s": shop_id, "c": other},
        )
    ).scalar_one()

    mine = (
        await db.execute(
            text("SELECT id FROM customers WHERE telegram_user_id = :t"), {"t": USER_ID}
        )
    ).scalar_one()

    from tests.bot_harness import bound_session_factory as factory

    async with factory(db)() as session:
        changed = await set_preferred_hashtag(
            session,
            shop_id=shop_id,
            customer_id=mine,
            recipient_id=victim,
            hashtag="atirgul",
        )
        await session.commit()
    assert changed is False

    still_null = (
        await db.execute(
            text("SELECT preferred_hashtag FROM recipients WHERE id = :i"), {"i": victim}
        )
    ).scalar_one()
    assert still_null is None


# --- scope fence -----------------------------------------------------------


def test_cp36_does_not_reach_into_cp5() -> None:
    """CP3.6 stores these fields; CP5 consumes them.

    The scheduling package must not read the preference columns yet, or the two
    checkpoints stop being independently revertable.
    """
    scheduling = REPO_ROOT / "src/gulbot/scheduling"
    for path in scheduling.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for field in ("reminder_count", "preferred_send_time", "preferred_hashtag"):
            assert field not in source, f"{path.name} already consumes {field}"


def test_service_layer_rejects_values_the_database_would_refuse() -> None:
    """Fail in Python before Postgres has to, so the error is legible."""
    import asyncio

    from gulbot.services.preferences import set_preferred_hashtag

    with pytest.raises(ValueError, match="unknown flower preset"):
        asyncio.run(
            set_preferred_hashtag(
                None,  # type: ignore[arg-type]
                shop_id=1,
                customer_id=1,
                recipient_id=1,
                hashtag="roza",
            )
        )
