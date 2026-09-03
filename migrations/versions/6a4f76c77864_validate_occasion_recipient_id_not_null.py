"""validate occasion recipient_id not null

Steps 3 and 4 of the tighten. VALIDATE scans the table but takes only a SHARE
UPDATE EXCLUSIVE lock, so writes continue. If the previous migration's backfill
missed a row, THIS migration fails -- which is the point of splitting them.

SET NOT NULL then reuses the validated CHECK instead of scanning again
(Postgres 12+), so it is effectively instant.

Revision ID: 6a4f76c77864
Revises: 603b4c962f57
Create Date: 2026-09-03 22:24:07.230469
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "6a4f76c77864"
down_revision: str | None = "603b4c962f57"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE occasions VALIDATE CONSTRAINT ck_occasions_recipient_id_present")
    op.alter_column("occasions", "recipient_id", nullable=False)
    # The column constraint now carries the guarantee; the scaffolding CHECK
    # would only be a second thing to keep in step.
    op.execute("ALTER TABLE occasions DROP CONSTRAINT ck_occasions_recipient_id_present")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE occasions ADD CONSTRAINT ck_occasions_recipient_id_present "
        "CHECK (recipient_id IS NOT NULL) NOT VALID"
    )
    op.alter_column("occasions", "recipient_id", nullable=True)
