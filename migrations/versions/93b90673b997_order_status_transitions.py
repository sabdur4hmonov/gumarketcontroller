"""order status transitions

What CP13 needs to make the shop's order card actionable:

  * `rejection_reason` -- why, in the shop's own words, so the customer is
    told something rather than left guessing.
  * `status_changed_at` -- NULL while an order is still 'placed', which
    makes "never acted on" a queryable state rather than an inference from
    created_at.
  * 'cancelled' in the PING state CHECK. A rejected order's delivery is not
    happening, so its 3-hour and 1-hour reminders must stop. CP10b's
    docstring said a ping needs no CANCELLED because nobody can block the
    bot in its own group -- true, and beside the point: this is not the
    destination refusing, it is the reason evaporating.

The status CHECK on `orders` needs no change at all: CP10a put all five
values in it from the start precisely so the migration that began using
them would be additive. This is that migration, and it is.

AUTOGENERATE SAW THE TWO COLUMNS AND NOT THE CHECK, as it has every time --
it compares CHECK constraints by name and the name did not change. See
CONTRIBUTING.md.

Revision ID: 93b90673b997
Revises: 3f7767d11dea
Create Date: 2026-09-09 10:37:27.157257
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "93b90673b997"
down_revision: str | None = "3f7767d11dea"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Literals, not an import from the model: a migration must describe the
#: schema at THIS revision, and importing the enum would make it silently
#: follow later edits.
STATES_BEFORE = ("pending", "sending", "sent", "failed", "dead_letter")
STATES_AFTER = ("pending", "sending", "sent", "failed", "dead_letter", "cancelled")


def _state_check(states: Sequence[str]) -> str:
    return "state IN (" + ", ".join(f"'{state}'" for state in states) + ")"


def upgrade() -> None:
    op.add_column("orders", sa.Column("rejection_reason", sa.String(length=200), nullable=True))
    op.add_column(
        "orders", sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.drop_constraint(op.f("ck_order_reminders_state_known"), "order_reminders", type_="check")
    op.create_check_constraint(
        "state_known", "order_reminders", sa.text(_state_check(STATES_AFTER))
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_order_reminders_state_known"), "order_reminders", type_="check")
    # A cancelled ping has no representable state once the CHECK narrows.
    # Back to 'dead_letter': the order it belonged to was rejected, so the
    # ping must still never be sent, and dead_letter is the one surviving
    # state that means exactly that.
    op.execute("UPDATE order_reminders SET state = 'dead_letter' WHERE state = 'cancelled'")
    op.create_check_constraint(
        "state_known", "order_reminders", sa.text(_state_check(STATES_BEFORE))
    )
    op.drop_column("orders", "status_changed_at")
    op.drop_column("orders", "rejection_reason")
