"""photo purge: an expired page's photo FILES go, the rows stay for the counts (CP18)

  * `share_page_photos.data` becomes nullable -- loosening a constraint, which
    is additive: every existing row still satisfies it;
  * `share_page_photos.purged_at`: when the nightly scrub dropped the bytes.
  * `ck_share_page_photos_purged_has_no_data`: data IS NULL exactly when
    purged_at is set, so a half-purged row is not a state the table can hold.

Revision ID: b996b9032869
Revises: 7b6dc650b1d6
Create Date: 2026-10-09 01:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b996b9032869"
down_revision: str | None = "7b6dc650b1d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "share_page_photos", sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.alter_column("share_page_photos", "data", existing_type=sa.LargeBinary(), nullable=True)
    op.create_check_constraint(
        "purged_has_no_data",
        "share_page_photos",
        "(purged_at IS NULL) = (data IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_share_page_photos_purged_has_no_data"), "share_page_photos", type_="check"
    )
    # A purged row has no bytes to restore: it cannot exist below this revision.
    op.execute("DELETE FROM share_page_photos WHERE data IS NULL")
    op.alter_column("share_page_photos", "data", existing_type=sa.LargeBinary(), nullable=False)
    op.drop_column("share_page_photos", "purged_at")
