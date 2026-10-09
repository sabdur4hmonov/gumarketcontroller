"""the gift rule: premium share-page parts unlocked by a confirmed order, per shop (CP18)

  * `shops.gift_premium_after_order` boolean NOT NULL DEFAULT true -- the
    product rule as briefed; the admin panel turns it off per shop;
  * `premium_unlocks` (shop_id, customer_id, order_id, granted_at): one row
    per customer PER SHOP, written in the transaction that confirms their
    first order there. Composite FKs onto customers (id, shop_id) and orders
    (id, shop_id): an unlock can only ever join a customer and an order of
    the SAME shop it belongs to.

Revision ID: b553a27b698e
Revises: eda7c57173b7
Create Date: 2026-10-09 01:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b553a27b698e"
down_revision: str | None = "eda7c57173b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "shops",
        sa.Column(
            "gift_premium_after_order",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    op.create_table(
        "premium_unlocks",
        sa.Column("shop_id", sa.BigInteger(), nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["customer_id", "shop_id"],
            ["customers.id", "customers.shop_id"],
            name=op.f("fk_premium_unlocks_customer_id_shop_id_customers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["order_id", "shop_id"],
            ["orders.id", "orders.shop_id"],
            name=op.f("fk_premium_unlocks_order_id_shop_id_orders"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("shop_id", "customer_id", name=op.f("pk_premium_unlocks")),
    )


def downgrade() -> None:
    op.drop_table("premium_unlocks")
    op.drop_column("shops", "gift_premium_after_order")
