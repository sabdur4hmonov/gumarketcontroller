"""share pages: Uzrnoma, the apology letter

CP17. A third kind of page on `share_pages`; no new columns:

  * `ck_share_pages_kind_known` is widened to admit 'apology' (dropped and
    recreated under its convention name, as CP17 did for the templates).
  * `ck_share_pages_apology_complete` -- a live apology has its letter, kept
    in `message`.

The answer reuses `answered_at`, `notify_creator` and `notified_at`, exactly
as a Ha/Yo'q page does.

Downgrade removes the apology pages (their kind no longer exists below this
revision); everything else is untouched.

Revision ID: c5a8e2d61f37
Revises: b3f7a90c2e14
Create Date: 2026-10-05 13:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c5a8e2d61f37"
down_revision: str | None = "b3f7a90c2e14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_share_pages_kind_known"), "share_pages", type_="check")
    op.create_check_constraint(
        "kind_known", "share_pages", "kind IN ('yesno', 'invite', 'apology')"
    )
    op.create_check_constraint(
        "apology_complete",
        "share_pages",
        "deleted_at IS NOT NULL OR kind <> 'apology' OR message IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_share_pages_apology_complete"), "share_pages", type_="check")
    op.execute("DELETE FROM share_pages WHERE kind = 'apology'")
    op.drop_constraint(op.f("ck_share_pages_kind_known"), "share_pages", type_="check")
    op.create_check_constraint("kind_known", "share_pages", "kind IN ('yesno', 'invite')")
