"""share pages: photos -- the Foto design's frame and an invitation's gallery

CP17. One table, nothing existing touched:

  * `share_page_photos` -- up to six photos per page, numbered 1-6 (UNIQUE
    page_id + position; position 1 is the Foto frame), as re-encoded
    server-side: no EXIF, no GPS, at most 1200 px. Stored in the
    database rather than on disk so the photo travels with the page's backup,
    is deleted in the same transaction as the page's text, and needs no
    shared filesystem between processes. A CHECK bounds the stored size.
    `(page_id, shop_id)` is the composite FK onto the page, CASCADE.

Revision ID: 86570def06eb
Revises: 797f8207081f
Create Date: 2026-10-04 18:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "86570def06eb"
down_revision: str | None = "797f8207081f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "share_page_photos",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("shop_id", sa.BigInteger(), nullable=False),
        sa.Column("page_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("width", sa.SmallInteger(), nullable=False),
        sa.Column("height", sa.SmallInteger(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "size_bytes > 0 AND size_bytes <= 1500000",
            name=op.f("ck_share_page_photos_size_bound"),
        ),
        sa.CheckConstraint(
            "width > 0 AND height > 0", name=op.f("ck_share_page_photos_dimensions_positive")
        ),
        sa.ForeignKeyConstraint(
            ["page_id", "shop_id"],
            ["share_pages.id", "share_pages.shop_id"],
            name=op.f("fk_share_page_photos_page_id_shop_id_share_pages"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_share_page_photos")),
        sa.CheckConstraint(
            "position BETWEEN 1 AND 6", name=op.f("ck_share_page_photos_position_range")
        ),
        sa.UniqueConstraint(
            "page_id", "position", name=op.f("uq_share_page_photos_page_id_position")
        ),
    )


def downgrade() -> None:
    op.drop_table("share_page_photos")
