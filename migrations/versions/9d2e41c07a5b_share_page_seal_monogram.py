"""share pages: the creator's monogram on the Konvert wax seal

CP17. One column on `share_pages`; nothing existing changes:

  * `seal_monogram` -- up to five characters the creator enters ("A&M"):
    letters, "&" or a middle dot. NULL shows the couple's initials, as every
    page made before this migration already does.

Revision ID: 9d2e41c07a5b
Revises: 541afb7b8568
Create Date: 2026-10-05 09:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9d2e41c07a5b"
down_revision: str | None = "541afb7b8568"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("share_pages", sa.Column("seal_monogram", sa.String(length=5), nullable=True))


def downgrade() -> None:
    op.drop_column("share_pages", "seal_monogram")
