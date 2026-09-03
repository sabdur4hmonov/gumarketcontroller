"""recipients and occasion recipient_id

Step 1 of the four-step tighten documented in CONTRIBUTING.md: create the table,
add the column NULLABLE, backfill, then assert the shape with a NOT VALID check.
The next migration validates it and sets NOT NULL, so an incomplete backfill
surfaces as a failed migration rather than as NULLs nobody notices.

ONE DELIBERATE EXCEPTION to additive-only: the old
uq_occasions_customer_id_month_day_label is DROPPED. It keyed duplicate
detection on the label, so a customer with two friends both labelled "Do'stim"
could not save the same date for the second one. Two recipients sharing a label
is now explicitly supported, which makes that constraint wrong rather than
merely redundant. It is replaced by uq_occasions_recipient_id_month_day, which
is strictly more correct and still stops a double-tapped confirm.

Revision ID: 603b4c962f57
Revises: a87cd107a0ed
Create Date: 2026-09-03 22:22:53.610392
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "603b4c962f57"
down_revision: str | None = "a87cd107a0ed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recipients",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("shop_id", sa.BigInteger(), nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("preferred_hashtag", sa.String(length=32), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("length(btrim(label)) > 0", name=op.f("ck_recipients_label_not_blank")),
        sa.CheckConstraint(
            "type IN ('wife', 'spouse', 'mother', 'father', 'child', 'friend', 'custom')",
            name=op.f("ck_recipients_type_known"),
        ),
        sa.ForeignKeyConstraint(
            ["customer_id", "shop_id"],
            ["customers.id", "customers.shop_id"],
            name=op.f("fk_recipients_customer_id_shop_id_customers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recipients")),
        sa.UniqueConstraint("id", "customer_id", name=op.f("uq_recipients_id_customer_id")),
    )
    op.create_index(
        "ix_recipients_customer_active", "recipients", ["customer_id", "active"], unique=False
    )

    op.add_column("occasions", sa.Column("recipient_id", sa.BigInteger(), nullable=True))

    # --- backfill --------------------------------------------------------
    # One recipient per distinct (customer_id, label). Existing rows carry no
    # way to tell two same-labelled people apart, so collapsing them is the
    # only honest reading of the old data. Going forward they stay separate.
    op.execute(
        """
        INSERT INTO recipients (shop_id, customer_id, label, type, active)
        SELECT DISTINCT ON (o.customer_id, o.label)
               o.shop_id, o.customer_id, o.label, o.type, true
        FROM occasions o
        ORDER BY o.customer_id, o.label, o.id
        """
    )
    op.execute(
        """
        UPDATE occasions o
        SET recipient_id = r.id
        FROM recipients r
        WHERE r.customer_id = o.customer_id
          AND r.label = o.label
        """
    )

    op.drop_constraint("uq_occasions_customer_id_month_day_label", "occasions", type_="unique")
    op.create_foreign_key(
        op.f("fk_occasions_recipient_id_customer_id_recipients"),
        "occasions",
        "recipients",
        ["recipient_id", "customer_id"],
        ["id", "customer_id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        op.f("uq_occasions_recipient_id_month_day"),
        "occasions",
        ["recipient_id", "month", "day"],
    )
    op.create_index("ix_occasions_recipient", "occasions", ["recipient_id"], unique=False)

    # Asserted here, validated in the next migration. NOT VALID is instant: it
    # binds new rows without scanning the table.
    op.execute(
        "ALTER TABLE occasions ADD CONSTRAINT ck_occasions_recipient_id_present "
        "CHECK (recipient_id IS NOT NULL) NOT VALID"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE occasions DROP CONSTRAINT ck_occasions_recipient_id_present")
    op.drop_index("ix_occasions_recipient", table_name="occasions")
    op.drop_constraint(op.f("uq_occasions_recipient_id_month_day"), "occasions", type_="unique")
    op.drop_constraint(
        op.f("fk_occasions_recipient_id_customer_id_recipients"),
        "occasions",
        type_="foreignkey",
    )
    op.create_unique_constraint(
        "uq_occasions_customer_id_month_day_label",
        "occasions",
        ["customer_id", "month", "day", "label"],
    )
    op.drop_column("occasions", "recipient_id")
    op.drop_index("ix_recipients_customer_active", table_name="recipients")
    op.drop_table("recipients")
