"""share pages: optional music

CP17. One column on `share_pages`; nothing existing changes:

  * `music` -- NULL (no music: the default, and every page made before this
    migration) or the name of one of OUR tracks. A CHECK admits only those
    names, so no page can carry a song we have no license for; the tracks
    and their license are in static/js/music.js and static/music/LICENSE.md.

Revision ID: b3f7a90c2e14
Revises: 9d2e41c07a5b
Create Date: 2026-10-05 11:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3f7a90c2e14"
down_revision: str | None = "9d2e41c07a5b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("share_pages", sa.Column("music", sa.String(length=16), nullable=True))
    op.create_check_constraint(
        "music_known",
        "share_pages",
        "music IS NULL OR music IN ('bahor', 'oqshom', 'tantana')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_share_pages_music_known"), "share_pages", type_="check")
    op.drop_column("share_pages", "music")
