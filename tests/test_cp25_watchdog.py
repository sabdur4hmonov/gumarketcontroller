"""Poller recovery uses injected time, not sleeps or a fleet benchmark."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from tests.test_cp25_poll_isolation import world


async def test_crashed_poller_is_detected_without_touching_the_healthy_shop(monkeypatch) -> None:
    def factory(token):
        return SimpleNamespace(id=int(token), session=SimpleNamespace(close=AsyncMock()))

    pollers = world(monkeypatch, factory)
    try:
        await pollers.sync()
        healthy = pollers.running[2].task
        broken = pollers.running[1].task
        broken.cancel()
        await asyncio.gather(broken, return_exceptions=True)
        found = await pollers.watchdog()
        assert found == [1], "Watchdog must detect the crashed shop"
        assert pollers.running[2].task is healthy and not healthy.done()
    finally:
        await pollers.stop()


async def test_stall_backoff_and_restart_use_injected_time(monkeypatch) -> None:
    clock = [0.0]

    def factory(token):
        return SimpleNamespace(id=int(token), session=SimpleNamespace(close=AsyncMock()))

    pollers = world(monkeypatch, factory)
    pollers._clock = lambda: clock[0]
    pollers._persist = AsyncMock()
    try:
        await pollers.sync()
        healthy = pollers.running[2].task
        clock[0] = 100
        pollers.running[2].progress.last_progress = 100
        assert await pollers.watchdog() == [1]
        assert pollers._states[1]["status"] == "backoff"
        assert pollers._states[1]["reason"] == "poller_stalled"
        assert not pollers.restart_due(), "No immediate restart loop"
        assert await pollers.sync() == []
        clock[0] = 102
        assert pollers.restart_due()
        assert await pollers.sync() == [1]
        assert pollers.running[2].task is healthy
        pollers._backoff(1, "fixture")
        assert pollers._states[1]["retry_delay_s"] == 2
        for _ in range(100):
            pollers._backoff(1, "fixture")
        assert pollers._states[1]["retry_delay_s"] == 60, "Backoff must be capped"
    finally:
        await pollers.stop()
