"""shops.lang: the language a shop's own people read (L2 of AUDIT_MULTI_TENANT.md)

CP-MT2's follow-up, planned there and made once CP17's migrations had merged
so there would be one Alembic head:

  * `shops.lang` varchar(2) NOT NULL DEFAULT 'uz' -- a constant default is a
    metadata-only change on Postgres 11+, no table rewrite, and every existing
    shop reads exactly what every shop-facing path hardcoded before;
  * `ck_shops_lang_known`: the same codes and the same shape as
    `customers.lang`, so there is one definition of a language in the schema.
    Every row is the default when it is added, so it needs no NOT VALID /
    VALIDATE split.

Revision ID: 4b6e1d9c2a07
Revises: c5a8e2d61f37
Create Date: 2026-10-08 20:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4b6e1d9c2a07"
down_revision: str | None = "c5a8e2d61f37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "shops",
        sa.Column("lang", sa.String(length=2), server_default=sa.text("'uz'"), nullable=False),
    )
    op.create_check_constraint("lang_known", "shops", "lang IN ('uz', 'ru', 'en')")


def downgrade() -> None:
    op.drop_constraint(op.f("ck_shops_lang_known"), "shops", type_="check")
    op.drop_column("shops", "lang")
