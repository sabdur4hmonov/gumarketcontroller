"""Recipients, chained onboarding and the minimal edit, through the real dispatcher."""

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
    EditOccasionCB,
    MonthCB,
    OccasionActionCB,
    OccasionTypeCB,
    RecipientCB,
    RecipientListCB,
    YearSkipCB,
    YesNoCB,
)
from gulbot.bot.factory import build_dispatcher
from gulbot.i18n.catalog import CATALOG

USER_ID = 920_001
OTHER_USER_ID = 920_999


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
            self.dispatcher, self.bot, callback_update(data, user_id=USER_ID, update_id=self.n)
        )

    async def date(self, month: int, day: int, *, year: str | None = None) -> None:
        await self.tap(MonthCB(month=month).pack())
        await self.tap(DayCB(day=day).pack())
        if year is None:
            await self.tap(YearSkipCB(action="skip").pack())
        else:
            await self.text(year)
        await self.tap(ConfirmCB(action="save").pack())

    async def add_person(self, preset: str, month: int, day: int) -> None:
        await self.tap(OccasionTypeCB(type=preset).pack())
        await self.date(month, day)

    async def open_menu_list(self) -> None:
        await self.text(CATALOG["btn.menu.occasions"]["uz"])

    async def leave_flow(self) -> None:
        """Escape the chained onboarding the fixture leaves us in.

        The list and detail callbacks are gated on state None on purpose, so a
        stale inline button tapped mid-flow does nothing.
        """
        await self.text(CATALOG["btn.nav.cancel"]["uz"])

    @property
    def sent(self) -> list[str]:
        return self.recorder.sent_texts


@pytest_asyncio.fixture
async def driver(dispatcher: Dispatcher, bot_and_session: tuple[Bot, RecordingSession]) -> Driver:
    """A first-contact customer, sitting at the chained onboarding type picker."""
    bot, recorder = bot_and_session
    d = Driver(dispatcher, bot, recorder)
    await d.text("/start")
    await d.text(CATALOG["btn.language.uz"]["uz"])
    return d


async def _recipients(db: AsyncConnection, telegram_user_id: int = USER_ID) -> list[dict]:
    rows = (
        await db.execute(
            text(
                "SELECT r.id, r.label, r.type, r.active FROM recipients r "
                "JOIN customers c ON c.id = r.customer_id "
                "WHERE c.telegram_user_id = :t ORDER BY r.id"
            ),
            {"t": telegram_user_id},
        )
    ).mappings()
    return [dict(r) for r in rows]


async def _occasions(db: AsyncConnection, telegram_user_id: int = USER_ID) -> list[dict]:
    rows = (
        await db.execute(
            text(
                "SELECT o.id, o.recipient_id, o.label, o.month, o.day, o.year, o.active "
                "FROM occasions o JOIN customers c ON c.id = o.customer_id "
                "WHERE c.telegram_user_id = :t ORDER BY o.id"
            ),
            {"t": telegram_user_id},
        )
    ).mappings()
    return [dict(r) for r in rows]


# --- chained onboarding ----------------------------------------------------


@pytest.mark.infra
async def test_first_contact_chains_straight_into_the_type_picker(driver: Driver) -> None:
    """Language choice leads into onboarding without a menu detour."""
    assert CATALOG["occasions.choose_type"]["uz"] in driver.sent


@pytest.mark.infra
async def test_saving_a_date_asks_for_more_dates_for_the_same_person(
    driver: Driver,
) -> None:
    await driver.add_person("mother", 3, 8)
    expected = CATALOG["recipients.ask_more_dates"]["uz"].format(
        label=CATALOG["occtype.mother"]["uz"]
    )
    assert expected in driver.sent


