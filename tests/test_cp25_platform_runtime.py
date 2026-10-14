"""Platform work yields during TLS setup and exposes stale runtime snapshots."""

from __future__ import annotations

import asyncio
import contextlib
import threading
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.fsm.storage.memory import MemoryStorage

from gulbot.bot import factory, run
from gulbot.bot.middlewares import DbSessionMiddleware, PrivateOnlyMiddleware
from gulbot.bot.reliability import HandlerDeadline
from gulbot.bot.routers import shop_onboarding as onboarding
from gulbot.services import admin_panel


@pytest.mark.parametrize("path", ["platform", "onboarding"])
async def test_tls_factory_runs_offloop_and_client_closes_on_owner_loop(monkeypatch, path):
    owner_thread = threading.get_ident()
    loop = asyncio.get_running_loop()
    built_on = []
    closed_on = []

    async def close():
        closed_on.append(asyncio.get_running_loop())

    bot = SimpleNamespace(id=123, session=SimpleNamespace(close=close))

    def build(token):
        built_on.append(threading.get_ident())
        assert token == "123:token"
        return bot

    if path == "onboarding":

        async def token(state):
            return "123:token"

        async def check(client):
            assert client is bot
            raise ValueError("check failed")

        monkeypatch.setattr(onboarding, "_shop_token", token)
        with pytest.raises(ValueError, match="check failed"):
            await onboarding._checked_with_the_shop_bot(None, build, check)
    else:
        monkeypatch.setattr(run, "cipher_ready", lambda: None)
        monkeypatch.setattr(
            run,
            "get_settings",
            lambda: SimpleNamespace(
                platform_bot_token=SimpleNamespace(get_secret_value=lambda: "123:token")
            ),
        )

        async def poll(dispatcher, client):
            await asyncio.Event().wait()

        storage = MemoryStorage()
        platform = await run.start_platform(
            None, storage=storage, pollers=SimpleNamespace(running={}), bot_factory=build, poll=poll
        )
        try:
            assert platform is not None
        finally:
            await platform.stop()
            await storage.close()
    assert built_on and all(t != owner_thread for t in built_on)
    assert closed_on == [loop]


async def test_platform_deadline_is_first_and_cancels_stuck_update():
    dispatcher = factory.build_platform_dispatcher(session_factory=None)
    middlewares = dispatcher.update.outer_middleware._middlewares
    deadline = dispatcher.get("handler_deadline")
    assert isinstance(deadline, HandlerDeadline) and deadline.shop_id == 0
    assert middlewares.index(deadline) < next(
        i
        for i, m in enumerate(middlewares)
        if isinstance(m, (DbSessionMiddleware, PrivateOnlyMiddleware))
    )
    deadline.seconds = 0.01
    cancelled = asyncio.Event()

    async def stuck(event, data):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    assert await deadline(stuck, None, {}) is None
    assert cancelled.is_set() and deadline.timeouts == 1
    await dispatcher.storage.close()


def test_runtime_freshness_does_not_report_a_dead_process_as_healthy():
    now = datetime.now(UTC)
    row = SimpleNamespace(
        last_indexed_at=now,
        runtime={"status": "running"},
        runtime_updated_at=now - timedelta(seconds=121),
        checked_at=now,
        no_bot=False,
        token_valid=True,
        group_chat_id=5,
        group_ok=True,
        channel_id=6,
        channel_ok=True,
    )
    assert admin_panel._health(row, now)[:2] == ("bad", "poller snapshot stale")
    row.runtime_updated_at = now - timedelta(seconds=119)
    assert admin_panel._health(row, now)[:2] == ("ok", "")
    row.runtime = None
    row.runtime_updated_at = None
    assert admin_panel._health(row, now)[0] == "ok"


@pytest.mark.parametrize("cancel", [False, True])
async def test_abandoned_constructor_closes_late_result_on_owner_loop(cancel):
    from gulbot.bot.client_lifetime import create_bot

    release = threading.Event()
    entered = threading.Event()
    closed = asyncio.Event()
    loop = asyncio.get_running_loop()
    closures = []

    async def close():
        closures.append(asyncio.get_running_loop())
        closed.set()

    def build(token):
        entered.set()
        release.wait(2)
        return SimpleNamespace(session=SimpleNamespace(close=close))

    task = asyncio.create_task(create_bot(build, "token", seconds=0.02 if not cancel else 20))
    try:
        if cancel:
            assert await asyncio.to_thread(entered.wait, 1)
            task.cancel()
        bounded = False
        try:
            await task
        except (asyncio.CancelledError, TimeoutError):
            bounded = True
        assert bounded, "Constructor must honour cancellation and its startup deadline"
    finally:
        release.set()
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(closed.wait(), timeout=2)
    assert closures == [loop], "Late TLS result must close exactly once on its owning loop"


async def test_production_watchdog_runs_every_five_seconds_and_stops_cleanly(monkeypatch):
    delays = []
    pollers = SimpleNamespace(
        sync=AsyncMock(),
        watchdog=AsyncMock(return_value=[]),
        restart_due=lambda: False,
        running={1: object()},
        stop=AsyncMock(),
    )
    storage = SimpleNamespace(close=AsyncMock())
    monkeypatch.setattr(
        run, "get_settings", lambda: SimpleNamespace(log_level="INFO", environment="test")
    )
    monkeypatch.setattr(run, "build_session_factory", lambda: None)
    monkeypatch.setattr(run, "build_storage", lambda: storage)
    monkeypatch.setattr(run, "ShopPollers", lambda *args, **kwargs: pollers)
    monkeypatch.setattr(run, "start_platform", AsyncMock(return_value=None))

    async def sleep(delay):
        delays.append(delay)
        if len(delays) == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(run.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await run.main()
    assert delays == [5, 5], "Production watchdog must not wait for the credential refresh"
    pollers.watchdog.assert_awaited_once()
    pollers.sync.assert_awaited_once()
    pollers.stop.assert_awaited_once()
    storage.close.assert_awaited_once()
