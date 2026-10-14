"""Experimental task-owned HTTP batch; NOT wired to worker send paths.

Activate only after a clean25-shop attribution profile and real two-loop I/O
proof. Bot identity/pacing remain per token; only the HTTP session is shared.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode

from gulbot.bot.factory import TELEGRAM_REQUEST_TIMEOUT
from gulbot.bot.registry import BotRegistry, TokenResolver
from gulbot.bot.reliability import ReplyPolicy
from gulbot.config import get_settings

SessionFactory = Callable[[], BaseSession]
SessionBotFactory = Callable[[str | None, BaseSession], Bot]


def batch_session() -> BaseSession:
    session = AiohttpSession(timeout=TELEGRAM_REQUEST_TIMEOUT)
    session.middleware.register(ReplyPolicy())
    return session


def bound_bot(token: str | None, session: BaseSession) -> Bot:
    return Bot(
        token=token if token is not None else get_settings().bot_token.get_secret_value(),
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


class TaskBotBatch:
    def __init__(
        self, token_for: TokenResolver, session: BaseSession, bot_factory: SessionBotFactory
    ) -> None:
        self._loop = asyncio.get_running_loop()
        self._session = session
        self._registry: BotRegistry | None = BotRegistry(
            token_for=token_for, bot_factory=lambda token: bot_factory(token, session)
        )

    def bot_for(self, shop_id: int) -> Bot:
        if self._registry is None or asyncio.get_running_loop() is not self._loop:
            raise RuntimeError("Batch clients belong only to their open task loop")
        return self._registry.bot_for(shop_id)

    async def close(self) -> None:
        if self._registry is None:
            return
        if asyncio.get_running_loop() is not self._loop:
            raise RuntimeError("Only the owning task loop may close the HTTP batch")
        self._registry = None
        await self._session.close()


@asynccontextmanager
async def task_bot_batch(
    *,
    token_for: TokenResolver,
    session_factory: SessionFactory = batch_session,
    bot_factory: SessionBotFactory = bound_bot,
) -> AsyncIterator[TaskBotBatch]:
    batch = TaskBotBatch(token_for, session_factory(), bot_factory)
    try:
        yield batch
    finally:
        await batch.close()
