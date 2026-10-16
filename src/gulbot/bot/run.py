"""The bot process: every shop's bot, and the platform bot, in one process.

ONE DISPATCHER PER SHOP. Every customer-facing handler is written against the
shop its dispatcher was built for (`CustomerMiddleware(shop_id)`), and the
tenancy of every customer, order and date rests on that binding. So each shop
with a usable bot gets its own dispatcher and its own long-poll, and the
binding stays exactly what it was when there was one shop.

This replaced `resolve_single_shop`, which refused to start with more than one
shop -- so the first completed owner onboarding would have left the pilot's bot
unable to restart.

WHICH BOT: the same rule the workers send by (gulbot.bot.registry) -- a shop's
own stored token, or, for the pilot shop alone, the logged BOT_TOKEN fallback.
Receiving on one bot and sending from another would split every conversation.

NEW SHOPS WITHOUT A RESTART. Onboarding tells `ShopPollers.sync` the moment a
shop is committed, and a refresh every SHOP_REFRESH_SECONDS catches anything
else. A poller that died is restarted on the next sync. A shop that cannot be
served is reported -- once per reason -- and never stops the others.

ONE BOT IS NEVER POLLED TWICE: two long-polls of one bot make Telegram answer
409 to both, and the second shop would be the one silently stealing updates.

SCALE NOTE: one long-poll per shop is simple and right for tens of shops. For
the ~1000 the SaaS targets, webhooks are the better shape -- one HTTP endpoint,
no idle connection per bot -- and the per-shop dispatcher carries over as is.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.base import BaseStorage
from aiogram.utils.token import TokenValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gulbot.bot.client_lifetime import close_bot, create_bot
from gulbot.bot.factory import (
    ALLOWED_UPDATES,
    build_dispatcher,
    build_platform_dispatcher,
    build_storage,
)
from gulbot.bot.loop_lag import monitor as monitor_event_loop
from gulbot.bot.registry import BotFactory, build_bot_for, stored_tokens
from gulbot.bot.reliability import PollObserver, PollProgress
from gulbot.config import get_settings, warn_if_unlimited_pages
from gulbot.db.session import build_session_factory
from gulbot.sending.transport import ShopBotUnavailable
from gulbot.services.runtime_state import store_states
from gulbot.services.shop_tokens import TokenCipherError, cipher_ready, load_bot_credentials

log = logging.getLogger("gulbot")

#: How often the process looks for shops it is not yet polling.
SHOP_REFRESH_SECONDS = 60

PollFn = Callable[[Dispatcher, Bot], Coroutine[Any, Any, None]]

#: How long a stopping poll gets to finish on its own before it is cancelled.
STOP_GRACE_SECONDS = 10


async def _stop_poll(dispatcher: Dispatcher, task: asyncio.Task[None]) -> None:
    """Stop one poll the way aiogram expects, then make sure it is gone.

    `stop_polling()` first, not `task.cancel()`: start_polling runs its own
    per-bot tasks, and cancelling the outer task alone leaves those orphaned --
    "Task was destroyed but it is pending" at shutdown. stop_polling lets
    aiogram cancel them itself. RuntimeError means it was not aiogram's poll,
    or it had not started yet, and cancelling is then the right thing.
    """
    if not task.done():
        try:
            await asyncio.wait_for(dispatcher.stop_polling(), timeout=STOP_GRACE_SECONDS)
        except (RuntimeError, TimeoutError):
            task.cancel()
    try:
        await asyncio.wait_for(task, timeout=STOP_GRACE_SECONDS)
    except (asyncio.CancelledError, TimeoutError):
        pass
    except Exception:
        log.exception("a bot poll ended with an error while stopping")


async def poll_forever(dispatcher: Dispatcher, bot: Bot, *, handle_as_tasks: bool = True) -> None:
    """aiogram's own long poll, for one bot.

    `handle_signals=False`: many polls share this process, and shutdown is the
    supervisor's job, not each poll's. `close_bot_session=False`: the bots are
    closed by whoever owns them, once.
    """
    await dispatcher.start_polling(
        bot,
        allowed_updates=ALLOWED_UPDATES,
        handle_signals=False,
        close_bot_session=False,
        handle_as_tasks=handle_as_tasks,
    )


@dataclass
class ShopPoller:
    shop_id: int
    dispatcher: Dispatcher
    bot: Bot
    task: asyncio.Task[None]
    progress: PollProgress
    started_at: float


class ShopPollers:
    """Every shop's long-poll, started and kept running."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        storage: BaseStorage,
        bot_factory: BotFactory = build_bot_for,
        poll: PollFn = poll_forever,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._session_factory = session_factory
        # ONE storage for every dispatcher: its keys carry the bot id (C3 of
        # AUDIT_MULTI_TENANT.md), so shops cannot see each other's state.
        self._storage = storage
        self._bot_factory = bot_factory
        self._poll = poll
        self._clock = clock
        self._retry_at: dict[int, float] = {}
        self._failures: dict[int, int] = {}
        self._states: dict[int, dict[str, Any]] = {}
        self.running: dict[int, ShopPoller] = {}
        #: The last problem reported per shop, so a refresh every minute does
        #: not repeat the same error line forever.
        self._reported: dict[int, str] = {}

    def _report(self, shop_id: int, problem: str) -> None:
        if self._reported.get(shop_id) != problem:
            self._reported[shop_id] = problem
            log.error("shop %s NOT POLLED: %s", shop_id, problem)

    async def sync(self) -> list[int]:
        """Start polling every shop that has a usable bot and is not already
        polled. Returns the shops started this time."""
        await self.watchdog()
        async with self._session_factory() as session:
            credentials = await load_bot_credentials(session)
        token_for = stored_tokens(credentials)
        for shop_id in list(self.running):
            if shop_id not in credentials:
                poller = self.running.pop(shop_id)
                await _stop_poll(poller.dispatcher, poller.task)
                await self._close_bot(poller.bot)
        self._states = {k: v for k, v in self._states.items() if k in credentials}
        self._retry_at = {k: v for k, v in self._retry_at.items() if k in credentials}

        started: list[int] = []
        for shop_id in sorted(credentials):
            if self._clock() < self._retry_at.get(shop_id, 0):
                continue
            current = self.running.get(shop_id)
            if current is not None and not current.task.done():
                continue
            if current is not None:
                log.error("shop %s: its poller stopped; restarting it", shop_id)
                await self._close_bot(current.bot)
                del self.running[shop_id]

            try:
                bot = await create_bot(self._bot_factory, token_for(shop_id))
            except ShopBotUnavailable as missing:
                self._report(shop_id, str(missing))
                continue
            except TokenValidationError:
                self._report(shop_id, "its stored token is not one Telegram would accept")
                continue
            except Exception as error:
                # Exception text can contain a credential or URL. Store/log
                # only its type, and keep starting the remaining shops.
                self._report(shop_id, f"factory_error:{type(error).__name__}")
                self._backoff(shop_id, type(error).__name__)
                continue

            clash = next((p.shop_id for p in self.running.values() if p.bot.id == bot.id), None)
            if clash is not None:
                await self._close_bot(bot)
                self._report(
                    shop_id,
                    f"its bot {bot.id} is already polled for shop {clash}; one bot, one shop",
                )
                continue

            dispatcher = build_dispatcher(
                session_factory=self._session_factory, shop_id=shop_id, storage=self._storage
            )
            progress = PollProgress(last_progress=self._clock())
            middleware = getattr(bot.session, "middleware", None)
            if middleware is not None:
                middleware.register(PollObserver(progress))
            task = asyncio.create_task(self._poll(dispatcher, bot), name=f"poll-shop-{shop_id}")
            self.running[shop_id] = ShopPoller(
                shop_id, dispatcher, bot, task, progress, self._clock()
            )
            self._states[shop_id] = {
                "status": "running",
                "restarts": self._failures.get(shop_id, 0),
            }
            self._reported.pop(shop_id, None)
            started.append(shop_id)
            log.info("shop %s: polling bot %s", shop_id, bot.id)
        await self._persist()
        return started

    async def stop(self) -> None:
        pollers, self.running = list(self.running.values()), {}
        await asyncio.gather(*(_stop_poll(p.dispatcher, p.task) for p in pollers))
        for poller in pollers:
            await self._close_bot(poller.bot)

    async def watchdog(self) -> list[int]:
        found = []
        now = self._clock()
        for shop_id, poller in list(self.running.items()):
            reason = ""
            if poller.task.done():
                error = None if poller.task.cancelled() else poller.task.exception()
                reason = type(error).__name__ if error else "poller_stopped"
            elif now - poller.progress.last_progress > 90:
                reason = "poller_stalled"
            elif poller.progress.consecutive_failures >= 3:
                reason = poller.progress.error_type or "poll_errors"
            if reason:
                await _stop_poll(poller.dispatcher, poller.task)
                await self._close_bot(poller.bot)
                del self.running[shop_id]
                self._backoff(shop_id, reason)
                found.append(shop_id)
            elif now - poller.started_at >= 60:
                self._failures[shop_id] = 0
        if found:
            await self._persist()
        return found

    def _backoff(self, shop_id: int, reason: str) -> None:
        count = self._failures.get(shop_id, 0) + 1
        self._failures[shop_id] = count
        delay = min(60, 2 ** min(count - 1, 6))
        self._retry_at[shop_id] = self._clock() + delay
        self._states[shop_id] = {
            "status": "backoff",
            "reason": reason,
            "retry_delay_s": delay,
            "restarts": count,
        }
        self._report(shop_id, reason)

    def restart_due(self) -> bool:
        return any(
            k not in self.running and due <= self._clock() for k, due in self._retry_at.items()
        )

    async def _persist(self) -> None:
        for shop_id, poller in self.running.items():
            metrics = (
                poller.dispatcher.get("handler_deadline")
                if isinstance(poller.dispatcher, Dispatcher)
                else None
            )
            state = self._states.setdefault(shop_id, {"status": "running"})
            if metrics is not None:
                state.update(metrics.snapshot())
        try:
            async with asyncio.timeout(5), self._session_factory() as session:
                await store_states(session, self._states)
                await session.commit()
        except Exception as error:
            log.warning("runtime snapshot unavailable: %s", type(error).__name__)

    @staticmethod
    async def _close_bot(bot: Bot) -> None:
        with contextlib.suppress(Exception):
            await asyncio.wait_for(bot.session.close(), timeout=5)


