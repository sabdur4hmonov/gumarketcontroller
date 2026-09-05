"""Choosing one bouquet from the catalogue CP8 indexes.

CP9's read side. It knows nothing about reminders, Telegram or rendering -- it
answers one question, "which product should this customer be shown", and the
send path composes the message around the answer.

THE RANKING RULE, stated rather than implied:

    1. a product tagged with the recipient's `preferred_hashtag`, resolved
       through `hashtag_aliases`;
    2. failing that, the most recently indexed product.

Ties break on `indexed_at DESC`. That is the whole rule. It is expressed as one
`ORDER BY` rather than two queries so that "preference beats recency" is a
property of the SQL and not of the order two calls happen to run in.

NO FUZZY MATCHING, and this is a decision rather than an omission. pg_trgm needs
`CREATE EXTENSION`, which needs elevated database rights that a future host may
not grant, and its similarity threshold would have to be guessed before there is
any usage data to tune against. Showing the WRONG flower is worse than showing
none. `hashtag_aliases` handles synonyms and cross-script spellings as data, and
scales to as many flower types as the shop cares to add -- it is a different
tool, not a weaker one. Revisit with real "no match" query logs, not before.

WHAT IS EXCLUDED, and why each one matters:

    finalized_at IS NULL   a provisional album. Its name, price and tags are
                           not settled yet; CP8 creates the row before it can
                           know them.
    active = false         the shop hid it, or CP10 rejected an order for it.
    deleted_at IS NOT NULL nothing writes this yet. Filtered defensively now
                           because adding the column to a query later is free
                           and forgetting it is a silent bug.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Boolean, ColumnElement, case, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.catalog.prices import PriceConfidence
from gulbot.models.product import Product, ProductHashtag
from gulbot.services.hashtag_aliases import resolve_alias


@dataclass(frozen=True)
class Bouquet:
    """One product, reduced to what a reminder needs."""

    product_id: int
    name: str
    price_uzs: int | None
    price_confidence: str
    telegram_file_id: str

    @property
    def has_price(self) -> bool:
        """A price only counts if the parser was willing to stand behind it."""
        return self.price_uzs is not None and self.price_confidence != PriceConfidence.NONE.value


async def choose_bouquet(
    session: AsyncSession, *, shop_id: int, preferred_hashtag: str | None = None
) -> Bouquet | None:
    """The best product for this customer, or None if the catalogue is empty.

    None is an ordinary answer, not an error. A shop that has not posted
    anything yet still gets its reminders -- the send path falls back to bare
    text, exactly as CP6 sends it.
    """
    tag = None
    if preferred_hashtag:
        # Query-side alias resolution. Stored tags are never rewritten, so the
        # alias table stays editable without a re-index -- see CP8.
        resolved = await resolve_alias(session, shop_id=shop_id, tag=preferred_hashtag)
        tag = resolved or None

    matched: ColumnElement[bool]
    if tag is None:
        matched = literal(False, Boolean)
        query = select(Product)
    else:
        # LEFT JOIN, not a filter: an unmatched product is still a candidate,
        # it just sorts below a matched one. product_hashtags is unique on
        # (product_id, hashtag_normalized), so this cannot duplicate rows.
        joined = select(Product).outerjoin(
            ProductHashtag,
            (ProductHashtag.product_id == Product.id) & (ProductHashtag.hashtag_normalized == tag),
        )
        matched = case((ProductHashtag.product_id.is_not(None), True), else_=False)
        query = joined

    product = await session.scalar(
        query.where(
            Product.shop_id == shop_id,
            Product.active.is_(True),
            Product.deleted_at.is_(None),
            Product.finalized_at.is_not(None),
        )
        .order_by(matched.desc(), Product.indexed_at.desc(), Product.id.desc())
        .limit(1)
    )
    if product is None:
        return None

    return Bouquet(
        product_id=product.id,
        name=product.name,
        price_uzs=product.price_uzs,
        price_confidence=product.price_confidence,
        telegram_file_id=product.telegram_file_id,
    )
