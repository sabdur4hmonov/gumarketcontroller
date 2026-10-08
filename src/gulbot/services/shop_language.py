"""The language a shop's own people read. L2 of AUDIT_MULTI_TENANT.md.

SHOP-FACING, NOT CUSTOMER-FACING. A customer has `customers.lang` and is
spoken to in it. This is for what the SHOP reads: the order card and the
delivery pings in its group, the stall and dead-letter alerts, the daily
summary, and the admin group's buttons and stamped outcomes. Every one of those
asks this function, per shop, and none of them names a language itself.

THE ONE PLACE IT IS READ: `shops.lang` (migration 4b6e1d9c2a07, CP-MT2's
follow-up). Every existing shop got 'uz' -- what every one of those paths
hardcoded before -- and onboarding stores the owner's language for a new one.
A shop that cannot be found reads DEFAULT_LANGUAGE rather than failing: these
are alerts and summaries, and a missing word is better than a missing alert.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.i18n.catalog import DEFAULT_LANGUAGE
from gulbot.models.shop import Shop


async def shop_language(session: AsyncSession, *, shop_id: int) -> str:
    """The language for everything this shop's own people read."""
    lang = await session.scalar(select(Shop.lang).where(Shop.id == shop_id))
    return str(lang) if lang else DEFAULT_LANGUAGE
