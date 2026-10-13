"""Separate API, bot, and tick processes for CP25 baseline measurement."""

from __future__ import annotations

import asyncio
import os
import time
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.session.base import BaseSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.fsm.storage.base import DefaultKeyBuilder
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from gulbot.bot.run import SHOP_REFRESH_SECONDS, ShopPollers
from gulbot.config import get_settings
from gulbot.db.session import build_engine

from .db_meter import DbMeter
from .load_seed import DATABASE, NOW
from .resources import Resources, atomic_json

REDIS_INDEX = 15


def install_local_api(api: str) -> Callable[[], None]:
    """Change only the HTTP endpoint, preserving production factories/pools."""
    if urlparse(api).hostname != "127.0.0.1":
        raise ValueError("Only the owned localhost API is permitted")
    endpoint = TelegramAPIServer.from_base(api)
    base: Any = BaseSession
    client: Any = AiohttpSession
    original_init = base.__init__
    original_request = client.make_request

    def init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        self.api = endpoint

    async def request(self: Any, bot: Any, method: Any, *args: Any, **kwargs: Any) -> Any:
        if "CP25TEST" not in bot.token:
            raise ValueError("Real tokens are forbidden in this harness")
        self.api = endpoint
        return await original_request(self, bot, method, *args, **kwargs)

    base.__init__ = init
    client.make_request = request

    def restore() -> None:
        base.__init__ = original_init
        client.make_request = original_request

    return restore


class MeasuredRedis(Redis):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.ops: Counter[str] = Counter()
        self.total_ms = 0.0

    async def execute_command(self, *args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        try:
            return await super().execute_command(*args, **kwargs)  # type: ignore[no-untyped-call]
        finally:
            self.ops[str(args[0]).upper()] += 1
            self.total_ms += (time.perf_counter() - started) * 1000


async def bot_role(api: str, output: Path) -> None:
    resources = Resources()
    engine = build_engine(DATABASE)
    meter = DbMeter(engine)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    settings = get_settings()
    redis = MeasuredRedis.from_url(settings.redis_url(REDIS_INDEX))
    prefix = "cp25-load:" + os.environ["CP25_RUN_ID"]
    storage = RedisStorage(
        redis=redis, key_builder=DefaultKeyBuilder(prefix=prefix, with_bot_id=True)
    )
    restore_api = install_local_api(api)
    pollers = ShopPollers(sessions, storage=storage)
    startup = 0.0
    try:
        started = time.perf_counter()
        await pollers.sync()
        startup = time.perf_counter() - started
        resources.sample()
        await asyncio.to_thread(
            atomic_json,
            output / "bots-ready.json",
            {"shops": len(pollers.running), "startup_s": startup},
        )
        last_refresh = time.perf_counter()
        while not await asyncio.to_thread((output / "stop-bots").exists):
            resources.sample()
            if time.perf_counter() - last_refresh >= SHOP_REFRESH_SECONDS:
                await pollers.sync()
                last_refresh = time.perf_counter()
            await asyncio.sleep(0.1)
    finally:
        try:
            await pollers.stop()
        finally:
            try:
                await storage.close()
            finally:
                await engine.dispose()
                restore_api()
        await asyncio.to_thread(
            atomic_json,
            output / "bot-metrics.json",
            {
                "resources": resources.result(),
                "db": meter.result(),
                "redis_ops": dict(redis.ops),
                "redis_total_ms": round(redis.total_ms, 2),
                "startup_s": round(startup, 3),
            },
        )


async def worker_role(api: str, output: Path, shops: int) -> None:
    import gulbot.db.session as session_module
    from gulbot.worker import tasks as task_module

    tasks: Any = task_module

    resources = Resources()
    meters: list[DbMeter] = []
    original_engine = session_module.build_engine
    original_datetime = tasks.datetime

    def measured_engine(database: str | None = None) -> AsyncEngine:
        engine = original_engine(DATABASE)
        meters.append(DbMeter(engine))
        return engine

    class Clock(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> Any:
            return NOW if tz is not None else NOW.replace(tzinfo=None)

    session_module.build_engine = measured_engine
    restore_api = install_local_api(api)
    tasks.datetime = Clock
    ticks: list[dict[str, Any]] = []
    pings: list[dict[str, Any]] = []
    try:
        # Public task bodies include heartbeats and a fresh asyncio.run loop.
        # Execute them off this coordinator loop. Reusing one event loop or
        # registry would conceal task-lifetime defects and baseline costs.
        for _ in range((shops + 99) // 100):
            resources.sample()
            started = time.perf_counter()
            result = await asyncio.to_thread(tasks.send_due_reminders.run)
            ticks.append({"seconds": round(time.perf_counter() - started, 4), **result})
        for _ in range((shops + 99) // 100):
            resources.sample()
            started = time.perf_counter()
            result = await asyncio.to_thread(tasks.send_order_pings.run)
            pings.append({"seconds": round(time.perf_counter() - started, 4), **result})
    finally:
        session_module.build_engine = original_engine
        restore_api()
        tasks.datetime = original_datetime
        times = [value for meter in meters for value in meter.times_ms]
        from .resources import percentile

        db = {
            "queries": len(times),
            "query_total_ms": round(sum(times), 2),
            "query_p50_ms": percentile(times, 50),
            "query_p95_ms": percentile(times, 95),
            "query_p99_ms": percentile(times, 99),
            "peak_connections": max((m.peak_connections for m in meters), default=0),
            "peak_checked_out": max((m.peak_checked_out for m in meters), default=0),
        }
        await asyncio.to_thread(
            atomic_json,
            output / "worker-metrics.json",
            {
                "resources": resources.result(),
                "db": db,
                "reminder_ticks": ticks,
                "order_ticks": pings,
            },
        )
