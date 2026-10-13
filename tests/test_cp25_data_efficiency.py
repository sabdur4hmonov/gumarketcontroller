"""Bound pool demand and cache catalogue choices only within one tick."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import text

from gulbot.db import session as db_session
from gulbot.sending import attach
from gulbot.sending.dispatcher import TickResult
from gulbot.services.bouquets import Bouquet
from gulbot.worker import tasks


async def test_task_pool_is_small_without_shrinking_the_bot_pool(settings) -> None:
    engine = db_session.build_engine(settings.postgres_test_db)
    try:
        assert engine.pool.size() == 5
        async with db_session.task_session_factory(settings.postgres_test_db) as factory:
            task_engine = factory.kw["bind"]
            assert task_engine.pool.size() == 1, "A sequential tick needs one connection"
            assert task_engine.pool._max_overflow == 0, "Worker concurrency multiplies pool demand"
            async with factory() as session:
                assert await session.scalar(text("SELECT 1")) == 1
    finally:
        await engine.dispose()


def test_pool_and_connect_waits_are_bounded(monkeypatch) -> None:
    captured = {}

    def build(url, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(db_session, "create_async_engine", build)
    db_session.build_engine()
    assert captured.get("pool_timeout") == 5, "Pool starvation must not wait forever"
    assert captured["connect_args"].get("timeout") == 10, "DB connection must have a deadline"


async def test_bouquet_cache_is_per_tick_and_per_shop_and_preference(monkeypatch) -> None:
    assert hasattr(attach, "BouquetLookup"), "Repeated customer choices need a tick-owned lookup"
    calls = []

    async def choose(session, *, shop_id, preferred_hashtag):
        calls.append((shop_id, preferred_hashtag))
        return (
            Bouquet(shop_id, str(shop_id), None, "none", f"file-{shop_id}")
            if shop_id == 1
            else None
        )

    monkeypatch.setattr(attach, "choose_bouquet", choose)
    session = AsyncMock()
    first = attach.BouquetLookup()
    assert (await first.choose(session, 1, "atirgul")).telegram_file_id == "file-1"
    assert (await first.choose(session, 1, "atirgul")).telegram_file_id == "file-1"
    assert await first.choose(session, 2, "atirgul") is None
    assert await first.choose(session, 2, "atirgul") is None
    await first.choose(session, 1, "lola")
    assert calls == [(1, "atirgul"), (2, "atirgul"), (1, "lola")], (
        "Never mix shops or repeatedly query empty catalogues"
    )
    second = attach.BouquetLookup()
    await second.choose(session, 1, "atirgul")
    assert len(calls) == 4, "A new tick must see catalogue changes"


async def test_worker_shares_lookup_inside_tick_and_rebuilds_it_next_tick(monkeypatch):
    calls = []

    async def choose(session, *, shop_id, preferred_hashtag):
        calls.append(shop_id)
        return None

    session = AsyncMock()
    context = AsyncMock()
    context.__aenter__.return_value = session

    @asynccontextmanager
    async def factory():
        yield lambda: context

    async def tick(session, *, attach, **kwargs):
        group = SimpleNamespace(shop_id=1, rows=[], occasions=[], recipients=[], lang="uz")
        assert await attach(group) is None
        assert await attach(group) is None
        return TickResult()

    monkeypatch.setattr(attach, "choose_bouquet", choose)
    monkeypatch.setattr(tasks, "task_session_factory", factory)
    monkeypatch.setattr(
        tasks, "registry_for", AsyncMock(return_value=SimpleNamespace(close=AsyncMock()))
    )
    monkeypatch.setattr(tasks, "run_tick", tick)
    # _transports produces a closure; the stub tick intentionally doesn't send.
    await tasks._send_due_reminders()
    await tasks._send_due_reminders()
    assert calls == [1, 1], "One catalogue query per tick, never per customer or across ticks"
