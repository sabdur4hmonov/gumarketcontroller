"""Operations state the admin panel reads (CP18): bot-health snapshots, written
by the worker every 10 minutes, and job heartbeats, written by every periodic
task. Rules: gulbot.services.shop_health."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from gulbot.db.base import Base, IdMixin


class ShopHealthSnapshot(IdMixin, Base):
    """What the worker found, through the shop's own bot. NULL = not checked
    (no bot, Telegram unreachable, or nothing to check)."""

    __tablename__ = "shop_health_snapshots"

    shop_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shops.id", ondelete="CASCADE"), nullable=False
    )
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    token_valid: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    bot_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    channel_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    group_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    __table_args__ = (Index("ix_shop_health_snapshots_shop_checked", "shop_id", "checked_at"),)


class JobRun(Base):
    """One row per periodic job: its last start, finish and outcome."""

    __tablename__ = "job_runs"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(200), nullable=True)
