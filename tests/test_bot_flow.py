"""End-to-end handler behaviour through the real dispatcher."""

from __future__ import annotations

import pytest
import pytest_asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import RecordingSession, bound_session_factory, feed, make_bot, text_update

from gulbot.bot.factory import build_dispatcher
from gulbot.i18n.catalog import CATALOG

USER_ID = 900_001


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


async def _customer_count(db: AsyncConnection, shop_id: int, user_id: int) -> int:
    return int(
        (
            await db.execute(
                text("SELECT count(*) FROM customers WHERE shop_id = :s AND telegram_user_id = :t"),
                {"s": shop_id, "t": user_id},
            )
        ).scalar_one()
    )


@pytest.mark.infra
async def test_start_registers_the_customer_and_asks_for_language(
    dispatcher: Dispatcher,
    bot_and_session: tuple[Bot, RecordingSession],
    db: AsyncConnection,
    shop_id: int,
) -> None:
    bot, recorder = bot_and_session
    await feed(dispatcher, bot, text_update("/start", user_id=USER_ID))

    assert await _customer_count(db, shop_id, USER_ID) == 1
    assert CATALOG["start.choose_language"]["uz"] in recorder.sent_texts


@pytest.mark.infra
async def test_start_twice_creates_one_customer(
    dispatcher: Dispatcher,
    bot_and_session: tuple[Bot, RecordingSession],
    db: AsyncConnection,
    shop_id: int,
) -> None:
    bot, _ = bot_and_session
    await feed(dispatcher, bot, text_update("/start", user_id=USER_ID, update_id=1))
    await feed(dispatcher, bot, text_update("/start", user_id=USER_ID, update_id=2))

    assert await _customer_count(db, shop_id, USER_ID) == 1


@pytest.mark.infra
async def test_choosing_russian_persists_and_switches_the_interface(
    dispatcher: Dispatcher,
    bot_and_session: tuple[Bot, RecordingSession],
    db: AsyncConnection,
    shop_id: int,
) -> None:
    bot, recorder = bot_and_session
    await feed(dispatcher, bot, text_update("/start", user_id=USER_ID, update_id=1))
    await feed(
        dispatcher,
        bot,
        text_update(CATALOG["btn.language.ru"]["uz"], user_id=USER_ID, update_id=2),
    )

    stored = (
        await db.execute(
            text("SELECT lang FROM customers WHERE shop_id = :s AND telegram_user_id = :t"),
            {"s": shop_id, "t": USER_ID},
        )
    ).scalar_one()
    assert stored == "ru"
    # CP3.5: first contact chains straight into onboarding, in the new language.
    assert CATALOG["occasions.choose_type"]["ru"] in recorder.sent_texts


@pytest.mark.infra
async def test_help_button_answers_in_the_customers_language(
    dispatcher: Dispatcher,
    bot_and_session: tuple[Bot, RecordingSession],
) -> None:
    bot, recorder = bot_and_session
    await feed(dispatcher, bot, text_update("/start", user_id=USER_ID, update_id=1))
    await feed(
        dispatcher,
        bot,
        text_update(CATALOG["btn.language.uz"]["uz"], user_id=USER_ID, update_id=2),
    )
    # CP3.5 leaves first-contact customers inside the onboarding chain.
    await feed(
        dispatcher,
        bot,
        text_update(CATALOG["btn.nav.cancel"]["uz"], user_id=USER_ID, update_id=3),
    )
    await feed(
        dispatcher,
        bot,
        text_update(CATALOG["btn.menu.help"]["uz"], user_id=USER_ID, update_id=4),
    )

    assert CATALOG["help.text"]["uz"] in recorder.sent_texts


@pytest.mark.infra
async def test_unrecognised_text_hits_the_fallback_not_a_flow(
    dispatcher: Dispatcher,
    bot_and_session: tuple[Bot, RecordingSession],
) -> None:
    bot, recorder = bot_and_session
    await feed(dispatcher, bot, text_update("/start", user_id=USER_ID, update_id=1))
    await feed(
        dispatcher,
        bot,
        text_update(CATALOG["btn.language.uz"]["uz"], user_id=USER_ID, update_id=2),
    )
    await feed(dispatcher, bot, text_update("qwerty asdf", user_id=USER_ID, update_id=3))

    assert CATALOG["common.unknown"]["uz"] in recorder.sent_texts


@pytest.mark.infra
async def test_back_inside_a_flow_returns_to_settings_not_the_main_menu(
    dispatcher: Dispatcher,
    bot_and_session: tuple[Bot, RecordingSession],
) -> None:
    """The exact bug the shadow sweep caught: an ungated Back handler here
    would send the customer to the main menu instead of back one screen."""
    bot, recorder = bot_and_session
    await feed(dispatcher, bot, text_update("/start", user_id=USER_ID, update_id=1))
    await feed(
        dispatcher,
        bot,
        text_update(CATALOG["btn.language.uz"]["uz"], user_id=USER_ID, update_id=2),
    )
    # CP3.5 leaves first-contact customers inside the onboarding chain.
    await feed(
        dispatcher,
        bot,
        text_update(CATALOG["btn.nav.cancel"]["uz"], user_id=USER_ID, update_id=3),
    )
    await feed(
        dispatcher,
        bot,
        text_update(CATALOG["btn.menu.settings"]["uz"], user_id=USER_ID, update_id=4),
    )
    await feed(
        dispatcher,
        bot,
        text_update(CATALOG["btn.settings.change_language"]["uz"], user_id=USER_ID, update_id=5),
    )
    recorder.calls.clear()
    await feed(
        dispatcher,
        bot,
        text_update(CATALOG["btn.nav.back"]["uz"], user_id=USER_ID, update_id=6),
    )

    assert recorder.sent_texts == [CATALOG["settings.title"]["uz"]]
