"""share pages: a taklifnoma's optional sections

CP17. Three columns on `share_pages`; nothing existing changes:

  * `show_countdown` -- the countdown under the date (on, as every page made
    before this migration already shows it).
  * `show_gallery`   -- the photo gallery (on; with no photos there is
    nothing to show either way).
  * `dress_colors`   -- up to five dress-code colours, palette keys picked in
    the bot ("oq,oltin"). A CHECK keeps the stored shape: lower-case keys,
    comma-separated, at most five. NULL is "no colours".

Revision ID: cf7aa499fe45
Revises: 86570def06eb
Create Date: 2026-10-04 20:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "cf7aa499fe45"
down_revision: str | None = "86570def06eb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "share_pages",
        sa.Column("show_countdown", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column(
        "share_pages",
        sa.Column("show_gallery", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column("share_pages", sa.Column("dress_colors", sa.String(length=80), nullable=True))
    op.create_check_constraint(
        "dress_colors_shape",
        "share_pages",
        "dress_colors IS NULL OR dress_colors ~ '^[a-z]{2,12}(,[a-z]{2,12}){0,4}$'",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_share_pages_dress_colors_shape"), "share_pages", type_="check")
    op.drop_column("share_pages", "dress_colors")
    op.drop_column("share_pages", "show_gallery")
    op.drop_column("share_pages", "show_countdown")
