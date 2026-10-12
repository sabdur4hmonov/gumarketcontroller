"""Per-shop learned corrections, and deleted posts (CP23 addendum).

Additive: one new table, and the drafts' status CHECK extended by 'deleted'
the way CONTRIBUTING extends an enumeration -- drop and recreate one small
constraint (every existing value is still allowed, so no row can fail).

The downgrade cannot keep 'deleted' drafts under the old CHECK: it turns
them back into 'published' rows -- their channel post is gone -- and drops
every shop's learned corrections. DEPLOY's downgrade table says so.

Revision ID: e23c5a9d0b37
Revises: d23b4e8f1a26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e23c5a9d0b37"
down_revision: str | None = "d23b4e8f1a26"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = (
    "status IN ('collecting','transcribing','review','confirmed','preview',"
    "'publishing','published','ambiguous')"
)
NEW = (
    "status IN ('collecting','transcribing','review','confirmed','preview',"
    "'publishing','published','ambiguous','deleted')"
)
CHECK = "ck_announcement_drafts_status_known"


def upgrade() -> None:
    op.drop_constraint(op.f(CHECK), "announcement_drafts", type_="check")
    op.create_check_constraint(op.f(CHECK), "announcement_drafts", NEW)
    op.create_table(
        "announcement_corrections",
        sa.Column("shop_id", sa.BigInteger(), nullable=False),
        sa.Column("heard", sa.Text(), nullable=False),
        sa.Column("corrected", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("taught_by", sa.BigInteger(), nullable=False),
        sa.Column("uses", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "last_used_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('flower','colour','number')",
            name=op.f("ck_announcement_corrections_kind_known"),
        ),
        sa.CheckConstraint(
            "length(heard) BETWEEN 1 AND 40", name=op.f("ck_announcement_corrections_heard_short")
        ),
        sa.CheckConstraint(
            "length(corrected) BETWEEN 1 AND 40",
            name=op.f("ck_announcement_corrections_corrected_short"),
        ),
        sa.CheckConstraint(
            "taught_by > 0", name=op.f("ck_announcement_corrections_taught_by_a_person")
        ),
        sa.CheckConstraint("uses >= 0", name=op.f("ck_announcement_corrections_uses_not_negative")),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shop_id", "heard"),
    )


def downgrade() -> None:
    op.drop_table("announcement_corrections")
    op.execute("UPDATE announcement_drafts SET status = 'published' WHERE status = 'deleted'")
    op.drop_constraint(op.f(CHECK), "announcement_drafts", type_="check")
    op.create_check_constraint(op.f(CHECK), "announcement_drafts", OLD)
