"""Add the sellable catalogue cursor index without blocking catalogue writes."""

import sqlalchemy as sa
from alembic import op

revision = "a25f2c7d9e10"
down_revision = "a25e1d6c8b90"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_products_shop_sellable_cursor",
            "products",
            ["shop_id", "indexed_at", "id"],
            postgresql_where=sa.text(
                "active IS TRUE AND deleted_at IS NULL AND finalized_at IS NOT NULL"
            ),
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_products_shop_sellable_cursor", table_name="products", postgresql_concurrently=True
        )
