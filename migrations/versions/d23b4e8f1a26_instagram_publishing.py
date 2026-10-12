"""Instagram story publishing: connections, OAuth states, uploads (CP23 phase 3).

Additive only: three new tables and one UNIQUE (id, shop_id) on
announcement_drafts, which the uploads' composite foreign key needs (ids are
already unique, so it cannot fail on existing rows).

Revision ID: d23b4e8f1a26
Revises: c23a1f5e7b90
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d23b4e8f1a26"
down_revision: str | None = "c23a1f5e7b90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        op.f("uq_announcement_drafts_id_shop_id"), "announcement_drafts", ["id", "shop_id"]
    )
    op.create_table(
        "instagram_connections",
        sa.Column("shop_id", sa.BigInteger(), nullable=False),
        sa.Column("ig_user_id", sa.Text(), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("token_encrypted", sa.Text(), nullable=False),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
        sa.Column("connected_by", sa.BigInteger(), nullable=False),
        sa.Column(
            "connected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "ig_user_id ~ '^[0-9]{1,32}$'", name=op.f("ck_instagram_connections_ig_user_id_digits")
        ),
        sa.CheckConstraint(
            "length(username) BETWEEN 1 AND 64",
            name=op.f("ck_instagram_connections_username_length"),
        ),
        sa.CheckConstraint(
            "status IN ('active','expired')", name=op.f("ck_instagram_connections_status_known")
        ),
        sa.CheckConstraint(
            "connected_by > 0", name=op.f("ck_instagram_connections_connected_by_a_person")
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("shop_id"),
    )
    op.create_table(
        "instagram_oauth_states",
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("shop_id", sa.BigInteger(), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "owner_id > 0", name=op.f("ck_instagram_oauth_states_owner_is_a_person")
        ),
        sa.CheckConstraint(
            "token_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_instagram_oauth_states_token_hash_sha256"),
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        op.f("ix_instagram_oauth_states_shop_id"), "instagram_oauth_states", ["shop_id"]
    )
    op.create_table(
        "instagram_story_uploads",
        sa.Column("shop_id", sa.BigInteger(), nullable=False),
        sa.Column("draft_id", sa.BigInteger(), nullable=False),
        sa.Column("actor", sa.BigInteger(), nullable=False),
        sa.Column("layout", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("image", sa.LargeBinary(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("container_id", sa.Text(), nullable=True),
        sa.Column("media_id", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("actor > 0", name=op.f("ck_instagram_story_uploads_actor_is_a_person")),
        sa.CheckConstraint(
            "token_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_instagram_story_uploads_token_hash_sha256"),
        ),
        sa.CheckConstraint(
            "status IN ('queued','container','published','failed','expired')",
            name=op.f("ck_instagram_story_uploads_status_known"),
        ),
        sa.CheckConstraint(
            "status IN ('queued','container') OR image IS NULL",
            name=op.f("ck_instagram_story_uploads_image_wiped_when_done"),
        ),
        sa.ForeignKeyConstraint(
            ["draft_id", "shop_id"],
            ["announcement_drafts.id", "announcement_drafts.shop_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_instagram_story_uploads_shop_created",
        "instagram_story_uploads",
        ["shop_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_instagram_story_uploads_shop_created", table_name="instagram_story_uploads")
    op.drop_table("instagram_story_uploads")
    op.drop_index(op.f("ix_instagram_oauth_states_shop_id"), table_name="instagram_oauth_states")
    op.drop_table("instagram_oauth_states")
    op.drop_table("instagram_connections")
    op.drop_constraint(
        op.f("uq_announcement_drafts_id_shop_id"), "announcement_drafts", type_="unique"
    )
