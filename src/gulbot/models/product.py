"""The shop's catalogue: bouquets, their tags, and the synonym table.

Nothing writes to these yet. CP8 fills `products` from channel posts, CP9
searches them. What matters now is that the constraints CP8 will lean on exist
before CP8 needs them, because they are the difference between an album arriving
as five updates becoming one product or five.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from gulbot.catalog.prices import PriceConfidence
from gulbot.db.base import Base, IdMixin, TimestampMixin


class ProductSource(StrEnum):
    """Where the row came from.

    'channel' rows are owned by the indexer and may be overwritten by an
    edited_channel_post; 'manual' rows are owned by a human and must not be.
    """

    MANUAL = "manual"
    CHANNEL = "channel"


#: Rendered into the CHECK constraints, so the enum and the database cannot
#: drift apart. tests/test_check_constraints.py asserts they have not.
PRODUCT_SOURCES_SQL = ", ".join(f"'{s.value}'" for s in ProductSource)
PRICE_CONFIDENCE_SQL = ", ".join(f"'{c.value}'" for c in PriceConfidence)

HASHTAG_MAX_LENGTH = 64


class Product(IdMixin, TimestampMixin, Base):
    __tablename__ = "products"

    shop_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shops.id", ondelete="RESTRICT"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)

    #: NULLABLE on purpose. An unpriced post is still a product: it is indexed,
    #: shown, and captioned "narx operator tomonidan tasdiqlanadi". Dropping
    #: unpriced posts would silently hide half a shop's catalogue.
    price_uzs: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    price_confidence: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=text("'none'")
    )

    telegram_file_id: Mapped[str] = mapped_column(Text, nullable=False)

    source: Mapped[str] = mapped_column(String(16), nullable=False)

    #: Set for channel rows. NULL for manual ones, which is why the uniqueness
    #: below is per shop and tolerates NULLs.
    channel_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    #: Telegram's album identifier. Five photos posted together arrive as five
    #: updates sharing one of these, with the caption only on the first.
    media_group_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    #: The caption exactly as posted. Kept so a parser improvement can be
    #: re-run over history without re-reading the channel, which the Bot API
    #: does not allow.
    caption_raw: Mapped[str | None] = mapped_column(Text, nullable=True)

    indexed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    #: Set by the nightly sweep when a post can no longer be copied, i.e. it
    #: was deleted from the channel. Deletions produce no update, so this is
    #: the only way to notice.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: Manual disable, distinct from deleted_at: the shop can hide an item that
    #: still exists in the channel, and CP10 marks one inactive when an order
    #: for it is rejected.
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    __table_args__ = (
        # CP1's tenancy pattern: children reference (id, shop_id).
        UniqueConstraint("id", "shop_id"),
        # Redelivery idempotency. Telegram may deliver the same channel_post
        # twice; the second insert conflicts instead of creating a twin.
        UniqueConstraint("shop_id", "channel_message_id"),
        CheckConstraint(f"source IN ({PRODUCT_SOURCES_SQL})", name="source_known"),
        CheckConstraint(
            f"price_confidence IN ({PRICE_CONFIDENCE_SQL})", name="price_confidence_known"
        ),
        # A price and its confidence have to agree. "high confidence, no price"
        # is not a state that means anything.
        CheckConstraint(
            "(price_uzs IS NULL) = (price_confidence = 'none')",
            name="price_matches_confidence",
        ),
        CheckConstraint("price_uzs IS NULL OR price_uzs > 0", name="price_positive"),
        # A channel row must say which message it came from; a manual row
        # must not pretend to.
        CheckConstraint(
            "(source = 'channel') OR (channel_message_id IS NULL)",
            name="only_channel_rows_have_a_message_id",
        ),
        Index("ix_products_shop_active", "shop_id", "active"),
        # Partial: many products legitimately have no album at all, and NULLs
        # would otherwise all collide under a plain unique constraint... they
        # would not in Postgres, but stating the intent keeps the index small
        # and makes the album anchor explicit for CP8.
        Index(
            "uq_products_shop_media_group",
            "shop_id",
            "media_group_id",
            unique=True,
            postgresql_where=text("media_group_id IS NOT NULL"),
        ),
    )

    def __repr__(self) -> str:
        return f"<Product id={getattr(self, 'id', None)} name={self.name!r}>"


class ProductHashtag(IdMixin, Base):
    """One normalised tag on one product."""

    __tablename__ = "product_hashtags"

    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    product_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    hashtag_normalized: Mapped[str] = mapped_column(String(HASHTAG_MAX_LENGTH), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["product_id", "shop_id"],
            ["products.id", "products.shop_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("product_id", "hashtag_normalized"),
        # Never store the empty string: normalize_hashtag returns "" for a tag
        # that is only digits, and those must be dropped, not stored.
        CheckConstraint("length(hashtag_normalized) > 0", name="hashtag_not_blank"),
        # The search path: given a tag, find products in this shop.
        Index("ix_product_hashtags_lookup", "shop_id", "hashtag_normalized"),
    )

    def __repr__(self) -> str:
        return f"<ProductHashtag {self.hashtag_normalized!r}>"


class HashtagAlias(IdMixin, Base):
    """Synonym -> canonical tag, seeded from a versioned fixture.

    This is where cross-script and cross-language matching lives: роза, rose
    and roza all point at atirgul. Deliberately DATA rather than code, so the
    shop can correct it without a deploy, and so normalize_hashtag does not
    have to transliterate.
    """

    __tablename__ = "hashtag_aliases"

    shop_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shops.id", ondelete="CASCADE"), nullable=False
    )
    alias_normalized: Mapped[str] = mapped_column(String(HASHTAG_MAX_LENGTH), nullable=False)
    canonical_hashtag: Mapped[str] = mapped_column(String(HASHTAG_MAX_LENGTH), nullable=False)

    #: Which fixture version wrote this row, so a reseed can tell its own rows
    #: from ones a human added by hand.
    fixture_version: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("shop_id", "alias_normalized"),
        CheckConstraint("length(alias_normalized) > 0", name="alias_not_blank"),
        CheckConstraint("length(canonical_hashtag) > 0", name="canonical_not_blank"),
        # An alias pointing at itself is a no-op row that would make the lookup
        # ambiguous about whether a tag is canonical.
        CheckConstraint(
            "alias_normalized <> canonical_hashtag", name="alias_differs_from_canonical"
        ),
        Index("ix_hashtag_aliases_lookup", "shop_id", "alias_normalized"),
    )

    def __repr__(self) -> str:
        return f"<HashtagAlias {self.alias_normalized!r} -> {self.canonical_hashtag!r}>"
