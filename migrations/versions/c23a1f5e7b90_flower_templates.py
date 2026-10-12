"""Flower templates on drafts, and a favourite layout per flower (CP23).

Additive only: three new draft columns (nullable or defaulted, so existing
drafts and CP22's saved styles are untouched) and one new table.

Revision ID: c23a1f5e7b90
Revises: 9c22e4d87b10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c23a1f5e7b90"
down_revision: str | None = "9c22e4d87b10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

THEMES = (
    "atirgul",
    "kust_atirgul",
    "lola",
    "xrizantema",
    "gerbera",
    "liliya",
    "pion",
    "gortenziya",
    "eustoma",
    "chinnigul",
    "orxideya",
    "alstromeriya",
    "mimoza",
    "aralash",
    "quti",
)
LAYOUTS = (
    "classic",
    "minimal",
    "festive",
    "premium",
    "playful",
    "sale",
    "gift",
    "new_arrival",
    "price_first",
    "story_card",
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.add_column("announcement_drafts", sa.Column("template", sa.Text(), nullable=True))
    op.add_column(
        "announcement_drafts",
        sa.Column("template_picked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "announcement_drafts",
        sa.Column("caption_lang", sa.Text(), server_default=sa.text("'uz'"), nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_announcement_drafts_template_shape"),
        "announcement_drafts",
        "template IS NULL OR template ~ '^[a-z_]+[.][a-z_]+$'",
    )
    op.create_check_constraint(
        op.f("ck_announcement_drafts_caption_lang_known"),
        "announcement_drafts",
        "caption_lang IN ('uz','uz_cyrl','ru')",
    )
    op.create_table(
        "announcement_theme_favourites",
        sa.Column("shop_id", sa.BigInteger(), nullable=False),
        sa.Column("theme", sa.Text(), nullable=False),
        sa.Column("layout", sa.Text(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            _in("theme", THEMES), name=op.f("ck_announcement_theme_favourites_theme_known")
        ),
        sa.CheckConstraint(
            _in("layout", LAYOUTS), name=op.f("ck_announcement_theme_favourites_layout_known")
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("shop_id", "theme"),
    )


def downgrade() -> None:
    op.drop_table("announcement_theme_favourites")
    op.drop_constraint(
        op.f("ck_announcement_drafts_caption_lang_known"), "announcement_drafts", type_="check"
    )
    op.drop_constraint(
        op.f("ck_announcement_drafts_template_shape"), "announcement_drafts", type_="check"
    )
    op.drop_column("announcement_drafts", "caption_lang")
    op.drop_column("announcement_drafts", "template_picked")
    op.drop_column("announcement_drafts", "template")
