"""Shop-scoped authoring drafts and favourite styles (CP22)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from gulbot.db.base import Base, IdMixin, TimestampMixin


class AnnouncementDraft(IdMixin, TimestampMixin, Base):
    __tablename__ = "announcement_drafts"
    shop_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shops.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'collecting'"))
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("'1'"))
    photos: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    fields: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    caption_style: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'classic'")
    )
    image_style: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'none'"))
    preview_media: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    preview_caption: Mapped[str | None] = mapped_column(Text)
    receipts: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    acknowledgement_id: Mapped[int | None] = mapped_column(BigInteger)
    job_id: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("author_id > 0", name="author_is_a_person"),
        CheckConstraint("revision > 0", name="revision_positive"),
        CheckConstraint("jsonb_array_length(photos) <= 10", name="photos_max_ten"),
        CheckConstraint(
            "status IN ('collecting','transcribing','review','confirmed','preview',"
            "'publishing','published','ambiguous')",
            name="status_known",
        ),
    )


class AnnouncementPreference(Base):
    __tablename__ = "announcement_preferences"
    shop_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shops.id", ondelete="CASCADE"), primary_key=True
    )
    caption_style: Mapped[str] = mapped_column(Text, nullable=False)
    image_style: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
