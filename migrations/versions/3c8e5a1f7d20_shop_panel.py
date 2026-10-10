"""the shop owner's panel: login links, sessions and an append-only log (CP20)

Three new tables, every row owned by one shop. Nothing existing changes.
`shop_audit_log` refuses UPDATE, DELETE and TRUNCATE by trigger, as
admin_audit_log does (ef3c1a7d5b92).

Revision ID: 3c8e5a1f7d20
Revises: 0956590ccce1
Create Date: 2026-10-10 18:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3c8e5a1f7d20"
down_revision: str | None = "0956590ccce1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shop_login_links",
        sa.Column("shop_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["shop_id"],
            ["shops.id"],
            name=op.f("fk_shop_login_links_shop_id_shops"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shop_login_links")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_shop_login_links_token_hash")),
    )
    op.create_index(
        "ix_shop_login_links_shop_owner_created",
        "shop_login_links",
        ["shop_id", "telegram_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "shop_sessions",
        sa.Column("shop_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("csrf_token", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["shop_id"],
            ["shops.id"],
            name=op.f("fk_shop_sessions_shop_id_shops"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shop_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_shop_sessions_token_hash")),
    )
    op.create_table(
        "shop_audit_log",
        sa.Column("shop_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(length=48), nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["shop_id"], ["shops.id"], name=op.f("fk_shop_audit_log_shop_id_shops")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shop_audit_log")),
    )
    op.create_index("ix_shop_audit_log_shop_at", "shop_audit_log", ["shop_id", "at"], unique=False)
    op.execute(
        """
        CREATE FUNCTION shop_audit_log_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'shop_audit_log is append-only: % refused', TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER shop_audit_log_no_rewrite BEFORE UPDATE OR DELETE ON shop_audit_log "
        "FOR EACH ROW EXECUTE FUNCTION shop_audit_log_append_only()"
    )
    op.execute(
        "CREATE TRIGGER shop_audit_log_no_truncate BEFORE TRUNCATE ON shop_audit_log "
        "FOR EACH STATEMENT EXECUTE FUNCTION shop_audit_log_append_only()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER shop_audit_log_no_truncate ON shop_audit_log")
    op.execute("DROP TRIGGER shop_audit_log_no_rewrite ON shop_audit_log")
    op.execute("DROP FUNCTION shop_audit_log_append_only()")
    op.drop_index("ix_shop_audit_log_shop_at", table_name="shop_audit_log")
    op.drop_table("shop_audit_log")
    op.drop_table("shop_sessions")
    op.drop_index("ix_shop_login_links_shop_owner_created", table_name="shop_login_links")
    op.drop_table("shop_login_links")
