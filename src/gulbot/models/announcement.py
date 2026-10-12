"""Shop-scoped authoring drafts and favourite styles (CP22)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    func,
    text,
)
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
    # CP23: a flower template "<theme>.<layout>", or NULL for CP22's own
    # caption/image styles (kept as a family, so saved CP22 defaults still work).
    template: Mapped[str | None] = mapped_column(Text)
    # True once the owner chose the template; until then a re-confirm may
    # re-derive it from the (edited) flowers.
    template_picked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    caption_lang: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'uz'"))
    __table_args__ = (
        CheckConstraint(
            "template IS NULL OR template ~ '^[a-z_]+[.][a-z_]+$'", name="template_shape"
        ),
        CheckConstraint("caption_lang IN ('uz','uz_cyrl','ru')", name="caption_lang_known"),
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


#: CP23 values, mirrored by the CHECKs below (themes.py / layouts.py are the
#: source of truth; tests/test_flower_selection.py fails if they drift).
THEME_IDS = (
    "atirgul",
    "kust_atirgul",
    "lola",
    "xrizantema",
    "gerbera",
    "liliya",
    "pion",
    "gortenziya",
    "eustoma",
    "chinnigul",
    "orxideya",
    "alstromeriya",
    "mimoza",
    "aralash",
    "quti",
)
LAYOUT_IDS = (
    "classic",
    "minimal",
    "festive",
    "premium",
    "playful",
    "sale",
    "gift",
    "new_arrival",
    "price_first",
    "story_card",
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class AnnouncementThemeFavourite(Base):
    """A shop's favourite layout PER FLOWER THEME (CP23): roses may be premium,
    tulips festive. Shop-scoped by its key; one row per (shop, theme)."""

    __tablename__ = "announcement_theme_favourites"
    shop_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shops.id", ondelete="CASCADE"), primary_key=True
    )
    theme: Mapped[str] = mapped_column(Text, primary_key=True)
    layout: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    __table_args__ = (
        CheckConstraint(_in("theme", THEME_IDS), name="theme_known"),
        CheckConstraint(_in("layout", LAYOUT_IDS), name="layout_known"),
    )
