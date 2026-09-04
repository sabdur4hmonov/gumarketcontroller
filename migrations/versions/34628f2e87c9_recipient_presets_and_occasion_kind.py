"""recipient presets and occasion kind

Two changes from the onboarding review.

1. The recipient preset list becomes: Onam, Turmush o'rtog'im, Opa, Singil,
   Amma, Xola, Boshqa. "Xotinim" is dropped as a duplicate of "Turmush
   o'rtog'im"; Otam, Farzandim and Do'stim are dropped outright.

   Existing rows are MAPPED, not stranded:
       wife                    -> spouse   (they meant the same thing)
       father / child / friend -> custom   (the typed label is preserved,
                                            so the person is not lost)

2. `occasions.kind` is added: what the date actually IS, separate from who it
   is for. Until now `type` held the recipient preset and the confirm screen
   rendered it in the "kind" slot, which is why it read "Turi: Onam".

Step 1 of the four-step tighten (CONTRIBUTING.md): add the column NULLABLE,
backfill, assert with a NOT VALID check. The next migration validates it and
sets NOT NULL, so an incomplete backfill fails the deploy rather than leaving
NULLs nobody notices.

Revision ID: 34628f2e87c9
Revises: 9c82f8b5d486
Create Date: 2026-09-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "34628f2e87c9"
down_revision: str | None = "9c82f8b5d486"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_TYPES = (
    "'mother', 'spouse', 'older_sister', 'younger_sister', "
    "'paternal_aunt', 'maternal_aunt', 'custom'"
)
OLD_TYPES = "'wife', 'spouse', 'mother', 'father', 'child', 'friend', 'custom'"
KINDS = "'birthday', 'anniversary', 'other'"

_MAPPING = "CASE type WHEN 'wife' THEN 'spouse' ELSE 'custom' END"
_REMOVED = "('wife', 'father', 'child', 'friend')"


def upgrade() -> None:
    # --- 1. map away the retired presets, BEFORE tightening the CHECK -------
    for table in ("recipients", "occasions"):
        op.execute(f"UPDATE {table} SET type = {_MAPPING} WHERE type IN {_REMOVED}")
        op.drop_constraint(f"ck_{table}_type_known", table)
        op.create_check_constraint("type_known", table, f"type IN ({NEW_TYPES})")

    # --- 2. the occasion kind ----------------------------------------------
    op.add_column("occasions", sa.Column("kind", sa.String(length=16), nullable=True))
    # Every existing row predates the question. A saved personal date is
    # overwhelmingly a birthday, and it is the kind the reminder copy reads most
    # naturally for, so that is the honest default rather than 'other'.
    op.execute("UPDATE occasions SET kind = 'birthday' WHERE kind IS NULL")
    op.create_check_constraint("kind_known", "occasions", f"kind IN ({KINDS})")
    op.execute(
        "ALTER TABLE occasions ADD CONSTRAINT ck_occasions_kind_present "
        "CHECK (kind IS NOT NULL) NOT VALID"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE occasions DROP CONSTRAINT ck_occasions_kind_present")
    op.drop_constraint("ck_occasions_kind_known", "occasions")
    op.drop_column("occasions", "kind")

    for table in ("occasions", "recipients"):
        op.drop_constraint(f"ck_{table}_type_known", table)
        op.create_check_constraint("type_known", table, f"type IN ({OLD_TYPES})")
