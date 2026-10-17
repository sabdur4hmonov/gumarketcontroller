"""Taklifnoma Studio: one-time links, sessions, an append-only log, page venues (CP27.1)

Four new tables; nothing existing changes.

* studio_links / studio_sessions: a customer of ONE shop gets into the web
  creator by a link from that shop's bot. Composite FK (customer_id, shop_id)
  -> customers(id, shop_id); tokens stored as sha256 only.
* studio_audit_log: append-only by trigger, as shop_audit_log (3c8e5a1f7d20).
* share_page_venues: a taklifnoma's places, composite FK (page_id, shop_id)
  -> share_pages(id, shop_id). Literal lists: no application constant imported.

Revision ID: c27a1e5d9f01
Revises: a24d9e7b2c10
Create Date: 2026-10-16 19:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c27a1e5d9f01"
down_revision: str | None = "a24d9e7b2c10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VENUE_KINDS = ("toyxona", "restoran", "kafe", "bog", "uy", "boshqa")


def _customer_tables(name: str, *extra: sa.Column[object]) -> None:
    op.create_table(
        name,
        sa.Column("shop_id", sa.BigInteger(), nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        *extra,
        sa.Column("bot_username", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "used_at" if name == "studio_links" else "revoked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.CheckConstraint(
            "expires_at > created_at", name=op.f(f"ck_{name}_expires_after_created")
        ),
        sa.ForeignKeyConstraint(
            ["customer_id", "shop_id"],
            ["customers.id", "customers.shop_id"],
            name=op.f(f"fk_{name}_customer_id_shop_id_customers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["shop_id"], ["shops.id"], name=op.f(f"fk_{name}_shop_id_shops"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{name}")),
        sa.UniqueConstraint("token_hash", name=op.f(f"uq_{name}_token_hash")),
    )


def upgrade() -> None:
    _customer_tables("studio_links")
    op.create_index(
        "ix_studio_links_shop_customer_created",
        "studio_links",
        ["shop_id", "customer_id", "created_at"],
        unique=False,
    )
    _customer_tables(
        "studio_sessions", sa.Column("csrf_token", sa.String(length=64), nullable=False)
    )
    op.create_index(
        "ix_studio_sessions_shop_customer",
        "studio_sessions",
        ["shop_id", "customer_id"],
        unique=False,
    )
    op.create_table(
        "studio_audit_log",
        sa.Column("shop_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("customer_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(length=48), nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["shop_id"], ["shops.id"], name=op.f("fk_studio_audit_log_shop_id_shops")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_studio_audit_log")),
    )
    op.create_index(
        "ix_studio_audit_log_shop_at", "studio_audit_log", ["shop_id", "at"], unique=False
    )
    op.execute(
        """
        CREATE FUNCTION studio_audit_log_append_only() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'studio_audit_log is append-only: % refused', TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER studio_audit_log_no_rewrite BEFORE UPDATE OR DELETE ON studio_audit_log "
        "FOR EACH ROW EXECUTE FUNCTION studio_audit_log_append_only()"
    )
    op.execute(
        "CREATE TRIGGER studio_audit_log_no_truncate BEFORE TRUNCATE ON studio_audit_log "
        "FOR EACH STATEMENT EXECUTE FUNCTION studio_audit_log_append_only()"
    )
    op.create_table(
        "share_page_venues",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("shop_id", sa.BigInteger(), nullable=False),
        sa.Column("page_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("address", sa.String(length=160), nullable=True),
        sa.Column("map_url", sa.String(length=300), nullable=True),
        sa.Column("starts_at", sa.Time(), nullable=True),
        sa.CheckConstraint(
            "kind IN (" + ", ".join(f"'{kind}'" for kind in VENUE_KINDS) + ")",
            name=op.f("ck_share_page_venues_kind_known"),
        ),
        sa.CheckConstraint(
            "map_url IS NULL OR left(map_url, 8) = 'https://'",
            name=op.f("ck_share_page_venues_map_url_https"),
        ),
        sa.CheckConstraint(
            "position BETWEEN 1 AND 5", name=op.f("ck_share_page_venues_position_range")
        ),
        sa.ForeignKeyConstraint(
            ["page_id", "shop_id"],
            ["share_pages.id", "share_pages.shop_id"],
            name=op.f("fk_share_page_venues_page_id_shop_id_share_pages"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_share_page_venues")),
        sa.UniqueConstraint(
            "page_id", "position", name=op.f("uq_share_page_venues_page_id_position")
        ),
    )


def downgrade() -> None:
    op.drop_table("share_page_venues")
    op.execute("DROP TRIGGER studio_audit_log_no_truncate ON studio_audit_log")
    op.execute("DROP TRIGGER studio_audit_log_no_rewrite ON studio_audit_log")
    op.execute("DROP FUNCTION studio_audit_log_append_only()")
    op.drop_index("ix_studio_audit_log_shop_at", table_name="studio_audit_log")
    op.drop_table("studio_audit_log")
    op.drop_index("ix_studio_sessions_shop_customer", table_name="studio_sessions")
    op.drop_table("studio_sessions")
    op.drop_index("ix_studio_links_shop_customer_created", table_name="studio_links")
    op.drop_table("studio_links")
