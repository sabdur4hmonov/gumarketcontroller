"""share pages: the guest wishes wall

CP17. One table and one switch; nothing existing changes:

  * `share_pages.wishes_enabled` -- the wall is OFF until the creator turns it
    on in the bot (false for every page made before this migration).
  * `share_page_wishes` -- a guest's name and wish, both capped (40 / 300)
    and never empty; `hidden` is the creator's switch for any one wish.
    `(page_id, shop_id)` is the composite FK onto the page, CASCADE, so a wish
    can never belong to a page of another shop.

Revision ID: 541afb7b8568
Revises: cf7aa499fe45
Create Date: 2026-10-04 22:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "541afb7b8568"
down_revision: str | None = "cf7aa499fe45"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "share_pages",
        sa.Column("wishes_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.create_table(
        "share_page_wishes",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("shop_id", sa.BigInteger(), nullable=False),
        sa.Column("page_id", sa.BigInteger(), nullable=False),
        sa.Column("voter_key", sa.String(length=32), nullable=False),
        sa.Column("author", sa.String(length=40), nullable=False),
        sa.Column("body", sa.String(length=300), nullable=False),
        sa.Column("hidden", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(author) > 0 AND length(body) > 0", name=op.f("ck_share_page_wishes_not_empty")
        ),
        sa.ForeignKeyConstraint(
            ["page_id", "shop_id"],
            ["share_pages.id", "share_pages.shop_id"],
            name=op.f("fk_share_page_wishes_page_id_shop_id_share_pages"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_share_page_wishes")),
    )
    op.create_index(
        "ix_share_page_wishes_page_created", "share_page_wishes", ["page_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_share_page_wishes_page_created", table_name="share_page_wishes")
    op.drop_table("share_page_wishes")
    op.drop_column("share_pages", "wishes_enabled")
