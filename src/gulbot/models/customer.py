"""Customers, scoped to a shop."""

from __future__ import annotations

from datetime import time
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    SmallInteger,
    String,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from gulbot.db.base import Base, IdMixin, TimestampMixin

# What CP5 must apply when a customer never answered the preference
# questions. Stored here rather than in the schema so that NULL keeps
# meaning "not asked" -- a server default would make "answered 3" and
# "never asked" indistinguishable.
DEFAULT_REMINDER_COUNT = 3
DEFAULT_SEND_TIME = time(20, 0)

# reminder_count -> offsets. CP5 owns the wiring; this is the agreed mapping.
REMINDER_COUNT_OFFSETS: dict[int, tuple[int, ...]] = {
    1: (0,),
    2: (-1, 0),
    3: (-7, -1, 0),
}

# The only send times offered. Colons cannot appear in aiogram callback
# data, so the buttons carry names and this maps them to real times.
SEND_TIME_CHOICES: dict[str, time] = {
    "morning": time(9, 0),
    "noon": time(13, 0),
    "evening": time(20, 0),
}


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

    # Reminder preferences. NULLABLE ON PURPOSE: onboarding must never block on
    # them, and NULL is how CP5 tells "skipped" from "chose 3". CP3.6 only
    # STORES these; nothing reads them until CP5.
    reminder_count: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    preferred_send_time: Mapped[time | None] = mapped_column(Time, nullable=True)
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
        CheckConstraint(
            "reminder_count IS NULL OR reminder_count IN (1, 2, 3)",
            name="reminder_count_known",
        ),
        CheckConstraint(
            "preferred_send_time IS NULL OR preferred_send_time IN ('09:00', '13:00', '20:00')",
            name="preferred_send_time_known",
        ),
    )

    def __repr__(self) -> str:
        return f"<Customer id={getattr(self, 'id', None)} tg={self.telegram_user_id}>"
