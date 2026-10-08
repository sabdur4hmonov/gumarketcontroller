"""platform admin: one-time login links, sessions, and an append-only audit log (CP18)

Three new tables, nothing existing changes:

  * `admin_login_links` -- a link the platform bot sends; 10 minutes, one use;
  * `admin_sessions` -- a logged-in browser, with its CSRF token;
  * `admin_audit_log` -- every admin action and refusal.

Tokens are stored as SHA-256 only. The audit log is made append-only HERE, in
the database, by a trigger that refuses UPDATE, DELETE and TRUNCATE: the spec
asks that the app's own role cannot rewrite it, and a role grant is a
deployment step that can be forgotten, while a trigger travels with the schema.

Revision ID: ef3c1a7d5b92
Revises: 7b06b803c625
Create Date: 2026-10-08 22:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ef3c1a7d5b92"
down_revision: str | None = "7b06b803c625"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_login_links",
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_login_links")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_admin_login_links_token_hash")),
    )
    op.create_index(
        "ix_admin_login_links_telegram_created",
        "admin_login_links",
        ["telegram_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "admin_sessions",
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_admin_sessions_token_hash")),
    )
    op.create_table(
        "admin_audit_log",
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("admin_telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(length=48), nullable=False),
        sa.Column("shop_id", sa.BigInteger(), nullable=True),
        sa.Column("target_type", sa.String(length=24), nullable=True),
        sa.Column("target_id", sa.BigInteger(), nullable=True),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["shop_id"], ["shops.id"], name=op.f("fk_admin_audit_log_shop_id_shops")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_audit_log")),
    )
    op.create_index("ix_admin_audit_log_at", "admin_audit_log", ["at"], unique=False)
    op.create_index(
        "ix_admin_audit_log_shop_at", "admin_audit_log", ["shop_id", "at"], unique=False
    )
    op.execute(
        """
        CREATE FUNCTION admin_audit_log_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'admin_audit_log is append-only: % refused', TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER admin_audit_log_no_rewrite BEFORE UPDATE OR DELETE ON admin_audit_log "
        "FOR EACH ROW EXECUTE FUNCTION admin_audit_log_append_only()"
    )
    op.execute(
        "CREATE TRIGGER admin_audit_log_no_truncate BEFORE TRUNCATE ON admin_audit_log "
        "FOR EACH STATEMENT EXECUTE FUNCTION admin_audit_log_append_only()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER admin_audit_log_no_truncate ON admin_audit_log")
    op.execute("DROP TRIGGER admin_audit_log_no_rewrite ON admin_audit_log")
    op.execute("DROP FUNCTION admin_audit_log_append_only()")
    op.drop_index("ix_admin_audit_log_shop_at", table_name="admin_audit_log")
    op.drop_index("ix_admin_audit_log_at", table_name="admin_audit_log")
    op.drop_table("admin_audit_log")
    op.drop_table("admin_sessions")
    op.drop_index("ix_admin_login_links_telegram_created", table_name="admin_login_links")
    op.drop_table("admin_login_links")
