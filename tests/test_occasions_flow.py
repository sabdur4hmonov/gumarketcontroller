"""The add-occasion flow, driven through the real dispatcher."""

from __future__ import annotations

import pytest
import pytest_asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import (
    RecordingSession,
    bound_session_factory,
    callback_update,
    feed,
    make_bot,
    text_update,
)

from gulbot.bot.callbacks import (
    AddOccasionCB,
    BackCB,
    ConfirmCB,
    DayCB,
    MonthCB,
    OccasionActionCB,
    OccasionTypeCB,
    YearSkipCB,
)
from gulbot.bot.factory import build_dispatcher
from gulbot.i18n.catalog import CATALOG

USER_ID = 910_001
OTHER_USER_ID = 910_999


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
    """Sequential update feeder, so tests read like a conversation."""

    def __init__(self, dispatcher: Dispatcher, bot: Bot, recorder: RecordingSession):
        self.dispatcher, self.bot, self.recorder = dispatcher, bot, recorder
        self.n = 0

    async def text(self, value: str) -> None:
        self.n += 1
        await feed(self.dispatcher, self.bot, text_update(value, user_id=USER_ID, update_id=self.n))

    async def tap(self, data: str) -> None:
        self.n += 1
        await feed(
            self.dispatcher,
            self.bot,
            callback_update(data, user_id=USER_ID, update_id=self.n),
        )

    async def open_add_flow(self, preset: str) -> None:
        await self.text(CATALOG["btn.menu.occasions"]["uz"])
        await self.tap(AddOccasionCB(action="start").pack())
        await self.tap(OccasionTypeCB(type=preset).pack())

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


async def _occasions(db: AsyncConnection, telegram_user_id: int = USER_ID) -> list[dict]:
    rows = (
        await db.execute(
            text(
                "SELECT o.id, o.label, o.type, o.month, o.day, o.year, o.active "
                "FROM occasions o JOIN customers c ON c.id = o.customer_id "
                "WHERE c.telegram_user_id = :t ORDER BY o.id"
            ),
            {"t": telegram_user_id},
        )
    ).mappings()
    return [dict(r) for r in rows]


@pytest.mark.infra
async def test_preset_path_saves_the_occasion(driver: Driver, db: AsyncConnection) -> None:
    await driver.open_add_flow("mother")
    await driver.tap(MonthCB(month=3).pack())
    await driver.tap(DayCB(day=8).pack())
    await driver.tap(YearSkipCB(action="skip").pack())
    await driver.tap(ConfirmCB(action="save").pack())

    rows = await _occasions(db)
    assert len(rows) == 1
    assert rows[0]["label"] == CATALOG["occtype.mother"]["uz"]
    assert (rows[0]["type"], rows[0]["month"], rows[0]["day"], rows[0]["year"]) == (
        "mother",
        3,
        8,
        None,
    )


@pytest.mark.infra
async def test_custom_label_is_sanitized_before_storing(
    driver: Driver, db: AsyncConnection
) -> None:
    await driver.open_add_flow("custom")
    await driver.text("  Singlim\nAziza  " + "x" * 100)
    await driver.tap(MonthCB(month=6).pack())
    await driver.tap(DayCB(day=15).pack())
    await driver.tap(YearSkipCB(action="skip").pack())
    await driver.tap(ConfirmCB(action="save").pack())

    rows = await _occasions(db)
    assert len(rows) == 1
    label = rows[0]["label"]
    assert "\n" not in label
    assert len(label) <= 64
    assert label.startswith("Singlim Aziza")


@pytest.mark.infra
async def test_blank_label_is_refused_and_does_not_advance(driver: Driver) -> None:
    await driver.open_add_flow("custom")
    await driver.text("   \n\t  ")
    assert CATALOG["occasions.label_empty"]["uz"] in driver.sent


@pytest.mark.infra
async def test_only_the_custom_preset_opens_a_text_waiting_state(
    driver: Driver, db: AsyncConnection
) -> None:
    """Presets jump straight to the month picker, keeping the sweep surface small."""
    await driver.open_add_flow("wife")
    assert CATALOG["occasions.choose_month"]["uz"] in driver.sent
    assert CATALOG["occasions.enter_label"]["uz"] not in driver.sent


@pytest.mark.infra
async def test_non_numeric_year_is_refused(driver: Driver) -> None:
    await driver.open_add_flow("father")
    await driver.tap(MonthCB(month=5).pack())
    await driver.tap(DayCB(day=10).pack())
    await driver.text("kecha edi")
    assert CATALOG["occasions.year_invalid"]["uz"] in driver.sent


@pytest.mark.infra
async def test_out_of_range_year_is_refused(driver: Driver) -> None:
    await driver.open_add_flow("father")
    await driver.tap(MonthCB(month=5).pack())
    await driver.tap(DayCB(day=10).pack())
    await driver.text("1899")
    assert CATALOG["occasions.year_invalid"]["uz"] in driver.sent


@pytest.mark.infra
async def test_february_29_refuses_a_common_year_before_the_database(
    driver: Driver,
) -> None:
    await driver.open_add_flow("friend")
    await driver.tap(MonthCB(month=2).pack())
    await driver.tap(DayCB(day=29).pack())
    await driver.text("2023")
    assert CATALOG["occasions.year_not_leap"]["uz"] in driver.sent


@pytest.mark.infra
async def test_february_29_accepts_a_leap_year(driver: Driver, db: AsyncConnection) -> None:
    await driver.open_add_flow("friend")
    await driver.tap(MonthCB(month=2).pack())
    await driver.tap(DayCB(day=29).pack())
    await driver.text("2024")
    await driver.tap(ConfirmCB(action="save").pack())

    rows = await _occasions(db)
    assert (rows[0]["month"], rows[0]["day"], rows[0]["year"]) == (2, 29, 2024)


