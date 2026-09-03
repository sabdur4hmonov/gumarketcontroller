"""A person a customer buys flowers for.

One recipient owns many occasions: a wife has a birthday AND an anniversary.
Before CP3.5 the person existed only as a repeated `occasions.label` string,
which made "add another date for the same person" impossible to express.

There is deliberately NO uniqueness on (customer_id, label). "Do'stim" is not a
name -- a customer may well have several friends -- so treating the label as an
identity would silently merge two different people.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from gulbot.db.base import Base, IdMixin, TimestampMixin

LABEL_MAX_LENGTH = 64


class Recipient(IdMixin, TimestampMixin, Base):
    __tablename__ = "recipients"

    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    label: Mapped[str] = mapped_column(String(LABEL_MAX_LENGTH), nullable=False)
    # Which preset the customer picked, or 'custom' for a typed label.
    type: Mapped[str] = mapped_column(String(16), nullable=False)

    # CP3.6 stores a normalised preset here (atirgul / tyulpan / lola / NULL).
    # CP9 uses it as a ranking hint. Nothing matches it against the real
    # catalogue yet, so the allowed-value CHECK arrives with CP3.6.
    preferred_hashtag: Mapped[str | None] = mapped_column(String(32), nullable=True)

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    __table_args__ = (
        ForeignKeyConstraint(
            ["customer_id", "shop_id"],
            ["customers.id", "customers.shop_id"],
            ondelete="CASCADE",
        ),
        # Lets occasions declare FOREIGN KEY (recipient_id, customer_id), which
        # makes "an occasion pointing at another customer's recipient"
        # unrepresentable rather than merely unlikely.
        UniqueConstraint("id", "customer_id"),
        CheckConstraint(
            "type IN ('wife', 'spouse', 'mother', 'father', 'child', 'friend', 'custom')",
            name="type_known",
        ),
        CheckConstraint("length(btrim(label)) > 0", name="label_not_blank"),
        Index("ix_recipients_customer_active", "customer_id", "active"),
    )

    def __repr__(self) -> str:
        return f"<Recipient id={getattr(self, 'id', None)} label={self.label!r}>"
