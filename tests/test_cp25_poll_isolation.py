"""A synchronous startup error cannot prevent another shop's poller starting."""

from __future__ import annotations

import asyncio
import contextlib
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.fsm.storage.memory import MemoryStorage

from gulbot.bot import run


def world(monkeypatch, factory):
    class Sessions:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(
        run, "load_bot_credentials", AsyncMock(return_value={1: object(), 2: object()})
    )
    monkeypatch.setattr(run, "stored_tokens", lambda credentials: str)
    monkeypatch.setattr(
        run,
        "build_dispatcher",
        lambda **kwargs: SimpleNamespace(
            stop_polling=AsyncMock(side_effect=RuntimeError("fake poll"))
        ),
    )

    async def poll(dispatcher, bot):
        await asyncio.Event().wait()

    return run.ShopPollers(Sessions, storage=MemoryStorage(), bot_factory=factory, poll=poll)


async def test_unexpected_factory_error_is_isolated(monkeypatch) -> None:
    def factory(token):
        if token == "1":
            raise RuntimeError("synthetic factory failure")
        return SimpleNamespace(id=int(token), session=SimpleNamespace(close=AsyncMock()))

    pollers = world(monkeypatch, factory)
    started = []
    try:
        with contextlib.suppress(RuntimeError):
            started = await pollers.sync()
        assert started == [2], "One shop's startup crash must not stop the fleet"
        assert 2 in pollers.running and not pollers.running[2].task.done()
    finally:
        await pollers.stop()


async def test_bot_constructor_cannot_block_the_polling_loop(monkeypatch) -> None:
    owner = threading.get_ident()
    threads = []

    def factory(token):
        threads.append(threading.get_ident())
        return SimpleNamespace(id=int(token), session=SimpleNamespace(close=AsyncMock()))

    pollers = world(monkeypatch, factory)
    try:
        assert await pollers.sync() == [1, 2]
        assert threads and all(t != owner for t in threads), (
            "TLS certificate loading must be off loop"
        )
    finally:
        await pollers.stop()
