"""share pages: a Ha/Yo'q page may carry a date plan

CP17 Part 1. The creator offers 1-5 places and 1-5 times; after Ha, the
recipient picks one of each. Additive only:

  * `share_page_options` -- the creator's offers, one row each. A place is
    text; a slot is an instant. Positions 1-5 per kind, UNIQUE per page.
    `(page_id, shop_id)` is the composite FK onto the page, CASCADE.
  * on `share_pages`:
      - `chosen_place`, `chosen_slot_at`, `chosen_at` -- the recipient's
        choice, kept as a SNAPSHOT of what they picked, so the creator's
        message and the celebration read the same thing even after options
        change. Set once (compare-and-swap on chosen_at).
      - `choice_notified_at` -- the claim on the ONE follow-up message sent
        when the choice arrives after the first message already went.

CHECKs keep the snapshot whole (all three or none, and only after a Ha) and
the follow-up claim after a choice. Options are CHECKed to hold exactly the
field their kind needs.

Revision ID: 878bc32b72d4
Revises: 83ca22ed6f83
Create Date: 2026-10-04 14:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "878bc32b72d4"
down_revision: str | None = "83ca22ed6f83"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("share_pages", sa.Column("chosen_place", sa.String(length=80), nullable=True))
    op.add_column(
        "share_pages", sa.Column("chosen_slot_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("share_pages", sa.Column("chosen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "share_pages", sa.Column("choice_notified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        "choice_complete",
        "share_pages",
        "(chosen_at IS NULL AND chosen_place IS NULL AND chosen_slot_at IS NULL) "
        "OR (chosen_at IS NOT NULL AND chosen_place IS NOT NULL AND chosen_slot_at IS NOT NULL "
        "AND answered_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "choice_notified_after_choice",
        "share_pages",
        "choice_notified_at IS NULL OR chosen_at IS NOT NULL",
    )
    op.create_table(
        "share_page_options",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("shop_id", sa.BigInteger(), nullable=False),
        sa.Column("page_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("place", sa.String(length=80), nullable=True),
        sa.Column("slot_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('place', 'slot')", name=op.f("ck_share_page_options_kind_known")
        ),
        sa.CheckConstraint(
            "position BETWEEN 1 AND 5", name=op.f("ck_share_page_options_position_range")
        ),
        sa.CheckConstraint(
            "(kind = 'place' AND place IS NOT NULL AND slot_at IS NULL) "
            "OR (kind = 'slot' AND slot_at IS NOT NULL AND place IS NULL)",
            name=op.f("ck_share_page_options_one_value"),
        ),
        sa.ForeignKeyConstraint(
            ["page_id", "shop_id"],
            ["share_pages.id", "share_pages.shop_id"],
            name=op.f("fk_share_page_options_page_id_shop_id_share_pages"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_share_page_options")),
        sa.UniqueConstraint(
            "page_id", "kind", "position", name=op.f("uq_share_page_options_page_id_kind_position")
        ),
    )


def downgrade() -> None:
    op.drop_table("share_page_options")
    op.drop_constraint(
        op.f("ck_share_pages_choice_notified_after_choice"), "share_pages", type_="check"
    )
    op.drop_constraint(op.f("ck_share_pages_choice_complete"), "share_pages", type_="check")
    op.drop_column("share_pages", "choice_notified_at")
    op.drop_column("share_pages", "chosen_at")
    op.drop_column("share_pages", "chosen_slot_at")
    op.drop_column("share_pages", "chosen_place")
