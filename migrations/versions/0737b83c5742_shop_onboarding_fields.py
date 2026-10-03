"""shop onboarding fields

What a shop owner's onboarding conversation records, beyond the token itself:

  * `bot_telegram_id` -- the bot's numeric id, the PUBLIC half of its token
    ("123456789:..."). UNIQUE, so no two shops can hold the same bot even if
    two onboardings race past the conversation's own check: two long-polls of
    one bot make Telegram answer 409 to both, and two shops sharing a bot would
    share one customer-facing identity. NULL until a token is stored; the pilot
    shop, on the BOT_TOKEN fallback, has none to take it from.
  * `owner_phone` / `owner_phone_verified` -- the owner's own number, with the
    same verified-or-typed distinction `customers.phone` makes.

Additive only: nothing existing changes.

Revision ID: 0737b83c5742
Revises: da3db957e4c0
Create Date: 2026-09-28 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0737b83c5742"
down_revision: str | None = "da3db957e4c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("shops", sa.Column("bot_telegram_id", sa.BigInteger(), nullable=True))
    op.create_unique_constraint(op.f("uq_shops_bot_telegram_id"), "shops", ["bot_telegram_id"])
    op.add_column("shops", sa.Column("owner_phone", sa.String(length=32), nullable=True))
    op.add_column(
        "shops",
        sa.Column(
            "owner_phone_verified",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("shops", "owner_phone_verified")
    op.drop_column("shops", "owner_phone")
    op.drop_constraint(op.f("uq_shops_bot_telegram_id"), "shops", type_="unique")
    op.drop_column("shops", "bot_telegram_id")
