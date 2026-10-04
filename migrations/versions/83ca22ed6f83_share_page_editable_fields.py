"""share pages: every visible text block of a taklifnoma is editable

CP17. Five optional text blocks and an edit stamp, added to `share_pages`;
nothing existing changes:

  * `title`      -- the line above the names. NULL shows the event type's
    own label, in the page's language.
  * `dress_code`, `program`, `contact` -- extra lines the creator may add.
    Free text: a phone number appears on the page only if the creator types
    one here.
  * `closing`    -- the last line. NULL shows the event type's preset.
  * `edited_at`  -- when the creator last changed the page. The link does
    not change on edit; this is the record that the content did.

NULL meaning "the preset" (rather than the preset copied in at creation)
keeps presets in step with the page's language when the creator switches
it, and leaves every page made before this migration exactly as it was.

Revision ID: 83ca22ed6f83
Revises: 360f0694be06
Create Date: 2026-10-04 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "83ca22ed6f83"
down_revision: str | None = "360f0694be06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("share_pages", sa.Column("title", sa.String(length=80), nullable=True))
    op.add_column("share_pages", sa.Column("dress_code", sa.String(length=120), nullable=True))
    op.add_column("share_pages", sa.Column("program", sa.String(length=400), nullable=True))
    op.add_column("share_pages", sa.Column("contact", sa.String(length=120), nullable=True))
    op.add_column("share_pages", sa.Column("closing", sa.String(length=200), nullable=True))
    op.add_column("share_pages", sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("share_pages", "edited_at")
    op.drop_column("share_pages", "closing")
    op.drop_column("share_pages", "contact")
    op.drop_column("share_pages", "program")
    op.drop_column("share_pages", "dress_code")
    op.drop_column("share_pages", "title")
