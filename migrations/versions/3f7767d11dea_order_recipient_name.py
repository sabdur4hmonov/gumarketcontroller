"""order recipient name

Who takes delivery, as free text. Deliberately NOT the same thing as
`recipient_id`, which points at a saved person on the customer's own list: the
flowers are often handed to whoever answers the door, and the courier needs the
name they should ask for.

Nullable, because every order placed before this column existed has no answer
and inventing one would be worse than an honest blank. Every order placed after
it is asked.

Revision ID: 3f7767d11dea
Revises: ad3a69928f9b
Create Date: 2026-09-09 10:04:36.553307
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3f7767d11dea"
down_revision: str | None = "ad3a69928f9b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("recipient_name", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "recipient_name")
