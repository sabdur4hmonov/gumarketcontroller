"""The language a shop's own people read. L2 of AUDIT_MULTI_TENANT.md.

SHOP-FACING, NOT CUSTOMER-FACING. A customer has `customers.lang` and is
spoken to in it. This is for what the SHOP reads: the order card and the
delivery pings in its group, the stall and dead-letter alerts, the daily
summary, and the admin group's buttons and stamped outcomes. Every one of those
asks this function, per shop, and none of them names a language itself.

THE ONE PLACE THAT CHANGES. There is no `shops.lang` column yet: adding one is
a migration, planned in docs/CHECKPOINTS.md (CP-MT2, "Follow-up: shops.lang")
and deliberately not made on the branch that found the need. Until it exists
every shop reads DEFAULT_LANGUAGE -- exactly what every one of those paths
hardcoded before -- and the migration replaces this function's body and
nothing else.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.i18n.catalog import DEFAULT_LANGUAGE


async def shop_language(session: AsyncSession, *, shop_id: int) -> str:
    """The language for everything this shop's own people read.

    Takes the session and the shop now, though it reads neither yet, so that
    every caller is already shaped for the column: the follow-up migration
    changes this body to `SELECT lang FROM shops WHERE id = :shop_id`.
    """
    return DEFAULT_LANGUAGE