@pytest.mark.infra
async def test_double_tapped_confirm_creates_one_occasion(
    driver: Driver, db: AsyncConnection
) -> None:
    await driver.open_add_flow("wife")
    await driver.tap(MonthCB(month=9).pack())
    await driver.tap(DayCB(day=1).pack())
    await driver.tap(YearSkipCB(action="skip").pack())
    await driver.tap(ConfirmCB(action="save").pack())
    await driver.tap(ConfirmCB(action="save").pack())

    assert len(await _occasions(db)) == 1


@pytest.mark.infra
async def test_discard_saves_nothing(driver: Driver, db: AsyncConnection) -> None:
    await driver.open_add_flow("wife")
    await driver.tap(MonthCB(month=9).pack())
    await driver.tap(DayCB(day=1).pack())
    await driver.tap(YearSkipCB(action="skip").pack())
    await driver.tap(ConfirmCB(action="discard").pack())

    assert await _occasions(db) == []


@pytest.mark.infra
async def test_first_occasion_writes_exactly_one_consent_row(
    driver: Driver, db: AsyncConnection
) -> None:
    for month, day, preset in ((3, 8, "mother"), (4, 9, "father")):
        await driver.open_add_flow(preset)
        await driver.tap(MonthCB(month=month).pack())
        await driver.tap(DayCB(day=day).pack())
        await driver.tap(YearSkipCB(action="skip").pack())
        await driver.tap(ConfirmCB(action="save").pack())

    assert len(await _occasions(db)) == 2
    consents = (
        await db.execute(
            text(
                "SELECT count(*) FROM consent_events ce "
                "JOIN customers c ON c.id = ce.customer_id "
                "WHERE c.telegram_user_id = :t"
            ),
            {"t": USER_ID},
        )
    ).scalar_one()
    assert consents == 1


@pytest.mark.infra
async def test_consent_text_is_shown_on_the_confirm_screen(driver: Driver) -> None:
    """Consent must be visible at the moment of the act it records."""
    await driver.open_add_flow("child")
    await driver.tap(MonthCB(month=7).pack())
    await driver.tap(DayCB(day=4).pack())
    await driver.tap(YearSkipCB(action="skip").pack())
    assert any(CATALOG["occasions.consent"]["uz"] in sent for sent in driver.sent)


@pytest.mark.infra
async def test_back_steps_backwards_one_screen_at_a_time(driver: Driver) -> None:
    await driver.open_add_flow("mother")
    await driver.tap(MonthCB(month=3).pack())

    driver.recorder.calls.clear()
    await driver.tap(BackCB(action="back").pack())
    assert driver.sent == [CATALOG["occasions.choose_month"]["uz"]]

    driver.recorder.calls.clear()
    await driver.tap(BackCB(action="back").pack())
    assert driver.sent == [CATALOG["occasions.choose_type"]["uz"]]


@pytest.mark.infra
async def test_cancel_inside_a_text_waiting_state_leaves_the_flow(
    driver: Driver, db: AsyncConnection
) -> None:
    """nav is registered ahead of the flow, so Cancel beats enter_label."""
    await driver.open_add_flow("custom")

    driver.recorder.calls.clear()
    await driver.text(CATALOG["btn.nav.cancel"]["uz"])
    assert CATALOG["nav.cancelled"]["uz"] in driver.sent
    assert await _occasions(db) == []


@pytest.mark.infra
async def test_deactivate_hides_the_occasion(driver: Driver, db: AsyncConnection) -> None:
    await driver.open_add_flow("mother")
    await driver.tap(MonthCB(month=3).pack())
    await driver.tap(DayCB(day=8).pack())
    await driver.tap(YearSkipCB(action="skip").pack())
    await driver.tap(ConfirmCB(action="save").pack())

    occasion_id = (await _occasions(db))[0]["id"]
    await driver.tap(OccasionActionCB(action="deactivate", occasion_id=occasion_id).pack())

    assert (await _occasions(db))[0]["active"] is False


@pytest.mark.infra
async def test_cannot_deactivate_another_customers_occasion(
    driver: Driver, db: AsyncConnection, shop_id: int
) -> None:
    """A guessed occasion_id must not reach someone else's row."""
    other_id = (
        await db.execute(
            text("INSERT INTO customers (shop_id, telegram_user_id) VALUES (:s, :t) RETURNING id"),
            {"s": shop_id, "t": OTHER_USER_ID},
        )
    ).scalar_one()
    victim_id = (
        await db.execute(
            text(
                "INSERT INTO occasions (shop_id, customer_id, label, type, month, day) "
                "VALUES (:s, :c, 'Theirs', 'friend', 5, 5) RETURNING id"
            ),
            {"s": shop_id, "c": other_id},
        )
    ).scalar_one()

    await driver.tap(OccasionActionCB(action="deactivate", occasion_id=victim_id).pack())

    still_active = (
        await db.execute(text("SELECT active FROM occasions WHERE id = :i"), {"i": victim_id})
    ).scalar_one()
    assert still_active is True
    assert CATALOG["occasions.not_found"]["uz"] in driver.sent


@pytest.mark.infra
async def test_a_forged_day_callback_is_refused(driver: Driver, db: AsyncConnection) -> None:
    """The picker cannot offer Feb 30, but a replayed callback can claim it."""
    await driver.open_add_flow("friend")
    await driver.tap(MonthCB(month=2).pack())

    driver.recorder.calls.clear()
    await driver.tap(DayCB(day=30).pack())

    # Refused: it re-asks for the day instead of advancing to the year step.
    assert driver.sent == [CATALOG["occasions.choose_day"]["uz"]]
    assert CATALOG["occasions.enter_year"]["uz"] not in driver.sent
