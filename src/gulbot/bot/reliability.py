"""Bounded handler work, poller progress and per-bot reply pacing."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.client.session.middlewares.base import BaseRequestMiddleware, NextRequestMiddlewareType
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import Response, TelegramMethod
from aiogram.methods.base import TelegramType

log = logging.getLogger("gulbot.reliability")


@dataclass
class PollProgress:
    last_progress: float = field(default_factory=time.monotonic)
    consecutive_failures: int = 0
    error_type: str = ""


class PollObserver(BaseRequestMiddleware):
    def __init__(self, progress: PollProgress) -> None:
        self.progress = progress

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[TelegramType],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Response[TelegramType]:
        polling = method.__api_method__ in {"getMe", "getUpdates"}
        try:
            result = await make_request(bot, method)
        except Exception as error:
            if polling:
                self.progress.consecutive_failures += 1
                self.progress.error_type = type(error).__name__
                self.progress.last_progress = time.monotonic()
            raise
        if polling:
            self.progress.last_progress = time.monotonic()
            self.progress.consecutive_failures = 0
            self.progress.error_type = ""
        return result


class HandlerDeadline(BaseMiddleware):
    def __init__(self, shop_id: int, *, seconds: float = 25) -> None:
        self.shop_id = shop_id
        self.seconds = seconds
        self.handled = 0
        self.errors = 0
        self.timeouts = 0
        self.samples: deque[float] = deque(maxlen=128)

    def snapshot(self) -> dict[str, Any]:
        ordered = sorted(self.samples)
        quantile = None
        if ordered:
            position = (len(ordered) - 1) * 0.95
            left = int(position)
            quantile = ordered[left] + (
                ordered[min(left + 1, len(ordered) - 1)] - ordered[left]
            ) * (position - left)
        return {
            "handled": self.handled,
            "errors": self.errors,
            "timeouts": self.timeouts,
            "p95_ms": quantile,
            "samples": len(ordered),
        }

    async def __call__(
        self, handler: Callable[..., Awaitable[Any]], event: Any, data: dict[str, Any]
    ) -> Any:
        started = time.monotonic()
        outcome = "ok"
        error_module = ""
        deadline = asyncio.timeout(self.seconds)
        try:
            async with deadline:
                return await handler(event, data)
        except TimeoutError as error:
            error_module = type(error).__module__
            if deadline.expired():
                outcome = "timeout"
                self.timeouts += 1
            else:
                outcome = type(error).__name__
                self.errors += 1
            return None
        except Exception as error:
            outcome = type(error).__name__
            error_module = type(error).__module__
            self.errors += 1
            return None
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        finally:
            self.handled += 1
            elapsed = (time.monotonic() - started) * 1000
            self.samples.append(round(elapsed, 2))
            payload = {
                "event": "slow_handler" if elapsed > 250 else "handler",
                "shop_id": self.shop_id,
                "latency_ms": round(elapsed, 2),
                "outcome": outcome,
                "error_module": error_module,
            }
            if outcome != "ok" or elapsed > 250:
                log.warning(json.dumps(payload))
            else:
                log.info(json.dumps(payload))


class ReplyPolicy(BaseRequestMiddleware):
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.clock = clock
        self.sleep = sleep
        self.next_global: dict[int, float] = {}
        self.chats: dict[tuple[int, str], tuple[asyncio.Lock, float]] = {}

    async def _request(
        self,
        make_request: NextRequestMiddlewareType[TelegramType],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Response[TelegramType]:
        deadline = self.clock() + 10
        for attempt in range(3):
            try:
                return await make_request(bot, method)
            except TelegramRetryAfter as error:
                wait = max(0.0, float(error.retry_after))
                if attempt == 2 or self.clock() + wait > deadline:
                    raise
                await self.sleep(wait)
        raise RuntimeError("Unreachable reply retry state")

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[TelegramType],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Response[TelegramType]:
        if method.__api_method__ not in {"sendMessage", "sendPhoto", "sendMediaGroup"}:
            return await make_request(bot, method)
        chat = getattr(method, "chat_id", None)
        # Username targets do not carry group type; conservative group pacing.
        numeric_chat = int(str(chat)) if str(chat).lstrip("-").isdigit() else -1
        key = (bot.id, str(chat))
        if key not in self.chats:
            if len(self.chats) >= 4096:
                now = self.clock()
                self.chats = {
                    k: v for k, v in self.chats.items() if v[0].locked() or v[1] > now - 60
                }
                if len(self.chats) >= 4096:
                    raise RuntimeError("Too many active reply chats")
            self.chats[key] = (asyncio.Lock(), 0)
        lock, _ = self.chats[key]
        async with lock:
            now = self.clock()
            due = max(now, self.chats[key][1], self.next_global.get(bot.id, 0))
            cost = len(getattr(method, "media", [])) or 1
            self.next_global[bot.id] = due + cost / 28
            if due > now:
                await self.sleep(due - now)
            interval = 3 if numeric_chat < 0 else 1
            self.chats[key] = (lock, self.clock() + interval * cost)
            return await self._request(make_request, bot, method)
