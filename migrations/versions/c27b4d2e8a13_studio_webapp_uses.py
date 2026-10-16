"""Taklifnoma Studio: one row per Telegram Mini App launch that opened a session (CP27.4)

Additive: one new table. Telegram's initData stays valid for an hour; storing
the sha256 of its hash under a UNIQUE constraint makes each launch open at
most one session (replay refused). Composite FK (customer_id, shop_id) ->
customers(id, shop_id).

Revision ID: c27b4d2e8a13
Revises: c27a1e5d9f01
Create Date: 2026-10-17 00:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c27b4d2e8a13"
down_revision: str | None = "c27a1e5d9f01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "studio_webapp_uses",
        sa.Column("shop_id", sa.BigInteger(), nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("data_hash", sa.String(length=64), nullable=False),
        sa.Column("auth_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "used_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["customer_id", "shop_id"],
            ["customers.id", "customers.shop_id"],
            name=op.f("fk_studio_webapp_uses_customer_id_shop_id_customers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["shop_id"],
            ["shops.id"],
            name=op.f("fk_studio_webapp_uses_shop_id_shops"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_studio_webapp_uses")),
        sa.UniqueConstraint("data_hash", name=op.f("uq_studio_webapp_uses_data_hash")),
    )
    op.create_index(
        "ix_studio_webapp_uses_shop_used",
        "studio_webapp_uses",
        ["shop_id", "used_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_studio_webapp_uses_shop_used", table_name="studio_webapp_uses")
    op.drop_table("studio_webapp_uses")