@dataclass
class PlatformPoller:
    dispatcher: Dispatcher
    bot: Bot
    task: asyncio.Task[None]

    async def stop(self) -> None:
        await _stop_poll(self.dispatcher, self.task)
        await close_bot(self.bot)


async def start_platform(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    storage: BaseStorage,
    pollers: ShopPollers,
    bot_factory: BotFactory = build_bot_for,
    poll: PollFn = poll_forever,
) -> PlatformPoller | None:
    """The platform bot, where shop owners onboard. Off when PLATFORM_BOT_TOKEN
    is unset -- the deployment then simply serves the shops it has."""
    settings = get_settings()
    token = settings.platform_bot_token.get_secret_value()
    if not token:
        log.info("PLATFORM_BOT_TOKEN is not set: shop-owner onboarding is off")
        return None
    try:
        cipher_ready()
    except TokenCipherError as unusable:
        raise SystemExit(f"REFUSING TO START: PLATFORM_BOT_TOKEN is set, but {unusable}") from None

    bot = await create_bot(bot_factory, token)
    clash = next((p.shop_id for p in pollers.running.values() if p.bot.id == bot.id), None)
    if clash is not None:
        await close_bot(bot)
        raise SystemExit(
            f"REFUSING TO START: PLATFORM_BOT_TOKEN is shop {clash}'s bot; "
            "the platform needs a bot of its own"
        )

    async def start_new_shop(shop_id: int) -> None:
        await pollers.sync()

    dispatcher = build_platform_dispatcher(
        session_factory=session_factory, storage=storage, on_shop_created=start_new_shop
    )
    task = asyncio.create_task(poll(dispatcher, bot), name="poll-platform")
    log.info("platform bot %s: polling (shop-owner onboarding is on)", bot.id)
    return PlatformPoller(dispatcher, bot, task)


