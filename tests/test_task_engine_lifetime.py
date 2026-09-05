"""Every Celery task disposes the engine it built.

The third client in the same family as CP8's Redis debouncer and CP6's aiohttp
session, and the last one that was still leaking. `build_session_factory()`
creates a NEW engine per call and never disposes it. For `bot.run` that is
correct -- one engine for the life of one long-running process. For a task it is
a leak: `asyncio.run()` ends, the loop closes, and an asyncpg pool bound to that
loop is abandoned. One pool per tick, every minute, forever.

`task_session_factory()` is the fix, and these are its guards.

HOW DISPOSAL IS OBSERVED. `AsyncEngine.dispose()` does not set a flag, but it
does replace the pool -- `pool.recreate()`. So identity of `engine.pool` before
and after is a real, public-API witness that dispose actually ran, rather than a
mock assertion about a call that may or may not do anything.

WHY THE TASKS ARE PATCHED THE WAY THEY ARE. Each test replaces
`task_session_factory` on the task module with a wrapper around the REAL context
manager, pointed at the test database. If a task ever reverts to a
non-disposing factory, the wrapper is never called, `engines` stays empty, and
the test fails on that -- so this catches the regression, not just the leak.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import text

import gulbot.worker.tasks as tasks_module
from gulbot.config import Settings
from gulbot.db.session import build_session_factory, task_session_factory

pytestmark = pytest.mark.infra


def patched_factory(settings: Settings, engines: list[tuple[object, object]]):  # type: ignore[no-untyped-def]
    @asynccontextmanager
    async def factory_cm(*_args: object, **_kwargs: object):  # type: ignore[no-untyped-def]
        async with task_session_factory(settings.postgres_test_db) as factory:
            engine = factory.kw["bind"]
            engines.append((engine, engine.pool))
            yield factory

    return factory_cm


def assert_all_disposed(engines: list[tuple[object, object]], *, expected: int) -> None:
    assert len(engines) == expected, (
        f"expected {expected} engine(s) to be built through task_session_factory, "
        f"got {len(engines)} -- did the task go back to build_session_factory?"
    )
    for engine, pool_before in engines:
        assert engine.pool is not pool_before, (  # type: ignore[attr-defined]
            "the engine was never disposed; its pool is still the original one"
        )


# --- the context manager itself --------------------------------------------


async def test_the_task_factory_disposes_its_engine(settings: Settings) -> None:
    async with task_session_factory(settings.postgres_test_db) as factory:
        engine = factory.kw["bind"]
        pool_before = engine.pool
        async with factory() as session:
            assert (await session.execute(text("SELECT 1"))).scalar_one() == 1

    assert engine.pool is not pool_before, "task_session_factory leaked its pool"


async def test_the_plain_factory_still_does_not_dispose(settings: Settings) -> None:
    """Guards the guard.

    If `build_session_factory` ever started disposing on its own, the test above
    would pass for the wrong reason and prove nothing about the context manager.
    It must also keep NOT disposing, because `bot.run` depends on that.
    """
    factory = build_session_factory(settings.postgres_test_db)
    engine = factory.kw["bind"]
    pool_before = engine.pool
    async with factory() as session:
        await session.execute(text("SELECT 1"))
    try:
        assert engine.pool is pool_before
    finally:
        await engine.dispose()


# --- the tasks -------------------------------------------------------------


def test_the_materializer_disposes_its_engine(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Synchronous and via asyncio.run, the way Celery actually calls it."""
    engines: list[tuple[object, object]] = []
    monkeypatch.setattr(tasks_module, "task_session_factory", patched_factory(settings, engines))

    asyncio.run(tasks_module._materialize_all_shops())

    assert_all_disposed(engines, expected=1)


def test_the_album_finalize_disposes_its_engine(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No such album, so finalize returns MISSING and the task still completes.

    That is enough: the engine is built and disposed on the way through, which
    is the only thing under test here. The album logic has its own tests.
    """
    engines: list[tuple[object, object]] = []
    monkeypatch.setattr(tasks_module, "task_session_factory", patched_factory(settings, engines))

    result = asyncio.run(tasks_module._finalize_album(1, "engine-lifetime-no-such-album"))

    assert result["action"] == "done"
    assert result["outcome"] == "missing"
    assert_all_disposed(engines, expected=1)


def test_two_task_runs_in_one_process_each_build_and_dispose_their_own(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The worker's real shape: asyncio.run twice, two loops, two engines.

    A shared engine would be the same defect the debouncer had, on the database
    side -- an asyncpg pool bound to the first, now-closed loop.
    """
    engines: list[tuple[object, object]] = []
    monkeypatch.setattr(tasks_module, "task_session_factory", patched_factory(settings, engines))

    asyncio.run(tasks_module._materialize_all_shops())
    asyncio.run(tasks_module._materialize_all_shops())

    assert_all_disposed(engines, expected=2)
    assert engines[0][0] is not engines[1][0], "the two runs shared one engine"
