"""shops.status: onboarding / active / paused (CP18)

The platform admin panel's pause switch needs a state the WORKERS read, not a
panel-only flag:

  * `shops.status` varchar(16) NOT NULL DEFAULT 'active' -- every existing
    shop is serving today, so 'active' is what each one already is; a
    constant default adds the column without a rewrite;
  * `ck_shops_status_known`;
  * `shops.status_changed_at`, NULL until the first change.

Revision ID: 7b06b803c625
Revises: 4b6e1d9c2a07
Create Date: 2026-10-08 21:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7b06b803c625"
down_revision: str | None = "4b6e1d9c2a07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "shops",
        sa.Column(
            "status", sa.String(length=16), server_default=sa.text("'active'"), nullable=False
        ),
    )
    op.add_column(
        "shops", sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        "status_known", "shops", "status IN ('onboarding', 'active', 'paused')"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_shops_status_known"), "shops", type_="check")
    op.drop_column("shops", "status_changed_at")
    op.drop_column("shops", "status")
