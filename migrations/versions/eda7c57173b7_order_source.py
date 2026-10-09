"""orders.source and orders.source_page_id: where an order came from (CP18)

Set once, at submit, by services/orders.create_order:

  * 'reminder' -- the order started from a reminder's bouquet button;
  * 'page'     -- the customer arrived through a share page's "order flowers"
                  link (a share_page_referrals row) within the attribution
                  window; `source_page_id` names that page;
  * 'direct'   -- anything else.

NULL for every order placed before this revision: they are shown as
"before CP18", never guessed at.

`source_page_id` joins the page by (id, shop_id), the project's tenancy
shape, so an order can never be attributed to another shop's page. ON DELETE
SET NULL names its column (Postgres 15+): a bare SET NULL on a composite FK
would null shop_id too, which CP10a learned the hard way.

Revision ID: eda7c57173b7
Revises: 78826920ca97
Create Date: 2026-10-09 01:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "eda7c57173b7"
down_revision: str | None = "78826920ca97"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("source", sa.String(length=16), nullable=True))
    op.add_column("orders", sa.Column("source_page_id", sa.BigInteger(), nullable=True))
    op.create_check_constraint(
        "source_known",
        "orders",
        "source IS NULL OR source IN ('reminder', 'page', 'direct')",
    )
    op.create_check_constraint(
        "source_page_only_for_pages",
        "orders",
        "source_page_id IS NULL OR source = 'page'",
    )
    op.create_foreign_key(
        op.f("fk_orders_source_page_id_shop_id_share_pages"),
        "orders",
        "share_pages",
        ["source_page_id", "shop_id"],
        ["id", "shop_id"],
        ondelete="SET NULL (source_page_id)",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_orders_source_page_id_shop_id_share_pages"), "orders", type_="foreignkey"
    )
    op.drop_constraint(op.f("ck_orders_source_page_only_for_pages"), "orders", type_="check")
    op.drop_constraint(op.f("ck_orders_source_known"), "orders", type_="check")
    op.drop_column("orders", "source_page_id")
    op.drop_column("orders", "source")
