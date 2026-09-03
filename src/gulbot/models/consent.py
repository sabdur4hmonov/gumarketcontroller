"""Append-only consent ledger.

Rows are never updated or deleted. Withdrawal is a NEW row with granted=false,
so the history of what a customer agreed to, and when, stays intact.

`text_version` records WHICH wording they agreed to. When the consent text is
reworded later, existing rows still say exactly what was on screen at the time --
without it, a wording change silently rewrites everyone's past consent.
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from gulbot.db.base import Base, IdMixin


class ConsentType(StrEnum):
    STORE_DATES = "store_dates"


# Bump this whenever the consent WORDING changes, so old rows keep meaning what
# was actually on screen when the customer agreed. tests/test_consent.py pins
# the current text to this version and fails the build if the text is edited
# without a bump.
STORE_DATES_TEXT_VERSION = "store_dates.v1"


class ConsentSource(StrEnum):
    FIRST_OCCASION = "first_occasion"
    SETTINGS = "settings"


class ConsentEvent(IdMixin, Base):
    __tablename__ = "consent_events"

    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    type: Mapped[str] = mapped_column(String(32), nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    text_version: Mapped[str] = mapped_column(String(32), nullable=False)

    at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["customer_id", "shop_id"],
            ["customers.id", "customers.shop_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("type IN ('store_dates')", name="type_known"),
        CheckConstraint("source IN ('first_occasion', 'settings')", name="source_known"),
        Index("ix_consent_events_customer_type", "customer_id", "type"),
    )