@pytest.mark.infra
async def test_more_dates_yes_reuses_the_same_recipient(
    driver: Driver, db: AsyncConnection
) -> None:
    """The loop that recipients exist for: one person, two dates."""
    await driver.add_person("wife", 3, 8)
    await driver.tap(YesNoCB(scope="dates", answer="yes").pack())
    await driver.date(11, 2)

    recipients = await _recipients(db)
    occasions = await _occasions(db)
    assert len(recipients) == 1, "a second recipient was created for the same person"
    assert len(occasions) == 2
    assert {o["recipient_id"] for o in occasions} == {recipients[0]["id"]}


@pytest.mark.infra
async def test_more_people_yes_starts_a_new_recipient(driver: Driver, db: AsyncConnection) -> None:
    await driver.add_person("mother", 3, 8)
    await driver.tap(YesNoCB(scope="dates", answer="no").pack())
    await driver.tap(YesNoCB(scope="people", answer="yes").pack())
    await driver.add_person("father", 5, 9)

    recipients = await _recipients(db)
    occasions = await _occasions(db)
    assert [r["type"] for r in recipients] == ["mother", "father"]
    assert len({o["recipient_id"] for o in occasions}) == 2


@pytest.mark.infra
async def test_finishing_onboarding_says_so(driver: Driver) -> None:
    await driver.add_person("mother", 3, 8)
    await driver.tap(YesNoCB(scope="dates", answer="no").pack())
    driver.recorder.calls.clear()
    await driver.tap(YesNoCB(scope="people", answer="no").pack())
    assert CATALOG["recipients.onboarding_done"]["uz"] in driver.sent


@pytest.mark.infra
async def test_a_later_addition_returns_to_the_menu_not_the_onboarding_message(
    driver: Driver,
) -> None:
    """Same loop, different ending, because this is no longer first-run."""
    await driver.add_person("mother", 3, 8)
    await driver.tap(YesNoCB(scope="dates", answer="no").pack())
    await driver.tap(YesNoCB(scope="people", answer="no").pack())

    await driver.open_menu_list()
    await driver.tap(AddOccasionCB(action="start").pack())
    await driver.add_person("father", 5, 9)
    await driver.tap(YesNoCB(scope="dates", answer="no").pack())
    driver.recorder.calls.clear()
    await driver.tap(YesNoCB(scope="people", answer="no").pack())

    assert CATALOG["menu.title"]["uz"] in driver.sent
    assert CATALOG["recipients.onboarding_done"]["uz"] not in driver.sent


@pytest.mark.infra
async def test_two_recipients_may_share_a_label_and_a_date(
    driver: Driver, db: AsyncConnection
) -> None:
    """The old label-keyed unique constraint made this impossible."""
    await driver.add_person("friend", 6, 6)
    await driver.tap(YesNoCB(scope="dates", answer="no").pack())
    await driver.tap(YesNoCB(scope="people", answer="yes").pack())
    await driver.add_person("friend", 6, 6)

    recipients = await _recipients(db)
    occasions = await _occasions(db)
    assert len(recipients) == 2
    assert len(occasions) == 2
    assert {r["label"] for r in recipients} == {CATALOG["occtype.friend"]["uz"]}


# --- explicit confirmation -------------------------------------------------


@pytest.mark.infra
async def test_confirm_screen_restates_label_type_and_date(driver: Driver) -> None:
    await driver.tap(OccasionTypeCB(type="mother").pack())
    await driver.tap(MonthCB(month=3).pack())
    await driver.tap(DayCB(day=8).pack())
    driver.recorder.calls.clear()
    await driver.tap(YearSkipCB(action="skip").pack())

    summary = "\n".join(driver.sent)
    label = CATALOG["occtype.mother"]["uz"]
    assert label in summary
    assert "08.03" in summary
    assert CATALOG["occasions.consent"]["uz"] in summary


