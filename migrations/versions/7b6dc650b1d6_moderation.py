"""moderation: hide a share page or a guest's wish, reversibly (CP18)

`deleted_at` already means "deleted or expired" and scrubs the text, so a
moderation hide is its own thing -- reversible, the text kept:

  * `share_pages.hidden_at`, `hidden_by` (the admin's Telegram id),
    `hidden_reason`; the public server treats a hidden page as unavailable;
  * `share_page_wishes.admin_hidden_at`, separate from the creator's own
    `hidden` flag, so a creator cannot un-hide what moderation took down.

Revision ID: 7b6dc650b1d6
Revises: b553a27b698e
Create Date: 2026-10-09 01:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7b6dc650b1d6"
down_revision: str | None = "b553a27b698e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("share_pages", sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("share_pages", sa.Column("hidden_by", sa.BigInteger(), nullable=True))
    op.add_column("share_pages", sa.Column("hidden_reason", sa.Text(), nullable=True))
    op.create_check_constraint(
        "hidden_has_reason",
        "share_pages",
        "hidden_at IS NULL OR (hidden_by IS NOT NULL AND hidden_reason IS NOT NULL)",
    )
    op.add_column(
        "share_page_wishes",
        sa.Column("admin_hidden_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("share_page_wishes", "admin_hidden_at")
    op.drop_constraint(op.f("ck_share_pages_hidden_has_reason"), "share_pages", type_="check")
    op.drop_column("share_pages", "hidden_reason")
    op.drop_column("share_pages", "hidden_by")
    op.drop_column("share_pages", "hidden_at")
