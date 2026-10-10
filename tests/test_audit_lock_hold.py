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

These tests HOLD Telegram's answer open on purpose and, while it is held, take
the same lock from a second connection. Before the fix the competitor waits on
the held call.

NO STOPWATCH (CP19). The first version timed the competing claim against a
1-second bound while Telegram slept 3 seconds. It failed once, on 2026-10-09,
in a full-suite run on a loaded machine, and passed in isolation and in the
next loaded full run. The timed span included creating an engine and opening a
connection through Docker's port proxy, which on a loaded machine can itself
take over a second -- the stopwatch measured the machine as much as the lock.
And it could PASS with the defect: a competitor started late enough under load
would find the 3-second call already over and the lock free.

Now nothing is timed:
  * Telegram's answer is held until the test releases it, so the call is
    certainly still in progress while the competitor asks;
  * the competitor's connection is open before the call begins;
  * the competitor asks under `lock_timeout`, which counts only time spent
    WAITING FOR A LOCK -- not CPU starvation, not connecting. A free lock is
    granted whatever the load; a held one is refused with LockNotAvailable.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from aiogram import Bot
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import SendMessage, TelegramMethod
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
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

#: Only ever reached with the defect: how long the competitor waits for a HELD
#: lock before Postgres refuses it. Any value works -- a free lock is granted
#: without waiting, so this bounds the failure, never the pass.
LOCK_WAIT = "2s"
#: A safety net so a broken test cannot hang the suite. Never the measurement.
HANG_GUARD = 60


class HeldTelegram(RecordingSession):
    """Every SendMessage is held open until the test releases it, and says
    when one has started."""

    def __init__(self) -> None:
        super().__init__()
        self.sending = asyncio.Event()
        self.release = asyncio.Event()

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,  # noqa: ASYNC109  aiogram's BaseSession contract
    ) -> Any:
        if isinstance(method, SendMessage):
            self.sending.set()
            await asyncio.wait_for(self.release.wait(), timeout=HANG_GUARD)
        return await super().make_request(bot, method, timeout)


async def _submit_with_telegram_held(committed: dict, user_id: int) -> HeldTelegram:
    """Park `user_id` on the confirmation screen and tap Submit, with Telegram
    held. Returns the session so the caller can wait for the held send to
    begin and release it. The dispatcher runs in the background; the caller
    awaits `.done`."""
    settings, shop, product = committed["settings"], committed["shop"], committed["product"]
    engine = engine_for(settings)
    telegram = HeldTelegram()
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


async def _competing_claim_while_telegram_is_held(
    committed: dict, telegram: HeldTelegram, *, placed_token: str | None = None
) -> str | None:
    """Take the same shop-and-day lock from a second connection while the
    first submit's Telegram call is in progress. None if it was granted; the
    database's refusal otherwise.

    `placed_token`: the order the held call is about, which must already be
    COMMITTED -- proof that the submit took the lock and got past it before
    Telegram was called, so a grant here is not the vacuous kind."""
    engine = engine_for(committed["settings"])
    refused: str | None = None
    try:
        async with AsyncSession(engine) as session:
            # Connected BEFORE the call is under way: nothing below is setup.
            await session.execute(text("SELECT 1"))
            await asyncio.wait_for(telegram.sending.wait(), timeout=HANG_GUARD)
            if placed_token is not None:
                written = await session.scalar(
                    text("SELECT count(*) FROM orders WHERE submit_token = :t"),
                    {"t": placed_token},
                )
                assert written == 1, "Telegram was called before the order was committed"
            await session.execute(text(f"SET LOCAL lock_timeout = '{LOCK_WAIT}'"))
            try:
                await claim_delivery_slot(session, shop_id=committed["shop"], day=DELIVERY)
            except DBAPIError as exc:
                refused = type(exc.orig).__name__
            await session.rollback()
    finally:
        # ALWAYS let the submit finish, whatever happened above. Found by its
        # mutation: an assertion here that skipped this left the submit's
        # transaction open, and the fixture's committed-world teardown then
        # blocked on it with the event loop it needed -- a hang, not a failure.
        telegram.release.set()
        await engine.dispose()
        await asyncio.wait_for(telegram.done, timeout=HANG_GUARD)  # type: ignore[attr-defined]
    return refused


async def test_a_slow_confirmation_to_the_winner_does_not_hold_the_lock(
    committed: dict,
) -> None:
    """The winner's order is written; Telegram is slow to say "placed". A second
    customer submitting for the same day must not wait on that message."""
    telegram = await _submit_with_telegram_held(committed, 880_000)

    refused = await _competing_claim_while_telegram_is_held(
        committed, telegram, placed_token="lock-880000"
    )

    assert refused is None, (
        f"a competing submit was refused the lock ({refused}) while the winner's "
        f"Telegram call was in progress: the lock was held across it"
    )


async def test_a_slow_refusal_to_the_loser_does_not_hold_the_lock(committed: dict) -> None:
    """The day is full; Telegram is slow to tell the loser so. Nobody else may
    wait on that message either -- on a busy day the loser path is the common
    one."""
    await _place(committed, token="lock-already-full")

    telegram = await _submit_with_telegram_held(committed, 880_001)

    refused = await _competing_claim_while_telegram_is_held(committed, telegram)

    assert refused is None, (
        f"a competing submit was refused the lock ({refused}) while the loser's "
        f"Telegram call was in progress: the lock was held across it"
    )
