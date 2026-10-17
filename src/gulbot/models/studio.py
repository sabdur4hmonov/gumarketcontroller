"""Taklifnoma Studio (CP27): how a customer gets into the web creator, and the
record of what happens there.

The same design as the shop owner's panel (models/shop_panel.py), bound to ONE
customer of ONE shop:

    "Taklifnoma yaratish" in THAT shop's bot -> a studio_links row
    open the link, press Kirish                -> a studio_sessions row
    every /studio request                      -> that session, re-checked

TENANCY. Links and sessions name a customer through the composite FK
``(customer_id, shop_id) -> customers(id, shop_id)``, so a session cannot name
one shop while belonging to another shop's customer. The shop a session can
see comes from the link, and the link only from the shop's own bot.

Secrets are stored hashed (sha256 of 32 random bytes), as for /admin and /shop:
a dump of these tables hands out no way in. The audit log is append-only in
the database: a trigger refuses UPDATE, DELETE and TRUNCATE. It carries the
customer's id without a foreign key, so the log outlives a customer row.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from gulbot.db.base import Base, IdMixin
from gulbot.models.admin import HASH_LENGTH


class StudioLink(IdMixin, Base):
    """A one-time link a shop's bot sent to one of its customers."""

    __tablename__ = "studio_links"

    shop_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shops.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(HASH_LENGTH), nullable=False, unique=True)
    #: The shop bot's @username, so a page made in the studio links back to it.
    bot_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Set exactly once, by a compare-and-swap: the link is then spent.
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["customer_id", "shop_id"], ["customers.id", "customers.shop_id"], ondelete="CASCADE"
        ),
        CheckConstraint("expires_at > created_at", name="expires_after_created"),
        Index("ix_studio_links_shop_customer_created", "shop_id", "customer_id", "created_at"),
    )


class StudioSession(IdMixin, Base):
    """A customer's browser in the studio, for exactly one shop."""

    __tablename__ = "studio_sessions"

    shop_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shops.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(HASH_LENGTH), nullable=False, unique=True)
    #: Sent in every form; a POST without it is refused (CSRF).
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    bot_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["customer_id", "shop_id"], ["customers.id", "customers.shop_id"], ondelete="CASCADE"
        ),
        CheckConstraint("expires_at > created_at", name="expires_after_created"),
        Index("ix_studio_sessions_shop_customer", "shop_id", "customer_id"),
    )


class StudioAuditEntry(IdMixin, Base):
    """One thing that happened in the studio -- a link sent, a login, a refusal,
    a page made. Append-only."""

    __tablename__ = "studio_audit_log"

    shop_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shops.id"), nullable=False)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    #: NULL only for a refusal where nobody was identified.
    customer_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (Index("ix_studio_audit_log_shop_at", "shop_id", "at"),)


class StudioWebAppUse(IdMixin, Base):
    """One Telegram Mini App launch that opened a studio session (CP27.4).

    Telegram's initData is valid for an hour and could be replayed within it;
    each one opens at most ONE session: its own hash is stored (as sha256)
    under a UNIQUE constraint, and the insert is the compare-and-swap.
    Rows older than the replay window are pruned on the next launch.
    """

    __tablename__ = "studio_webapp_uses"

    shop_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shops.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    data_hash: Mapped[str] = mapped_column(String(HASH_LENGTH), nullable=False, unique=True)
    auth_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["customer_id", "shop_id"], ["customers.id", "customers.shop_id"], ondelete="CASCADE"
        ),
        Index("ix_studio_webapp_uses_shop_used", "shop_id", "used_at"),
    )
