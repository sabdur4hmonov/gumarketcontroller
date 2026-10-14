"""Off-loop TLS construction; socket use and disposal stay in the caller's loop."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from typing import TypeVar

from aiogram import Bot

from gulbot.services.offload import run_cpu

Token = TypeVar("Token")


async def close_bot(bot: Bot) -> None:
    with contextlib.suppress(Exception):
        await asyncio.wait_for(bot.session.close(), timeout=5)


async def create_bot(factory: Callable[[Token], Bot], token: Token, *, seconds: float = 20) -> Bot:
    # Shield running pure TLS work so cancellation cannot discard its result.
    # A late result is disposed on THIS loop; no async client is cached globally.
    construction = asyncio.create_task(run_cpu(factory, token))
    try:
        return await asyncio.wait_for(asyncio.shield(construction), timeout=seconds)
    except BaseException:

        def discard(done: asyncio.Task[Bot]) -> None:
            if not done.cancelled() and done.exception() is None:
                asyncio.create_task(close_bot(done.result()))

        construction.add_done_callback(discard)
        raise
