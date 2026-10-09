"""Premium parts of a share page, and the gift that unlocks them (CP18).

WHAT IS PREMIUM -- defined here and nowhere else:
  * PREMIUM_TEMPLATES: the ten designs CP17 added (photo-led, editorial,
    geometric, watercolour, vintage, black-and-white, children's, suzani,
    neon, deco). The ten CP16 designs stay free.
  * music (PREMIUM_FIELDS);
  * photos -- the gallery, and the Foto design's frame (`photos_are_premium`).
Everything else -- every kind of page, the date plan, sections, RSVP, the
wishes wall, editing at the same link -- is free for everyone.

HOW IT UNLOCKS: one of the customer's orders AT THIS SHOP is confirmed, while
the shop's gift rule (`shops.gift_premium_after_order`) is on. Then a row in
`premium_unlocks` (shop, customer) is written in the same transaction as the
confirmation. Per shop, never shared: the same person ordering at shop A
unlocks nothing at shop B -- the row carries the shop, and the composite FKs
make a cross-shop row unrepresentable.

GRANTED IS KEPT: turning the rule off stops new gifts; it takes none back.
Pages already using a premium part keep it (nothing is removed retroactively).
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.models.share_page import PAGE_TEMPLATES

PREMIUM_TEMPLATES: Final = frozenset(
    {
        "foto",
        "bold",
        "geometrik",
        "akvarel",
        "vintaj",
        "oqqora",
        "bolalar",
        "suzani",
        "neon",
        "deco",
    }
)
#: Page fields whose non-empty value is premium.
PREMIUM_FIELDS: Final = frozenset({"music"})
#: Any photo on a page (the gallery, the Foto frame) is premium.
PHOTOS_ARE_PREMIUM: Final = True

assert set(PAGE_TEMPLATES) >= PREMIUM_TEMPLATES, "a premium design that does not exist"


class PremiumLocked(Exception):
    """This customer has not unlocked premium at this shop."""


def is_premium_template(template: str | None) -> bool:
    return template in PREMIUM_TEMPLATES


async def unlocked(session: AsyncSession, *, shop_id: int, customer_id: int) -> bool:
    from gulbot.models.premium import PremiumUnlock

    found = await session.scalar(
        select(PremiumUnlock.customer_id).where(
            PremiumUnlock.shop_id == shop_id, PremiumUnlock.customer_id == customer_id
        )
    )
    return found is not None


async def require(session: AsyncSession, *, shop_id: int, customer_id: int) -> None:
    if not await unlocked(session, shop_id=shop_id, customer_id=customer_id):
        raise PremiumLocked()


async def grant_for_confirmed_order(session: AsyncSession, *, shop_id: int, order_id: int) -> bool:
    """Called in the transaction that confirms the order. Returns True if this
    confirmation unlocked premium (first confirmed order, rule on)."""
    granted = await session.scalar(
        text(
            """
            INSERT INTO premium_unlocks (shop_id, customer_id, order_id)
            SELECT o.shop_id, o.customer_id, o.id
              FROM orders o JOIN shops s ON s.id = o.shop_id
             WHERE o.id = :o AND o.shop_id = :s AND s.gift_premium_after_order
            ON CONFLICT (shop_id, customer_id) DO NOTHING
            RETURNING customer_id
            """
        ),
        {"o": order_id, "s": shop_id},
    )
    return granted is not None
