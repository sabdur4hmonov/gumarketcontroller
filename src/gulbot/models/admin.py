"""The platform admin panel's own tables (CP18): how an admin gets in, and the
record of everything an admin does.

NONE OF THESE BELONG TO A SHOP. They are the platform's, so they carry no
tenancy: `admin_audit_log.shop_id` is the shop an action was ABOUT (nullable,
FK to shops), never an owner of the row.

SECRETS ARE STORED HASHED. A login link and a session cookie are 128-bit
random tokens; only their SHA-256 is written, so a database dump hands out no
way in. Compared by hash lookup, which is constant-time with respect to the
secret.

THE AUDIT LOG IS APPEND-ONLY IN THE DATABASE, not only in the UI: a trigger
refuses UPDATE, DELETE and TRUNCATE on it (migration ef3c1a7d5b92), so not
even a bug in the panel -- or a psql session using the app's role -- can
rewrite history.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from gulbot.db.base import Base, IdMixin

#: hex SHA-256
HASH_LENGTH = 64


class AdminLoginLink(IdMixin, Base):
    """A one-time login link the PLATFORM bot sent to an admin's DM."""

    __tablename__ = "admin_login_links"

    token_hash: Mapped[str] = mapped_column(String(HASH_LENGTH), nullable=False, unique=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Set exactly once, by a compare-and-swap: the link is then spent.
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_admin_login_links_telegram_created", "telegram_id", "created_at"),)


class AdminSession(IdMixin, Base):
    """A logged-in browser. The cookie holds the raw token; this row its hash."""

    __tablename__ = "admin_sessions"

    token_hash: Mapped[str] = mapped_column(String(HASH_LENGTH), nullable=False, unique=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    #: Sent in every form; a POST without it is refused (CSRF).
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AdminAuditEntry(IdMixin, Base):
    """One thing an admin did -- or tried to do and was refused. Append-only."""

    __tablename__ = "admin_audit_log"

    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    #: NULL only for a refusal where nobody was identified (a spent link).
    admin_telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    shop_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("shops.id"), nullable=True)
    target_type: Mapped[str | None] = mapped_column(String(24), nullable=True)
    target_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_admin_audit_log_at", "at"),
        Index("ix_admin_audit_log_shop_at", "shop_id", "at"),
    )
