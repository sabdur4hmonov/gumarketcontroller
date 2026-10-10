"""holiday campaigns: the holidays a shop runs, lunar dates, holiday reminders (CP20)

Additive, in the CONTRIBUTING sense:
  * two new tables: `shop_holidays` (per shop) and `holiday_dates` (platform);
  * `scheduled_notifications` gains a nullable `holiday`, and `occasion_id`
    becomes nullable -- every existing row keeps its occasion, and a CHECK
    requires exactly one of the two from now on;
  * a partial UNIQUE index gives holiday rows the anti-duplicate guarantee the
    occasion UNIQUE gives the rest (a UNIQUE never compares NULLs);
  * two small CHECKs are widened by drop-and-recreate: orders.source gains
    'holiday', consent_events.type gains 'holiday_greetings'.

THE DOWNGRADE CHANGES DATA, because the old CHECKs cannot hold it: holiday
reminder rows are deleted, holiday orders lose their source (NULL, "unknown"),
and holiday consent rows are deleted. Back up before going below this.

Revision ID: 8f2d6c41b9a3
Revises: 3c8e5a1f7d20
Create Date: 2026-10-10 21:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8f2d6c41b9a3"
down_revision: str | None = "3c8e5a1f7d20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Spelled out, not imported: a migration must keep meaning what it meant.
HOLIDAYS = (
    "'valentines', 'womens_day', 'navruz', 'teachers_day', 'new_year', "
    "'ramazon_hayit', 'qurbon_hayit'"
)
LUNAR = "'ramazon_hayit', 'qurbon_hayit'"
OLD_SOURCES = "'reminder', 'page', 'direct'"
NEW_SOURCES = "'reminder', 'page', 'direct', 'holiday'"
OLD_CONSENT = "'store_dates'"
NEW_CONSENT = "'store_dates', 'holiday_greetings'"


def upgrade() -> None:
    op.create_table(
        "shop_holidays",
        sa.Column("shop_id", sa.BigInteger(), nullable=False),
        sa.Column("holiday", sa.String(length=24), nullable=False),
        sa.Column(
            "enabled_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("enabled_by", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(f"holiday IN ({HOLIDAYS})", name=op.f("ck_shop_holidays_holiday_known")),
        sa.ForeignKeyConstraint(
            ["shop_id"],
            ["shops.id"],
            name=op.f("fk_shop_holidays_shop_id_shops"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("shop_id", "holiday", name=op.f("pk_shop_holidays")),
    )
    op.create_table(
        "holiday_dates",
        sa.Column("holiday", sa.String(length=24), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("falls_on", sa.Date(), nullable=False),
        sa.Column(
            "set_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("set_by", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(f"holiday IN ({LUNAR})", name=op.f("ck_holiday_dates_lunar_only")),
        sa.CheckConstraint(
            "EXTRACT(YEAR FROM falls_on) = year", name=op.f("ck_holiday_dates_date_in_its_year")
        ),
        sa.CheckConstraint("year BETWEEN 2020 AND 2100", name=op.f("ck_holiday_dates_year_range")),
        sa.PrimaryKeyConstraint("holiday", "year", name=op.f("pk_holiday_dates")),
    )

    op.add_column(
        "scheduled_notifications", sa.Column("holiday", sa.String(length=24), nullable=True)
    )
    op.alter_column(
        "scheduled_notifications", "occasion_id", existing_type=sa.BigInteger(), nullable=True
    )
    op.create_check_constraint(
        "occasion_or_holiday",
        "scheduled_notifications",
        "(occasion_id IS NULL) <> (holiday IS NULL)",
    )
    op.create_check_constraint(
        "holiday_known", "scheduled_notifications", f"holiday IS NULL OR holiday IN ({HOLIDAYS})"
    )
    op.create_index(
        "uq_scheduled_notifications_holiday",
        "scheduled_notifications",
        ["customer_id", "holiday", "occurrence_year", "offset_days", "channel"],
        unique=True,
        postgresql_where=sa.text("holiday IS NOT NULL"),
    )

    op.drop_constraint("ck_orders_source_known", "orders")
    op.create_check_constraint(
        "source_known", "orders", f"source IS NULL OR source IN ({NEW_SOURCES})"
    )
    op.drop_constraint("ck_consent_events_type_known", "consent_events")
    op.create_check_constraint("type_known", "consent_events", f"type IN ({NEW_CONSENT})")


def downgrade() -> None:
    op.execute("DELETE FROM consent_events WHERE type = 'holiday_greetings'")
    op.drop_constraint("ck_consent_events_type_known", "consent_events")
    op.create_check_constraint("type_known", "consent_events", f"type IN ({OLD_CONSENT})")
    op.execute("UPDATE orders SET source = NULL WHERE source = 'holiday'")
    op.drop_constraint("ck_orders_source_known", "orders")
    op.create_check_constraint(
        "source_known", "orders", f"source IS NULL OR source IN ({OLD_SOURCES})"
    )

    op.execute("DELETE FROM scheduled_notifications WHERE holiday IS NOT NULL")
    op.drop_index("uq_scheduled_notifications_holiday", table_name="scheduled_notifications")
    op.drop_constraint("ck_scheduled_notifications_holiday_known", "scheduled_notifications")
    op.drop_constraint("ck_scheduled_notifications_occasion_or_holiday", "scheduled_notifications")
    op.alter_column(
        "scheduled_notifications", "occasion_id", existing_type=sa.BigInteger(), nullable=False
    )
    op.drop_column("scheduled_notifications", "holiday")

    op.drop_table("holiday_dates")
    op.drop_table("shop_holidays")