@pytest.mark.infra
async def test_nothing_is_written_before_the_explicit_tap(
    driver: Driver, db: AsyncConnection
) -> None:
    """Reaching the confirm screen must not create a recipient OR an occasion."""
    await driver.tap(OccasionTypeCB(type="mother").pack())
    await driver.tap(MonthCB(month=3).pack())
    await driver.tap(DayCB(day=8).pack())
    await driver.tap(YearSkipCB(action="skip").pack())

    assert await _recipients(db) == []
    assert await _occasions(db) == []

    await driver.tap(ConfirmCB(action="save").pack())
    assert len(await _recipients(db)) == 1
    assert len(await _occasions(db)) == 1


@pytest.mark.infra
async def test_discard_writes_nothing(driver: Driver, db: AsyncConnection) -> None:
    await driver.tap(OccasionTypeCB(type="mother").pack())
    await driver.tap(MonthCB(month=3).pack())
    await driver.tap(DayCB(day=8).pack())
    await driver.tap(YearSkipCB(action="skip").pack())
    await driver.tap(ConfirmCB(action="discard").pack())

    assert await _recipients(db) == []
    assert await _occasions(db) == []


@pytest.mark.infra
async def test_double_tapped_confirm_creates_one_occasion(
    driver: Driver, db: AsyncConnection
) -> None:
    await driver.tap(OccasionTypeCB(type="wife").pack())
    await driver.tap(MonthCB(month=9).pack())
    await driver.tap(DayCB(day=1).pack())
    await driver.tap(YearSkipCB(action="skip").pack())
    await driver.tap(ConfirmCB(action="save").pack())
    await driver.tap(ConfirmCB(action="save").pack())

    assert len(await _occasions(db)) == 1


# --- validation still holds ------------------------------------------------


@pytest.mark.infra
async def test_custom_label_is_sanitized(driver: Driver, db: AsyncConnection) -> None:
    await driver.tap(OccasionTypeCB(type="custom").pack())
    await driver.text("  Singlim\nAziza  " + "x" * 100)
    await driver.date(6, 15)

    label = (await _recipients(db))[0]["label"]
    assert "\n" not in label
    assert len(label) <= 64
    assert label.startswith("Singlim Aziza")


@pytest.mark.infra
async def test_blank_label_is_refused(driver: Driver) -> None:
    await driver.tap(OccasionTypeCB(type="custom").pack())
    await driver.text("   \n\t  ")
    assert CATALOG["occasions.label_empty"]["uz"] in driver.sent


@pytest.mark.infra
async def test_february_29_still_refuses_a_common_year(driver: Driver) -> None:
    await driver.tap(OccasionTypeCB(type="friend").pack())
    await driver.tap(MonthCB(month=2).pack())
    await driver.tap(DayCB(day=29).pack())
    await driver.text("2023")
    assert CATALOG["occasions.year_not_leap"]["uz"] in driver.sent


@pytest.mark.infra
async def test_forged_day_callback_is_still_refused(driver: Driver) -> None:
    await driver.tap(OccasionTypeCB(type="friend").pack())
    await driver.tap(MonthCB(month=2).pack())
    driver.recorder.calls.clear()
    await driver.tap(DayCB(day=30).pack())
    assert driver.sent == [CATALOG["occasions.choose_day"]["uz"]]


# --- minimal edit ----------------------------------------------------------


@pytest.mark.infra
async def test_rename_with_a_preset(driver: Driver, db: AsyncConnection) -> None:
    await driver.add_person("friend", 6, 6)
    await driver.tap(YesNoCB(scope="dates", answer="no").pack())
    await driver.tap(YesNoCB(scope="people", answer="no").pack())

    recipient_id = (await _recipients(db))[0]["id"]
    await driver.open_menu_list()
    await driver.tap(RecipientCB(action="open", recipient_id=recipient_id).pack())
    await driver.tap(RecipientCB(action="rename", recipient_id=recipient_id).pack())
    await driver.tap(OccasionTypeCB(type="mother").pack())

    renamed = (await _recipients(db))[0]
    assert renamed["label"] == CATALOG["occtype.mother"]["uz"]
    assert renamed["type"] == "mother"


