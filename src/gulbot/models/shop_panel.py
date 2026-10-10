"""The shop owner's own panel, /shop (CP20): how an owner gets in, and the
record of what happens there.

EVERY ROW BELONGS TO ONE SHOP. A link is minted by THAT shop's bot for one of
its owners, a session opened from it can see only that shop, and the log
records that shop's events. `shops` is the tenancy root, so the plain FK on
`shop_id` is the tenancy constraint.

Secrets are stored hashed, as for /admin (models/admin.py): a dump of these
tables hands out no way in. The audit log is append-only in the database: a
trigger refuses UPDATE, DELETE and TRUNCATE (migration 3c8e5a1f7d20), so its
FK to shops has no ON DELETE -- a shop with a history is not deleted quietly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from gulbot.db.base import Base, IdMixin
from gulbot.models.admin import HASH_LENGTH


class ShopLoginLink(IdMixin, Base):
    """A one-time link THIS shop's bot sent to one of its owners."""

    __tablename__ = "shop_login_links"

    shop_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shops.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(HASH_LENGTH), nullable=False, unique=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Set exactly once, by a compare-and-swap: the link is then spent.
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_shop_login_links_shop_owner_created", "shop_id", "telegram_id", "created_at"),
    )


class ShopSession(IdMixin, Base):
    """A logged-in owner's browser, for exactly one shop."""

    __tablename__ = "shop_sessions"

    shop_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shops.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(HASH_LENGTH), nullable=False, unique=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    #: Sent in every form; a POST without it is refused (CSRF).
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ShopAuditEntry(IdMixin, Base):
    """One thing that happened in a shop's panel -- a login, a refusal, an
    export, a setting changed. Append-only."""

    __tablename__ = "shop_audit_log"

    shop_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("shops.id"), nullable=False)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    #: NULL only for a refusal where nobody was identified.
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (Index("ix_shop_audit_log_shop_at", "shop_id", "at"),)
