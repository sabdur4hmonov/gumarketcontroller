"""Customers, scoped to a shop."""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from gulbot.db.base import Base, IdMixin, TimestampMixin


class CustomerStatus(StrEnum):
    ACTIVE = "active"
    BLOCKED = "blocked"  # customer blocked the bot
    STOPPED = "stopped"  # customer opted out of reminders


class Language(StrEnum):
    UZ = "uz"
    RU = "ru"


class Customer(IdMixin, TimestampMixin, Base):
    __tablename__ = "customers"

    # shops is the tenancy root, so this is a plain FK -- there is no composite
    # parent to point at.
    shop_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shops.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # False when the customer declined the contact-share button and typed the
    # number by hand. A legitimate choice (the Telegram-linked number is often
    # not the one they want a courier calling), so it never blocks an order --
    # it only marks the number as unverified on the shop's group card.
    phone_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    lang: Mapped[str] = mapped_column(String(2), nullable=False, server_default=text("'uz'"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'active'"))

    __table_args__ = (
        UniqueConstraint("shop_id", "telegram_user_id"),
        # Looks pointless while nothing references it. It is what lets occasions
        # (CP3) and orders (CP10) declare FOREIGN KEY (customer_id, shop_id),
        # which makes a cross-tenant row unrepresentable rather than merely
        # discouraged. Adding it later means auditing live data.
        UniqueConstraint("id", "shop_id"),
        CheckConstraint(
            "status IN ('active', 'blocked', 'stopped')",
            name="status_known",
        ),
        CheckConstraint("lang IN ('uz', 'ru')", name="lang_known"),
    )

    def __repr__(self) -> str:
        return f"<Customer id={getattr(self, 'id', None)} tg={self.telegram_user_id}>"
