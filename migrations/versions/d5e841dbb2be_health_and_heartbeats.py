"""bot-health snapshots and job heartbeats (CP18)

  * `shop_health_snapshots`: what the worker found every 10 minutes, per shop,
    through that shop's own bot (token valid, channel and group standing).
    The admin panel reads the latest; it never calls Telegram itself.
  * `job_runs`: one row per periodic job -- last start, last finish, last
    outcome. Read by the panel's stalled-job alert and by the page server's
    /healthz/jobs, both independent of the worker that writes it.

Revision ID: d5e841dbb2be
Revises: b996b9032869
Create Date: 2026-10-09 01:50:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d5e841dbb2be"
down_revision: str | None = "b996b9032869"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shop_health_snapshots",
        sa.Column("shop_id", sa.BigInteger(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("token_valid", sa.Boolean(), nullable=True),
        sa.Column("bot_username", sa.String(length=64), nullable=True),
        sa.Column("channel_ok", sa.Boolean(), nullable=True),
        sa.Column("group_ok", sa.Boolean(), nullable=True),
        sa.Column(
            "detail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.ForeignKeyConstraint(
            ["shop_id"],
            ["shops.id"],
            name=op.f("fk_shop_health_snapshots_shop_id_shops"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shop_health_snapshots")),
    )
    op.create_index(
        "ix_shop_health_snapshots_shop_checked",
        "shop_health_snapshots",
        ["shop_id", "checked_at"],
        unique=False,
    )
    op.create_table(
        "job_runs",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_ok", sa.Boolean(), nullable=True),
        sa.Column("last_error", sa.String(length=200), nullable=True),
        sa.PrimaryKeyConstraint("name", name=op.f("pk_job_runs")),
    )


def downgrade() -> None:
    op.drop_table("job_runs")
    op.drop_index("ix_shop_health_snapshots_shop_checked", table_name="shop_health_snapshots")
    op.drop_table("shop_health_snapshots")
