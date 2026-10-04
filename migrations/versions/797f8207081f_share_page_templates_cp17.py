"""share pages: ten more designs

CP17 adds ten designs, so `ck_share_pages_template_known` is widened the way
CONTRIBUTING describes for a text + CHECK enumeration: drop the one named
constraint and create it again. Nothing existing changes.

Downgrading moves any page on a CP17 design to "minimal" first, so the
narrower CHECK can be restored without refusing rows.

Revision ID: 797f8207081f
Revises: 878bc32b72d4
Create Date: 2026-10-04 16:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "797f8207081f"
down_revision: str | None = "878bc32b72d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CP16 = (
    "'milliy', 'atlas', 'minimal', 'bog', 'romantik', 'oltin', 'quvnoq', 'tungi', 'pastel', "
    "'konvert'"
)
CP17 = (
    "'foto', 'bold', 'geometrik', 'akvarel', 'vintaj', 'oqqora', 'bolalar', 'suzani', 'neon', "
    "'deco'"
)


def upgrade() -> None:
    op.drop_constraint(op.f("ck_share_pages_template_known"), "share_pages", type_="check")
    op.create_check_constraint("template_known", "share_pages", f"template IN ({CP16}, {CP17})")


def downgrade() -> None:
    op.execute(f"UPDATE share_pages SET template = 'minimal' WHERE template IN ({CP17})")
    op.drop_constraint(op.f("ck_share_pages_template_known"), "share_pages", type_="check")
    op.create_check_constraint("template_known", "share_pages", f"template IN ({CP16})")
