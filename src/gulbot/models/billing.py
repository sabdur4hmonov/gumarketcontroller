"""The subscription ledger (CP18): one row per payment the platform owner
recorded by hand in the admin panel. Never edited; `shops.subscription_status`
and `shops.paid_until` are the current state, this is the history."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from gulbot.db.base import Base, IdMixin

PAYMENT_METHODS = ("cash", "card_transfer", "other")


class SubscriptionPayment(IdMixin, Base):
    __tablename__ = "subscription_payments"

    shop_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shops.id"), nullable=False)
    paid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    amount_uzs: Mapped[int] = mapped_column(BigInteger, nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    paid_until: Mapped[date] = mapped_column(Date, nullable=False)
    admin_telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    __table_args__ = (
        CheckConstraint("amount_uzs > 0", name="amount_positive"),
        CheckConstraint("method IN ('cash', 'card_transfer', 'other')", name="method_known"),
        Index("ix_subscription_payments_shop_paid", "shop_id", "paid_at"),
    )
