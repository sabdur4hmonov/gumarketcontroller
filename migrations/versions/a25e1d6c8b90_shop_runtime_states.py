"""Add durable shop runtime state without changing existing health records."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a25e1d6c8b90"
down_revision = "a24d9e7b2c10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shop_runtime_states",
        sa.Column("shop_id", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("shop_id"),
    )


def downgrade() -> None:
    op.drop_table("shop_runtime_states")