@pytest.mark.infra
async def test_rename_with_free_text_is_sanitized(driver: Driver, db: AsyncConnection) -> None:
    await driver.add_person("friend", 6, 6)
    await driver.tap(YesNoCB(scope="dates", answer="no").pack())
    await driver.tap(YesNoCB(scope="people", answer="no").pack())

    recipient_id = (await _recipients(db))[0]["id"]
    await driver.open_menu_list()
    await driver.tap(RecipientCB(action="rename", recipient_id=recipient_id).pack())
    await driver.tap(OccasionTypeCB(type="custom").pack())
    await driver.text("  Ustozim\nAkmal  ")

    renamed = (await _recipients(db))[0]
    assert renamed["label"] == "Ustozim Akmal"
    assert renamed["type"] == "custom"


@pytest.mark.infra
async def test_editing_a_date_reuses_the_creation_subflow(
    driver: Driver, db: AsyncConnection
) -> None:
    await driver.add_person("mother", 3, 8)
    await driver.tap(YesNoCB(scope="dates", answer="no").pack())
    await driver.tap(YesNoCB(scope="people", answer="no").pack())

    occasion = (await _occasions(db))[0]
    await driver.open_menu_list()
    await driver.tap(EditOccasionCB(occasion_id=occasion["id"]).pack())
    await driver.tap(MonthCB(month=4).pack())
    await driver.tap(DayCB(day=12).pack())
    await driver.tap(YearSkipCB(action="skip").pack())
    await driver.tap(ConfirmCB(action="save").pack())

    updated = await _occasions(db)
    assert len(updated) == 1, "editing must move the date, not add a second one"
    assert (updated[0]["month"], updated[0]["day"]) == (4, 12)


@pytest.mark.infra
async def test_adding_a_date_to_an_existing_recipient(driver: Driver, db: AsyncConnection) -> None:
    await driver.add_person("mother", 3, 8)
    await driver.tap(YesNoCB(scope="dates", answer="no").pack())
    await driver.tap(YesNoCB(scope="people", answer="no").pack())

    recipient_id = (await _recipients(db))[0]["id"]
    await driver.open_menu_list()
    await driver.tap(RecipientCB(action="add_date", recipient_id=recipient_id).pack())
    await driver.date(12, 25)

    occasions = await _occasions(db)
    assert len(occasions) == 2
    assert {o["recipient_id"] for o in occasions} == {recipient_id}
    assert len(await _recipients(db)) == 1


@pytest.mark.infra
async def test_deactivating_a_recipient_hides_their_dates(
    driver: Driver, db: AsyncConnection
) -> None:
    await driver.add_person("mother", 3, 8)
    await driver.tap(YesNoCB(scope="dates", answer="yes").pack())
    await driver.date(11, 2)
    await driver.tap(YesNoCB(scope="dates", answer="no").pack())
    await driver.tap(YesNoCB(scope="people", answer="no").pack())

    recipient_id = (await _recipients(db))[0]["id"]
    await driver.open_menu_list()
    await driver.tap(RecipientCB(action="deactivate", recipient_id=recipient_id).pack())

    assert (await _recipients(db))[0]["active"] is False
    assert all(o["active"] is False for o in await _occasions(db))


@pytest.mark.infra
async def test_deactivating_a_single_date_leaves_the_person(
    driver: Driver, db: AsyncConnection
) -> None:
    await driver.add_person("mother", 3, 8)
    await driver.tap(YesNoCB(scope="dates", answer="yes").pack())
    await driver.date(11, 2)
    await driver.tap(YesNoCB(scope="dates", answer="no").pack())
    await driver.tap(YesNoCB(scope="people", answer="no").pack())

    first = (await _occasions(db))[0]
    await driver.open_menu_list()
    await driver.tap(OccasionActionCB(action="deactivate", occasion_id=first["id"]).pack())

    occasions = await _occasions(db)
    assert [o["active"] for o in occasions] == [False, True]
    assert (await _recipients(db))[0]["active"] is True


