# ruff: noqa: F811  -- fixtures are imported by name; pytest injects them into
# the same-named test parameters, which ruff reads as a redefinition.
"""The per-shop-per-day lock must not be held across a Telegram call.

`claim_delivery_slot` takes a transaction-scoped advisory lock, released by the
commit. Measured in the pre-deployment audit, on a throwaway database:

  * a holder IDLE IN TRANSACTION blocks the next submit for that shop and day
    with no bound -- still blocked after 8 s, because `lock_timeout` and
    `idle_in_transaction_session_timeout` are both 0;
  * terminating the holder's backend, or killing its process, releases it in
    about 0.1 s.

So the lock is not leaked by a dying worker. The risk is a LIVE one that holds
it while waiting on something slow -- and `submit_order` held it across Telegram
calls, each allowed aiogram's 60-second default.

These tests make Telegram slow on purpose and time a competing claim from a
second connection. Before the fix the competitor waits out the slow call.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from aiogram import Bot
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import SendMessage, TelegramMethod
from sqlalchemy.ext.asyncio import async_sessionmaker
from tests.bot_harness import TEST_TOKEN, RecordingSession
from tests.test_audit_races import (  # noqa: F401  -- `committed` is a fixture
    DELIVERY,
    _place,
    committed,
    confirm_tap,
    engine_for,
)

from gulbot.bot.factory import build_dispatcher
from gulbot.bot.states import PlaceOrder
from gulbot.services.orders import claim_delivery_slot

pytestmark = pytest.mark.infra

#: How long Telegram takes to answer the customer, in this test.
SLOW = 3.0
#: How long a competing claim may wait and still count as not blocked.
PROMPT = 1.0


class SlowTelegram(RecordingSession):
    """Every SendMessage takes SLOW seconds, and says when one has started."""

    def __init__(self) -> None:
        super().__init__()
        self.sending = asyncio.Event()

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,  # noqa: ASYNC109  aiogram's BaseSession contract
    ) -> Any:
        if isinstance(method, SendMessage):
            self.sending.set()
            await asyncio.sleep(SLOW)
        return await super().make_request(bot, method, timeout)


async def _submit_with_slow_telegram(committed: dict, user_id: int) -> SlowTelegram:
    """Park `user_id` on the confirmation screen and tap Submit, with Telegram
    slow. Returns the session so the caller can wait for the slow send to begin.
    The dispatcher runs in the background; the caller awaits `.done`."""
    settings, shop, product = committed["settings"], committed["shop"], committed["product"]
    engine = engine_for(settings)
    telegram = SlowTelegram()
    bot = Bot(token=TEST_TOKEN, session=telegram)
    dispatcher = build_dispatcher(
        session_factory=async_sessionmaker(engine, expire_on_commit=False),
        shop_id=shop,
        storage=MemoryStorage(),
        schedule_finalize=lambda **kwargs: None,
    )
    context = dispatcher.fsm.get_context(bot, user_id, user_id)
    await context.set_state(PlaceOrder.confirming)
    await context.update_data(
        product_id=product,
        product_name="Oq atirgul",
        price_uzs=450_000,
        telegram_file_id="f",
        delivery_date=DELIVERY.isoformat(),
        delivery_hour=14,
        landmark="Kok eshik",
        recipient_name="Dilnoza",
        location_text="Chilonzor 5",
        submit_token=f"lock-{user_id}",
    )

    async def run() -> None:
        try:
            await dispatcher.feed_update(bot, confirm_tap(user_id=user_id, update_id=user_id))
        finally:
            await engine.dispose()

    telegram.done = asyncio.create_task(run())  # type: ignore[attr-defined]
    return telegram


async def _time_a_competing_claim(committed: dict) -> float:
    engine = engine_for(committed["settings"])
    started = time.monotonic()
    try:
        async with async_sessionmaker(engine)() as session:
            await claim_delivery_slot(session, shop_id=committed["shop"], day=DELIVERY)
            await session.commit()
    finally:
        await engine.dispose()
    return time.monotonic() - started


async def test_a_slow_confirmation_to_the_winner_does_not_hold_the_lock(
    committed: dict,
) -> None:
    """The winner's order is written; Telegram is slow to say "placed". A second
    customer submitting for the same day must not wait on that message."""
    telegram = await _submit_with_slow_telegram(committed, 880_000)
    await asyncio.wait_for(telegram.sending.wait(), timeout=10)

    waited = await _time_a_competing_claim(committed)
    await telegram.done  # type: ignore[attr-defined]

    assert waited < PROMPT, (
        f"a competing submit waited {waited:.1f}s on the winner's Telegram call; "
        f"the lock was held across it"
    )


async def test_a_slow_refusal_to_the_loser_does_not_hold_the_lock(committed: dict) -> None:
    """The day is full; Telegram is slow to tell the loser so. Nobody else may
    wait on that message either -- on a busy day the loser path is the common
    one."""
    await _place(committed, token="lock-already-full")

    telegram = await _submit_with_slow_telegram(committed, 880_001)
    await asyncio.wait_for(telegram.sending.wait(), timeout=10)

    waited = await _time_a_competing_claim(committed)
    await telegram.done  # type: ignore[attr-defined]

    assert waited < PROMPT, (
        f"a competing submit waited {waited:.1f}s on the loser's Telegram call; "
        f"the lock was held across it"
    )
