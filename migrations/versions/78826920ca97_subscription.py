"""subscriptions, set by hand: shops.subscription_status, paid_until, and a payments ledger (CP18)

Billing is manual for now (the spec's MVP): the platform owner records a
payment in the admin panel. Additive only:

  * `shops.subscription_status` varchar(16) NOT NULL DEFAULT 'none', with
    `ck_shops_subscription_known` (none / trial / paid / overdue);
  * `shops.paid_until` date, NULL until a payment is recorded;
  * `subscription_payments`: the ledger -- one row per recorded payment, who
    recorded it, never edited. The shops columns are the current state; the
    ledger is the history.

Revision ID: 78826920ca97
Revises: ef3c1a7d5b92
Create Date: 2026-10-09 01:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "78826920ca97"
down_revision: str | None = "ef3c1a7d5b92"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "shops",
        sa.Column(
            "subscription_status",
            sa.String(length=16),
            server_default=sa.text("'none'"),
            nullable=False,
        ),
    )
    op.add_column("shops", sa.Column("paid_until", sa.Date(), nullable=True))
    op.create_check_constraint(
        "subscription_known",
        "shops",
        "subscription_status IN ('none', 'trial', 'paid', 'overdue')",
    )
    op.create_table(
        "subscription_payments",
        sa.Column("shop_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "paid_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("amount_uzs", sa.BigInteger(), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("paid_until", sa.Date(), nullable=False),
        sa.Column("admin_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.CheckConstraint("amount_uzs > 0", name=op.f("ck_subscription_payments_amount_positive")),
        sa.CheckConstraint(
            "method IN ('cash', 'card_transfer', 'other')",
            name=op.f("ck_subscription_payments_method_known"),
        ),
        sa.ForeignKeyConstraint(
            ["shop_id"], ["shops.id"], name=op.f("fk_subscription_payments_shop_id_shops")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscription_payments")),
    )
    op.create_index(
        "ix_subscription_payments_shop_paid",
        "subscription_payments",
        ["shop_id", "paid_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_subscription_payments_shop_paid", table_name="subscription_payments")
    op.drop_table("subscription_payments")
    op.drop_constraint(op.f("ck_shops_subscription_known"), "shops", type_="check")
    op.drop_column("shops", "paid_until")
    op.drop_column("shops", "subscription_status")
