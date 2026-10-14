"""A blocked Telegram reply must not retain a scarce hot-path DB connection."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import Message
from sqlalchemy import text
from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from tests.bot_harness import text_update

from gulbot.bot.callbacks import AnnouncementCB
from gulbot.bot.routers import announcements, onboarding


@pytest.mark.parametrize("path", ["welcome", "published"])
async def test_slow_reply_releases_pool_connection_before_network(settings, monkeypatch, path):
    engine = create_async_engine(
        settings.database_url(database=settings.postgres_test_db),
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.1,
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    entered, release = asyncio.Event(), asyncio.Event()
    state = SimpleNamespace(clear=AsyncMock(), update_data=AsyncMock())

    async def answer(*args, **kwargs):
        entered.set()
        await release.wait()

    try:
        async with sessions() as session:
            await session.execute(text("SELECT 1"))
            if path == "welcome":
                message = SimpleNamespace(answer=answer, from_user=SimpleNamespace(first_name="X"))
                operation = onboarding.start(message, state, session, "uz", False)
            else:
                draft = SimpleNamespace(id=1, revision=1)
                monkeypatch.setattr(
                    announcements.service, "draft_for", AsyncMock(return_value=draft)
                )

                async def publish(*args, **kwargs):
                    # Receipt indexing starts a transaction AFTER delivery was committed.
                    await session.execute(text("SELECT 1"))
                    return "https://t.me/c/1/1"

                monkeypatch.setattr(announcements.service, "publish", publish)
                monkeypatch.setattr(Message, "answer", answer)
                callback = SimpleNamespace(
                    message=text_update("preview", user_id=777).message,
                    from_user=SimpleNamespace(id=777),
                    answer=AsyncMock(),
                )
                operation = announcements.action(
                    callback,
                    AnnouncementCB(action="publish", draft=1, revision=1, value=""),
                    state,
                    session,
                    1,
                    None,
                )
            task = asyncio.create_task(operation)
            available = False
            try:
                await asyncio.wait_for(entered.wait(), timeout=2)
                try:
                    async with engine.connect() as independent:
                        available = await independent.scalar(text("SELECT 1")) == 1
                except PoolTimeout:
                    pass
            finally:
                release.set()
                await task
            assert available, "Another shop must acquire DB capacity while this reply waits"
    finally:
        await engine.dispose()
