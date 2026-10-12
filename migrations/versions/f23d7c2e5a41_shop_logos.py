"""A shop's own logo on its announcement photos (CP23 addendum).

Additive: one new table, and drafts.logo_on (defaulted true; existing drafts
simply use the logo once a shop sends one).

Revision ID: f23d7c2e5a41
Revises: e23c5a9d0b37
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f23d7c2e5a41"
down_revision: str | None = "e23c5a9d0b37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "announcement_drafts",
        sa.Column("logo_on", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.create_table(
        "shop_logos",
        sa.Column("shop_id", sa.BigInteger(), nullable=False),
        sa.Column("image", sa.LargeBinary(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("uploaded_by", sa.BigInteger(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "octet_length(image) BETWEEN 1 AND 2000000", name=op.f("ck_shop_logos_image_size")
        ),
        sa.CheckConstraint(
            "width BETWEEN 16 AND 512 AND height BETWEEN 16 AND 512",
            name=op.f("ck_shop_logos_dimensions"),
        ),
        sa.CheckConstraint("uploaded_by > 0", name=op.f("ck_shop_logos_uploaded_by_a_person")),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("shop_id"),
    )


def downgrade() -> None:
    op.drop_table("shop_logos")
    op.drop_column("announcement_drafts", "logo_on")
