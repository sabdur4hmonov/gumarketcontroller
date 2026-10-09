"""The gift: premium share-page parts, unlocked for a customer AT ONE SHOP by
their first confirmed order there (CP18). Rules: gulbot.services.premium."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKeyConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from gulbot.db.base import Base


class PremiumUnlock(Base):
    """One per (shop, customer): the composite FKs make an unlock that joins a
    customer or an order of ANOTHER shop unrepresentable."""

    __tablename__ = "premium_unlocks"

    shop_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    customer_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    #: The confirmed order that granted it.
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["customer_id", "shop_id"],
            ["customers.id", "customers.shop_id"],
            ondelete="CASCADE",
        ),
        # CASCADE: an unlock never outlives the order that granted it. Orders
        # are not deleted in production; this keeps a hard delete (a test's
        # cleanup, an operator's psql) from being blocked by a gift.
        ForeignKeyConstraint(
            ["order_id", "shop_id"], ["orders.id", "orders.shop_id"], ondelete="CASCADE"
        ),
    )
