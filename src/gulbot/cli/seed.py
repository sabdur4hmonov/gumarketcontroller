"""Idempotent dev seed: create the single local shop if it is absent.

Safe to run repeatedly -- it never overwrites an existing shop's configuration,
because doing so would silently reset working hours someone tuned by hand.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from gulbot.db.session import build_session_factory, session_scope
from gulbot.models.shop import DEFAULT_WORKING_HOURS, Shop

DEV_SHOP_NAME = "Gulbot Dev Shop"


async def seed_dev_shop(*, database: str | None = None) -> tuple[int, bool]:
    """Return (shop_id, created)."""
    factory = build_session_factory(database)
    async with session_scope(factory) as session:
        existing = await session.scalar(select(Shop).where(Shop.name == DEV_SHOP_NAME))
        if existing is not None:
            return existing.id, False
        shop = Shop(name=DEV_SHOP_NAME, working_hours=DEFAULT_WORKING_HOURS)
        session.add(shop)
        await session.flush()
        return shop.id, True


def main() -> None:
    shop_id, created = asyncio.run(seed_dev_shop())
    print(f"shop id={shop_id} {'created' if created else 'already existed'}")


if __name__ == "__main__":
    main()
