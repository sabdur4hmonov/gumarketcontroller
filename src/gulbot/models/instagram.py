"""CP23 phase 3: a shop's Instagram business account, and the stories it posts.

Built, and OFF by default (settings.instagram_publishing_enabled).

  * instagram_connections -- one per shop: the account id and name, and its
    access token as Fernet CIPHERTEXT (services/shop_tokens.py, the same key
    and module as bot tokens). Never a plaintext token anywhere.
  * instagram_oauth_states -- the one-time `state` of a connect flow, stored
    as a hash, bound to the shop and owner who started it, 10 minutes.
  * instagram_story_uploads -- a story on its way to Instagram: the image
    Meta fetches from our page server at an unguessable URL (stored as a
    hash), short-lived, and wiped once Meta has it or the attempt ends.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from gulbot.db.base import Base, IdMixin


class InstagramConnection(Base):
    __tablename__ = "instagram_connections"
    shop_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shops.id", ondelete="CASCADE"), primary_key=True
    )
    ig_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    connected_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: A short error CODE (never a token, never Meta's raw text).
    last_error: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        CheckConstraint("ig_user_id ~ '^[0-9]{1,32}$'", name="ig_user_id_digits"),
        CheckConstraint("length(username) BETWEEN 1 AND 64", name="username_length"),
        CheckConstraint("status IN ('active','expired')", name="status_known"),
        CheckConstraint("connected_by > 0", name="connected_by_a_person"),
    )


class InstagramOAuthState(IdMixin, Base):
    __tablename__ = "instagram_oauth_states"
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    shop_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shops.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        CheckConstraint("owner_id > 0", name="owner_is_a_person"),
        CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="token_hash_sha256"),
    )


class InstagramStoryUpload(IdMixin, Base):
    __tablename__ = "instagram_story_uploads"
    shop_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("shops.id", ondelete="CASCADE"), nullable=False
    )
    draft_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    layout: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    #: The JPEG Meta fetches. NULL once the attempt has ended either way.
    image: Mapped[bytes | None] = mapped_column(LargeBinary)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'queued'"))
    container_id: Mapped[str | None] = mapped_column(Text)
    media_id: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        # Composite: an upload can never point at another shop's draft.
        ForeignKeyConstraint(
            ["draft_id", "shop_id"],
            ["announcement_drafts.id", "announcement_drafts.shop_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("actor > 0", name="actor_is_a_person"),
        CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="token_hash_sha256"),
        CheckConstraint(
            "status IN ('queued','container','published','failed','expired')",
            name="status_known",
        ),
        CheckConstraint(
            "status IN ('queued','container') OR image IS NULL", name="image_wiped_when_done"
        ),
        Index("ix_instagram_story_uploads_shop_created", "shop_id", "created_at"),
    )
