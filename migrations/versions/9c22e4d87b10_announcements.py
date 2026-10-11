"""Add shop-scoped announcement drafts and preferences (CP22).

Revision ID: 9c22e4d87b10
Revises: 8f2d6c41b9a3
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9c22e4d87b10"
down_revision: str | None = "8f2d6c41b9a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "announcement_drafts",
        sa.Column("shop_id", sa.BigInteger(), nullable=False),
        sa.Column("author_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'collecting'"), nullable=False),
        sa.Column("revision", sa.Integer(), server_default=sa.text("'1'"), nullable=False),
        sa.Column(
            "photos", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column(
            "fields", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("caption_style", sa.Text(), server_default=sa.text("'classic'"), nullable=False),
        sa.Column("image_style", sa.Text(), server_default=sa.text("'none'"), nullable=False),
        sa.Column(
            "preview_media",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("preview_caption", sa.Text(), nullable=True),
        sa.Column(
            "receipts", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("acknowledgement_id", sa.BigInteger(), nullable=True),
        sa.Column("job_id", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("author_id > 0", name=op.f("ck_announcement_drafts_author_is_a_person")),
        sa.CheckConstraint("revision > 0", name=op.f("ck_announcement_drafts_revision_positive")),
        sa.CheckConstraint(
            "jsonb_array_length(photos) <= 10", name=op.f("ck_announcement_drafts_photos_max_ten")
        ),
        sa.CheckConstraint(
            "status IN ('collecting','transcribing','review','confirmed','preview','publishing','published','ambiguous')",
            name=op.f("ck_announcement_drafts_status_known"),
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_announcement_drafts_shop_id"), "announcement_drafts", ["shop_id"])
    op.create_table(
        "announcement_preferences",
        sa.Column("shop_id", sa.BigInteger(), nullable=False),
        sa.Column("caption_style", sa.Text(), nullable=False),
        sa.Column("image_style", sa.Text(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("shop_id"),
    )


def downgrade() -> None:
    op.drop_table("announcement_preferences")
    op.drop_index(op.f("ix_announcement_drafts_shop_id"), table_name="announcement_drafts")
    op.drop_table("announcement_drafts")