@pytest.mark.infra
async def test_back_from_the_detail_view_returns_to_the_list(driver: Driver) -> None:
    await driver.add_person("mother", 3, 8)
    await driver.tap(YesNoCB(scope="dates", answer="no").pack())
    await driver.tap(YesNoCB(scope="people", answer="no").pack())

    await driver.open_menu_list()
    driver.recorder.calls.clear()
    await driver.tap(RecipientListCB(action="back").pack())
    assert CATALOG["recipients.list_title"]["uz"] in driver.sent


@pytest.mark.infra
async def test_back_steps_backwards_one_screen_at_a_time(driver: Driver) -> None:
    await driver.tap(OccasionTypeCB(type="mother").pack())
    await driver.tap(MonthCB(month=3).pack())

    driver.recorder.calls.clear()
    await driver.tap(BackCB(action="back").pack())
    assert driver.sent == [CATALOG["occasions.choose_month"]["uz"]]

    driver.recorder.calls.clear()
    await driver.tap(BackCB(action="back").pack())
    assert driver.sent == [CATALOG["occasions.choose_type"]["uz"]]


# --- tenancy ---------------------------------------------------------------


@pytest.mark.infra
async def test_cannot_open_another_customers_recipient(
    driver: Driver, db: AsyncConnection, shop_id: int
) -> None:
    other_id = (
        await db.execute(
            text("INSERT INTO customers (shop_id, telegram_user_id) VALUES (:s, :t) RETURNING id"),
            {"s": shop_id, "t": OTHER_USER_ID},
        )
    ).scalar_one()
    victim_id = (
        await db.execute(
            text(
                "INSERT INTO recipients (shop_id, customer_id, label, type) "
                "VALUES (:s, :c, 'Theirs', 'friend') RETURNING id"
            ),
            {"s": shop_id, "c": other_id},
        )
    ).scalar_one()

    await driver.leave_flow()
    await driver.open_menu_list()
    driver.recorder.calls.clear()
    await driver.tap(RecipientCB(action="open", recipient_id=victim_id).pack())
    assert CATALOG["recipients.not_found"]["uz"] in driver.sent


@pytest.mark.infra
async def test_cannot_deactivate_another_customers_recipient(
    driver: Driver, db: AsyncConnection, shop_id: int
) -> None:
    other_id = (
        await db.execute(
            text("INSERT INTO customers (shop_id, telegram_user_id) VALUES (:s, :t) RETURNING id"),
            {"s": shop_id, "t": OTHER_USER_ID},
        )
    ).scalar_one()
    victim_id = (
        await db.execute(
            text(
                "INSERT INTO recipients (shop_id, customer_id, label, type) "
                "VALUES (:s, :c, 'Theirs', 'friend') RETURNING id"
            ),
            {"s": shop_id, "c": other_id},
        )
    ).scalar_one()

    await driver.leave_flow()
    await driver.open_menu_list()
    await driver.tap(RecipientCB(action="deactivate", recipient_id=victim_id).pack())

    still_active = (
        await db.execute(text("SELECT active FROM recipients WHERE id = :i"), {"i": victim_id})
    ).scalar_one()
    assert still_active is True


# --- consent ---------------------------------------------------------------


@pytest.mark.infra
async def test_consent_is_written_once_across_the_whole_chain(
    driver: Driver, db: AsyncConnection
) -> None:
    await driver.add_person("mother", 3, 8)
    await driver.tap(YesNoCB(scope="dates", answer="yes").pack())
    await driver.date(11, 2)
    await driver.tap(YesNoCB(scope="dates", answer="no").pack())
    await driver.tap(YesNoCB(scope="people", answer="yes").pack())
    await driver.add_person("father", 5, 9)

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
    assert len(await _occasions(db)) == 3
