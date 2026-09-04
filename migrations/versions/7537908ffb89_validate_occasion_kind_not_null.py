"""validate occasion kind not null

Steps 3 and 4 of the tighten. VALIDATE scans but takes only a SHARE UPDATE
EXCLUSIVE lock, so writes continue. If the previous migration's backfill missed
a row, THIS migration fails -- which is why they are separate.

Revision ID: 7537908ffb89
Revises: 34628f2e87c9
Create Date: 2026-09-04
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "7537908ffb89"
down_revision: str | None = "34628f2e87c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE occasions VALIDATE CONSTRAINT ck_occasions_kind_present")
    op.alter_column("occasions", "kind", nullable=False)
    # The column constraint now carries the guarantee; the scaffolding CHECK
    # would only be a second thing to keep in step.
    op.execute("ALTER TABLE occasions DROP CONSTRAINT ck_occasions_kind_present")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE occasions ADD CONSTRAINT ck_occasions_kind_present "
        "CHECK (kind IS NOT NULL) NOT VALID"
    )
    op.alter_column("occasions", "kind", nullable=True)
