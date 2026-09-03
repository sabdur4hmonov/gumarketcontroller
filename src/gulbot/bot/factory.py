"""Build the Bot and the Dispatcher.

ALLOWED_UPDATES is declared explicitly. aiogram otherwise derives it from the
handlers currently registered, which means a channel indexer registered late or
conditionally would silently receive nothing -- the catalog would just stay
empty, with no error anywhere.
"""

from __future__ import annotations

from typing import Final

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gulbot.bot.middlewares import CustomerMiddleware, DbSessionMiddleware
from gulbot.bot.routers import build_routers
from gulbot.config import get_settings

ALLOWED_UPDATES: Final = [
    "message",
    "edited_message",
    "callback_query",
    "my_chat_member",
    "chat_member",
    # CP8 depends on these two. They are listed here from the start so the
    # indexer cannot be starved by handler-derived defaults.
    "channel_post",
    "edited_channel_post",
]


def build_bot() -> Bot:
    return Bot(
        token=get_settings().bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def build_storage() -> RedisStorage:
    settings = get_settings()
    return RedisStorage(redis=Redis.from_url(settings.redis_url(settings.redis_db_fsm)))


def build_dispatcher(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    shop_id: int,
    storage: BaseStorage | None = None,
) -> Dispatcher:
    dispatcher = Dispatcher(storage=storage) if storage is not None else Dispatcher()

    # Outer: run once per update, before routing.
    dispatcher.update.outer_middleware(DbSessionMiddleware(session_factory))
    dispatcher.update.outer_middleware(CustomerMiddleware(shop_id))

    for router in build_routers():
        dispatcher.include_router(router)
    return dispatcher