def require_something_to_serve(*, shops: int, platform: bool) -> None:
    """A process polling nothing would look healthy and do nothing."""
    if shops == 0 and not platform:
        raise SystemExit(
            "REFUSING TO START: no shop has a usable bot, and PLATFORM_BOT_TOKEN is not set "
            "-- there is nothing to serve. Give a shop BOT_TOKEN as its own bot (python -m "
            "gulbot.cli.seed --name <shop> --store-bot-token), or set PLATFORM_BOT_TOKEN "
            "and onboard one."
        )


async def main() -> None:
    # FIRST: get_settings() is where the production guard refuses to start.
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)-5s %(name)s %(message)s",
    )
    warn_if_unlimited_pages(log)
    session_factory = build_session_factory()
    storage = build_storage()
    pollers = ShopPollers(session_factory, storage=storage)
    loop_monitor = asyncio.create_task(monitor_event_loop(), name="event-loop-lag")
    platform: PlatformPoller | None = None
    try:
        await pollers.sync()
        platform = await start_platform(session_factory, storage=storage, pollers=pollers)
        require_something_to_serve(shops=len(pollers.running), platform=platform is not None)
        log.info(
            "serving %d shop(s); platform bot %s; environment=%s",
            len(pollers.running),
            "on" if platform is not None else "off",
            settings.environment,
        )
        last_refresh = time.monotonic()
        while True:
            await asyncio.sleep(5)
            try:
                found = await pollers.watchdog()
                if (
                    found
                    or pollers.restart_due()
                    or time.monotonic() - last_refresh >= SHOP_REFRESH_SECONDS
                ):
                    await pollers.sync()
                    last_refresh = time.monotonic()
            except Exception:
                # A database blip must not take down every shop's bot.
                log.exception("refreshing the shop pollers failed; trying again later")
    finally:
        loop_monitor.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await loop_monitor
        if platform is not None:
            await platform.stop()
        await pollers.stop()
        await storage.close()


if __name__ == "__main__":
    asyncio.run(main())
