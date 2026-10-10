"""shop staff: who may decide a shop's orders (CP19)

A new table, and nothing else: no shop gets a row, so every existing shop
keeps today's rule -- anyone in its group may confirm or reject -- until its
owner adds the first person from the platform bot.

Revision ID: 0956590ccce1
Revises: d5e841dbb2be
Create Date: 2026-10-10 11:00:46.183826
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0956590ccce1"
down_revision: str | None = "d5e841dbb2be"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shop_staff",
        sa.Column("shop_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=True),
        sa.Column("added_by", sa.BigInteger(), nullable=False),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("added_by > 0", name=op.f("ck_shop_staff_added_by_is_a_person")),
        sa.CheckConstraint("telegram_id > 0", name=op.f("ck_shop_staff_telegram_id_is_a_person")),
        sa.ForeignKeyConstraint(
            ["shop_id"], ["shops.id"], name=op.f("fk_shop_staff_shop_id_shops"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("shop_id", "telegram_id", name=op.f("pk_shop_staff")),
    )


def downgrade() -> None:
    # Drops every shop's list: each goes back to "anyone in the group".
    op.drop_table("shop_staff")
