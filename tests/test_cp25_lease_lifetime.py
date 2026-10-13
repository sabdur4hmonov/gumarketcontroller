"""The actual Postgres lock fences reset and survives for the run lifetime."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from scripts.cp25_load import capacity
from scripts.cp25_load.load_lease import database_lease


async def test_actual_lease_refuses_competitor_and_releases_after_cancellation() -> None:
    held = asyncio.Event()
    wait = asyncio.Event()

    async def owner() -> None:
        async with database_lease():
            held.set()
            await wait.wait()

    task = asyncio.create_task(owner())
    try:
        await asyncio.wait_for(held.wait(), timeout=15)
        with pytest.raises(RuntimeError, match="capacity run"):
            async with database_lease():
                pytest.fail("The database lease allowed two owners")
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    async with database_lease():
        pass


async def test_reset_and_children_cannot_start_without_lease(monkeypatch, tmp_path) -> None:
    from scripts.cp25_load import infrastructure

    class FakeInfrastructure:
        finished = 0.0
        samples = 0

        async def sample(self):
            self.samples += 1

        async def watch(self):
            await asyncio.Event().wait()

        def result(self):
            assert self.samples == 2, "Both boundaries must be sampled"
            return {"sample_count": self.samples}

    monkeypatch.setattr(infrastructure, "Infrastructure", FakeInfrastructure)
    monkeypatch.setattr(capacity, "available_mib", lambda: 2048)
    run = AsyncMock(return_value={"finished": True})
    monkeypatch.setattr(capacity, "_run_owned_scale", run)
    async with database_lease():
        refused = False
        try:
            await capacity.run_scale(2, tmp_path, "none")
        except RuntimeError:
            refused = True
        assert refused, "The competing run must not reach reset or children"
        run.assert_not_awaited()
    result = await capacity.run_scale(2, tmp_path, "none")
    assert result["finished"] is True
    assert "coordinator_process" in result, "Measure the coordinator too"
    assert result.get("infrastructure") == {"sample_count": 2}
    assert (tmp_path / "result.json").exists(), "Publish only the reconciled complete window"
    run.assert_awaited_once_with(2, tmp_path, "none")
