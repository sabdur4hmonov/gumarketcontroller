"""Seed the hashtag alias fixture into every shop. Idempotent."""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from gulbot.db.session import build_session_factory, session_scope
from gulbot.models.shop import Shop
from gulbot.services.hashtag_aliases import seed_hashtag_aliases


async def seed_all(*, database: str | None = None) -> dict[int, str]:
    factory = build_session_factory(database)
    summary: dict[int, str] = {}
    async with session_scope(factory) as session:
        for shop_id in await session.scalars(select(Shop.id)):
            result = await seed_hashtag_aliases(session, shop_id=shop_id)
            summary[shop_id] = (
                f"inserted={result.inserted} updated={result.updated} "
                f"unchanged={result.unchanged} skipped={result.skipped}"
            )
    return summary


def main() -> None:
    for shop_id, line in asyncio.run(seed_all()).items():
        print(f"shop {shop_id}: {line}")


if __name__ == "__main__":
    main()
