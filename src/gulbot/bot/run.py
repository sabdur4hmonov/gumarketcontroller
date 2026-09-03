"""Long-polling entrypoint for local development."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gulbot.bot.factory import ALLOWED_UPDATES, build_bot, build_dispatcher, build_storage
from gulbot.config import get_settings
from gulbot.db.session import build_session_factory
from gulbot.models.shop import Shop

log = logging.getLogger("gulbot")


async def resolve_single_shop(
    session_factory: async_sessionmaker[AsyncSession],
) -> int:
    """v1 runs one shop. Fail loudly rather than guessing which one."""
    async with session_factory() as session:
        ids = list(await session.scalars(select(Shop.id).order_by(Shop.id)))
    if len(ids) != 1:
        raise RuntimeError(
            f"expected exactly one shop, found {len(ids)}. Run: python -m gulbot.cli.seed"
        )
    return int(ids[0])


async def main() -> None:
    logging.basicConfig(
        level=get_settings().log_level,
        format="%(asctime)s %(levelname)-5s %(name)s %(message)s",
    )
    session_factory = build_session_factory()
    shop_id = await resolve_single_shop(session_factory)

    bot = build_bot()
    dispatcher = build_dispatcher(
        session_factory=session_factory, shop_id=shop_id, storage=build_storage()
    )

    me = await bot.get_me()
    # Identity only. The token must never reach the logs.
    log.info("starting as @%s (id=%s) for shop_id=%s", me.username, me.id, shop_id)

    try:
        await dispatcher.start_polling(bot, allowed_updates=ALLOWED_UPDATES)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
