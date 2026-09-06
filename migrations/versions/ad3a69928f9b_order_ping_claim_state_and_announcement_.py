"""order ping claim state and announcement ping

What CP10b needs that CP10a could not have known:

  * `claimed_at`, so a ping claim can time out. CP10a knew the row would be its
    own ledger; it did not yet know the claim needed a clock, because the send
    path did not exist.
  * 'sending' in the state CHECK. That is the claim itself: pending -> sending
    commits BEFORE Telegram is called, which is what stops a dead worker's
    retry sending the shop a second copy.
  * `ping_number >= 0` instead of `> 0`. Ping 0 is the "new order" announcement.
    It shares the delivery reminders' outbox because it is the same kind of
    thing -- one message to the shop, sent once, claimed the same way -- and a
    second table would have meant a second copy of the claim logic.

BOTH CHECK CHANGES WERE INVISIBLE TO AUTOGENERATE, which detected `claimed_at`
and nothing else. It compares CHECK constraints by NAME, and neither name
changed. Widening an enumeration by dropping and recreating one small named
constraint is the pattern CONTRIBUTING describes; the guard that catches a
mistake in it is `tests/test_check_constraints.py`, which reads
`pg_get_constraintdef` instead of asking Alembic.

The downgrade narrows `ping_number` back to `> 0`, which would fail against an
existing announcement row -- so it deletes ping 0 rows first. That is data loss,
and it is the honest behaviour: a schema that cannot represent those rows cannot
keep them.

Revision ID: ad3a69928f9b
Revises: 75e0e9cdd766
Create Date: 2026-09-06 19:30:56.506415
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ad3a69928f9b"
down_revision: str | None = "75e0e9cdd766"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Kept as literals rather than imported from the model. A migration must
#: describe the schema at THIS revision; importing the enum would make it
#: silently follow later edits to the model and stop being a record of anything.
STATES_BEFORE = ("pending", "sent", "failed", "dead_letter")
STATES_AFTER = ("pending", "sending", "sent", "failed", "dead_letter")


def _state_check(states: Sequence[str]) -> str:
    return "state IN (" + ", ".join(f"'{state}'" for state in states) + ")"


def upgrade() -> None:
    op.add_column(
        "order_reminders", sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.drop_constraint(op.f("ck_order_reminders_state_known"), "order_reminders", type_="check")
    op.create_check_constraint(
        "state_known", "order_reminders", sa.text(_state_check(STATES_AFTER))
    )

    op.drop_constraint(
        op.f("ck_order_reminders_ping_number_positive"), "order_reminders", type_="check"
    )
    op.create_check_constraint(
        "ping_number_positive", "order_reminders", sa.text("ping_number >= 0")
    )


def downgrade() -> None:
    # Narrow the constraint only after the rows it would reject are gone.
    op.drop_constraint(
        op.f("ck_order_reminders_ping_number_positive"), "order_reminders", type_="check"
    )
    op.execute("DELETE FROM order_reminders WHERE ping_number = 0")
    op.create_check_constraint(
        "ping_number_positive", "order_reminders", sa.text("ping_number > 0")
    )

    op.drop_constraint(op.f("ck_order_reminders_state_known"), "order_reminders", type_="check")
    # A row mid-flight when the downgrade runs has no representable state. Back
    # to 'pending' rather than dropped: the ping has not been sent, so the shop
    # still needs it, and the claim it is losing was about to time out anyway.
    op.execute("UPDATE order_reminders SET state = 'pending' WHERE state = 'sending'")
    op.create_check_constraint(
        "state_known", "order_reminders", sa.text(_state_check(STATES_BEFORE))
    )

    op.drop_column("order_reminders", "claimed_at")
