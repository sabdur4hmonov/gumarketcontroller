"""customers.lang may be 'en'

CP17 offers English for the menus and the Ha/Yo'q and taklifnoma flows, so a
customer can choose it. The CHECK is widened the way CONTRIBUTING describes
for a text + CHECK enumeration: drop the one named constraint and create it
again with the new value. Nothing existing changes.

Downgrading turns every English customer back into an Uzbek one first, so the
narrower CHECK can be restored.

Revision ID: 360f0694be06
Revises: 1897629a71dc
Create Date: 2026-10-04 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "360f0694be06"
down_revision: str | None = "1897629a71dc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_customers_lang_known"), "customers", type_="check")
    op.create_check_constraint("lang_known", "customers", "lang IN ('uz', 'ru', 'en')")


def downgrade() -> None:
    op.execute("UPDATE customers SET lang = 'uz' WHERE lang = 'en'")
    op.drop_constraint(op.f("ck_customers_lang_known"), "customers", type_="check")
    op.create_check_constraint("lang_known", "customers", "lang IN ('uz', 'ru')")
