"""Cancel and /start must win from EVERY state, including looped-back ones.

CP3.5 introduced two loop-back edges (`asking_more_dates -> choosing_month` and
`asking_more_people -> choosing_type`). A state reached the second time around
is the same state object, but it is reached with different FSM data, and it is
exactly where an escape hatch is easiest to lose.

Two layers of proof:

* exhaustive and static -- for every declared state, the FIRST handler matching
  a Cancel label or /start is the nav/onboarding one;
* behavioural -- actually drive the loops, then press Cancel or /start, and
  assert the customer really gets out.
"""

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
    ConfirmCB,
    DayCB,
    MonthCB,
    OccasionTypeCB,
    YearSkipCB,
    YesNoCB,
)
from gulbot.bot.factory import build_dispatcher
from gulbot.bot.shadow_sweep import declared_states, make_message, matching_handlers
from gulbot.i18n.catalog import CATALOG

USER_ID = 930_001

CANCEL_LABELS = sorted(CATALOG["btn.nav.cancel"].values())


def _sweep_dispatcher() -> Dispatcher:
    return build_dispatcher(session_factory=None, shop_id=0)  # type: ignore[arg-type]


# --- exhaustive: nav is first for every state ------------------------------


@pytest.mark.parametrize("cancel_label", CANCEL_LABELS)
async def test_cancel_is_the_first_match_in_every_state(cancel_label: str) -> None:
    dispatcher = _sweep_dispatcher()
    for raw_state in declared_states():
        matched = await matching_handlers(
            dispatcher, make_message(cancel_label), raw_state, "message"
        )
        assert matched, f"nothing handles Cancel in state {raw_state}"
        assert matched[0].name == "cancel_anywhere", (
            f"in state {raw_state}, Cancel is handled first by {matched[0]}"
        )


async def test_start_is_the_first_match_in_every_state() -> None:
    dispatcher = _sweep_dispatcher()
    for raw_state in declared_states():
        matched = await matching_handlers(dispatcher, make_message("/start"), raw_state, "message")
        assert matched, f"nothing handles /start in state {raw_state}"
        assert matched[0].name == "start", (
            f"in state {raw_state}, /start is handled first by {matched[0]}"
        )


async def test_every_loop_target_state_is_covered_by_the_check() -> None:
    """The loop-back edges land on these states; they must be declared."""
    states = {str(s) for s in declared_states()}
    loop_targets = {
        "AddOccasion:choosing_month",  # asking_more_dates --yes-->
        "AddOccasion:choosing_type",  # asking_more_people --yes-->
    }
    loop_sources = {"AddOccasion:asking_more_dates", "AddOccasion:asking_more_people"}
    assert loop_targets <= states
    assert loop_sources <= states


# --- behavioural: drive the loops, then escape -----------------------------


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

    async def save_one_date(self, preset: str, month: int, day: int) -> None:
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


async def _fsm_state(dispatcher: Dispatcher, bot: Bot) -> str | None:
    key = dispatcher.fsm.resolve_context(bot, chat_id=USER_ID, user_id=USER_ID)
    return await key.get_state()


@pytest.mark.infra
async def test_cancel_wins_after_looping_back_for_another_date(
    driver: Driver, dispatcher: Dispatcher, bot_and_session: tuple[Bot, RecordingSession]
) -> None:
    """Loop edge: asking_more_dates --yes--> choosing_month."""
    bot, _ = bot_and_session
    await driver.save_one_date("mother", 3, 8)
    await driver.tap(YesNoCB(scope="dates", answer="yes").pack())
    assert await _fsm_state(dispatcher, bot) == "AddOccasion:choosing_month"

    driver.recorder.calls.clear()
    await driver.text(CATALOG["btn.nav.cancel"]["uz"])
    assert CATALOG["nav.cancelled"]["uz"] in driver.sent
    assert await _fsm_state(dispatcher, bot) is None


@pytest.mark.infra
async def test_cancel_wins_after_looping_back_for_another_person(
    driver: Driver, dispatcher: Dispatcher, bot_and_session: tuple[Bot, RecordingSession]
) -> None:
    """Loop edge: asking_more_people --yes--> choosing_type."""
    bot, _ = bot_and_session
    await driver.save_one_date("mother", 3, 8)
    await driver.tap(YesNoCB(scope="dates", answer="no").pack())
    await driver.tap(YesNoCB(scope="people", answer="yes").pack())
    assert await _fsm_state(dispatcher, bot) == "AddOccasion:choosing_type"

    driver.recorder.calls.clear()
    await driver.text(CATALOG["btn.nav.cancel"]["uz"])
    assert CATALOG["nav.cancelled"]["uz"] in driver.sent
    assert await _fsm_state(dispatcher, bot) is None


@pytest.mark.infra
async def test_start_wins_deep_inside_a_second_lap(
    driver: Driver, dispatcher: Dispatcher, bot_and_session: tuple[Bot, RecordingSession]
) -> None:
    """Second lap, text-waiting state, /start must still escape.

    A RETURNING customer's /start clears the flow and lands on the menu; only
    first contact chains into onboarding. So the escape is to state None.
    """
    bot, _ = bot_and_session
    await driver.save_one_date("mother", 3, 8)
    await driver.tap(YesNoCB(scope="dates", answer="no").pack())
    await driver.tap(YesNoCB(scope="people", answer="yes").pack())
    await driver.tap(OccasionTypeCB(type="custom").pack())
    assert await _fsm_state(dispatcher, bot) == "AddOccasion:entering_label"

    driver.recorder.calls.clear()
    await driver.text("/start")
    assert await _fsm_state(dispatcher, bot) is None
    assert CATALOG["start.welcome_back"]["uz"].format(name="Aziz") in driver.sent


@pytest.mark.infra
async def test_cancel_wins_from_both_chained_questions(
    driver: Driver, dispatcher: Dispatcher, bot_and_session: tuple[Bot, RecordingSession]
) -> None:
    bot, _ = bot_and_session
    await driver.save_one_date("mother", 3, 8)
    assert await _fsm_state(dispatcher, bot) == "AddOccasion:asking_more_dates"
    await driver.text(CATALOG["btn.nav.cancel"]["uz"])
    assert await _fsm_state(dispatcher, bot) is None

    await driver.text(CATALOG["btn.menu.occasions"]["uz"])
    await driver.tap(
        __import__("gulbot.bot.callbacks", fromlist=["AddOccasionCB"])
        .AddOccasionCB(action="start")
        .pack()
    )
    await driver.save_one_date("father", 4, 9)
    await driver.tap(YesNoCB(scope="dates", answer="no").pack())
    assert await _fsm_state(dispatcher, bot) == "AddOccasion:asking_more_people"
    await driver.text(CATALOG["btn.nav.cancel"]["uz"])
    assert await _fsm_state(dispatcher, bot) is None


@pytest.mark.infra
async def test_cancel_does_not_lose_already_saved_dates(
    driver: Driver, db: AsyncConnection
) -> None:
    """Cancelling the loop abandons the flow, not the work already confirmed."""
    await driver.save_one_date("mother", 3, 8)
    await driver.tap(YesNoCB(scope="dates", answer="yes").pack())
    await driver.text(CATALOG["btn.nav.cancel"]["uz"])

    saved = (
        await db.execute(
            text(
                "SELECT count(*) FROM occasions o JOIN customers c ON c.id = o.customer_id "
                "WHERE c.telegram_user_id = :t AND o.active"
            ),
            {"t": USER_ID},
        )
    ).scalar_one()
    assert saved == 1
