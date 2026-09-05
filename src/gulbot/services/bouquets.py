"""Choosing one bouquet from the catalogue CP8 indexes.

CP9's read side. It knows nothing about reminders, Telegram or rendering -- it
answers one question, "which product should this customer be shown", and the
send path composes the message around the answer.

THE RANKING RULE, stated rather than implied:

    1. a product one of whose tags RESOLVES to the recipient's
       `preferred_hashtag`, through `hashtag_aliases`;
    2. failing that, the most recently indexed product.

Ties break on `indexed_at DESC`. That is the whole rule. It is expressed as one
`ORDER BY` rather than two queries so that "preference beats recency" is a
property of the SQL and not of the order two calls happen to run in.

WHICH WAY THE ALIAS LOOKUP RUNS, because CP9 got this backwards and the tier
silently never fired. `hashtag_aliases` maps synonym -> canonical, and
`resolve_alias` walks it that way for customer TEXT. But the preference is
already canonical (`preferred_hashtag` is CHECK-constrained to the presets), and
the STORED tag is whatever the shop typed -- CP8 never rewrites it. So the
resolution has to be applied to the STORED side:

    stored '#gulkinder' --alias--> 'atirgul'  ==  preset 'atirgul'   MATCH

Comparing the preset to the raw stored tag, as CP9 did, can only ever match a
shop whose own vocabulary already happens to be ours. Proven before the fix:
with `gulkinder -> atirgul` seeded, a rose tagged `#gulkinder` still lost to an
unrelated newer product.

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

from sqlalchemy import Boolean, ColumnElement, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.catalog.prices import PriceConfidence
from gulbot.models.product import HashtagAlias, Product, ProductHashtag
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
    target = None
    if preferred_hashtag:
        # Resolve the PRESET too, so both sides of the comparison are canonical.
        # Presets are canonicals already, so this is identity today -- it is here
        # so the rule is "canonical == canonical" rather than "canonical ==
        # whatever the preset happened to be".
        resolved = await resolve_alias(session, shop_id=shop_id, tag=preferred_hashtag)
        target = resolved or None

    matched: ColumnElement[bool]
    if target is None:
        matched = literal(False, Boolean)
    else:
        # CP9.5. The stored tag is resolved FORWARD and compared to the
        # canonical preset -- not the other way round, which is what CP9 did and
        # why its preference tier never fired in practice.
        #
        # CP8 stores tags exactly as the shop wrote them. So a shop tagging its
        # roses `#gulkinder`, or `#roza`, or `#rose`, stores that word; the
        # customer's preset is `atirgul`. Comparing those two strings can only
        # match a shop whose vocabulary already happens to be ours. Resolving
        # the STORED side through `hashtag_aliases` is what makes an alias row
        # (`gulkinder -> atirgul`) close the gap, and it needs no change to the
        # preset CHECK, the preference buttons, or the alias table's direction.
        #
        # EXISTS rather than a join: a product has several tags, and a join
        # would return it once per tag. Only "does ANY tag resolve to the
        # preset" matters.
        matched = (
            select(literal(1))
            .select_from(ProductHashtag)
            .outerjoin(
                HashtagAlias,
                (HashtagAlias.shop_id == shop_id)
                & (HashtagAlias.alias_normalized == ProductHashtag.hashtag_normalized),
            )
            .where(
                ProductHashtag.product_id == Product.id,
                func.coalesce(HashtagAlias.canonical_hashtag, ProductHashtag.hashtag_normalized)
                == target,
            )
            .exists()
        )

    product = await session.scalar(
        select(Product)
        .where(
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
