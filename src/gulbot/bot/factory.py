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
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import BaseStorage, DefaultKeyBuilder
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.fsm.strategy import FSMStrategy
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gulbot.bot.channel import FinalizeScheduler, build_channel_router
from gulbot.bot.middlewares import ChatGateMiddleware, CustomerMiddleware, DbSessionMiddleware
from gulbot.bot.routers import build_routers
from gulbot.config import get_settings
from gulbot.worker.debounce import schedule_album_finalize

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


#: Seconds before a Bot API request is given up on. aiogram's default is 60.
#:
#: Found in the pre-deployment audit, pass 5: in a Telegram outage every send
#: waits out this whole timeout before failing, so it is the unit the worst-case
#: tick is measured in. Fifteen seconds is far longer than a healthy sendMessage
#: or sendPhoto by file_id takes, and a quarter of the time lost per outage send.
#:
#: Long polling is unaffected: aiogram requests getUpdates with
#: `session.timeout + polling_timeout`, so the poll still waits its full window.
#: Downloads are unaffected too: `download_file` carries its own timeout.
TELEGRAM_REQUEST_TIMEOUT = 15


def build_bot(token: str | None = None) -> Bot:
    """A new Bot. `token` None means the process's BOT_TOKEN.

    Uncached on purpose; see worker/tasks.py. A token is passed only by
    `gulbot.bot.registry`, which picks one per shop.
    """
    return Bot(
        token=token if token is not None else get_settings().bot_token.get_secret_value(),
        session=AiohttpSession(timeout=TELEGRAM_REQUEST_TIMEOUT),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def process_token_is_set() -> bool:
    """Whether `build_bot()` with no token has a BOT_TOKEN to build from.

    Beside `build_bot` so the two always read the same settings -- the
    registry asks this before falling back, rather than letting aiogram fail
    on an empty token somewhere less clear.
    """
    return bool(get_settings().bot_token.get_secret_value())


def build_storage() -> RedisStorage:
    """FSM storage, with the BOT ID IN EVERY KEY.

    C3 of AUDIT_MULTI_TENANT.md, reproduced before it was fixed. aiogram's
    default key builder omits the bot id, giving `fsm:<chat_id>:<user_id>` --
    and in a private chat the chat id IS the user id, so the key named the
    person rather than the conversation. Two shops' bots sharing this Redis read
    and wrote the same state: shop B resumed shop A's half-finished order and
    wrote a shop-B order for shop A's bouquet. Keys are now
    `fsm:<bot_id>:<chat_id>:<user_id>:<part>`.

    MemoryStorage never had this bug -- it keys on the whole StorageKey, bot id
    included -- which is why the tests, which all use it, never saw it.
    `tests/test_fsm_isolation.py` runs against real Redis for that reason.
    """
    settings = get_settings()
    return RedisStorage(
        redis=Redis.from_url(settings.redis_url(settings.redis_db_fsm)),
        key_builder=DefaultKeyBuilder(with_bot_id=True),
    )


def build_dispatcher(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    shop_id: int,
    storage: BaseStorage | None = None,
    schedule_finalize: FinalizeScheduler | None = None,
) -> Dispatcher:
    # USER_IN_CHAT rather than aiogram's default CHAT strategy. In a private
    # chat the two are identical -- chat_id IS the user id -- so no customer
    # conversation changes. In a GROUP they differ, and the default would
    # give every admin one shared FSM state: one of them typing a rejection
    # reason would put the whole group into that state, and the next
    # person's message would be read as their reason.
    dispatcher = (
        Dispatcher(storage=storage, fsm_strategy=FSMStrategy.USER_IN_CHAT)
        if storage is not None
        else Dispatcher(fsm_strategy=FSMStrategy.USER_IN_CHAT)
    )

    # Outer: run once per update, before routing. The chat gate is FIRST so a
    # message in the shop's admin group opens no session and creates no
    # customer -- see ChatGateMiddleware for what it used to do instead.
    dispatcher.update.outer_middleware(ChatGateMiddleware())
    dispatcher.update.outer_middleware(DbSessionMiddleware(session_factory))
    dispatcher.update.outer_middleware(CustomerMiddleware(shop_id))

    # Injected as workflow data so the channel handlers stay plain module-level
    # functions. Tests hand in a recorder; production hands in the Redis-backed
    # debouncer, which is only touched when an album actually arrives.
    dispatcher["schedule_finalize"] = schedule_finalize or schedule_album_finalize

    # The channel indexer goes FIRST, and it is safe to say that without
    # qualification: it registers only `channel_post` and `edited_channel_post`,
    # which no customer-facing router observes. It can neither shadow nor be
    # shadowed, and the sweep's count is unchanged by its presence.
    dispatcher.include_router(build_channel_router())

    for router in build_routers():
        dispatcher.include_router(router)
    return dispatcher
