"""Activate twenty CP24 styles after CP23, preserving all existing pages.

Only the template CHECK is widened. Literal lists intentionally do not import
mutable application constants. Downgrade refuses when CP24 pages exist; it
never rewrites or deletes customer data.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a24d9e7b2c10"
down_revision: str | None = "f23d7c2e5a41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = (
    "milliy",
    "atlas",
    "minimal",
    "bog",
    "romantik",
    "oltin",
    "quvnoq",
    "tungi",
    "pastel",
    "konvert",
    "foto",
    "bold",
    "geometrik",
    "akvarel",
    "vintaj",
    "oqqora",
    "bolalar",
    "suzani",
    "neon",
    "deco",
)
NEW = (
    "zarhal",
    "zumrad",
    "anor",
    "girih",
    "gulshabnam",
    "sitrus",
    "maktub",
    "chiziq",
    "sahro",
    "kamalak",
    "ilm",
    "anjuman",
    "navroz",
    "qish",
    "lavha",
    "kadr",
    "zinalar",
    "sokin",
    "marjon",
    "moviy",
)


def replace_check(names: tuple[str, ...]) -> None:
    op.drop_constraint(op.f("ck_share_pages_template_known"), "share_pages", type_="check")
    op.create_check_constraint(
        op.f("ck_share_pages_template_known"),
        "share_pages",
        "template IN (" + ", ".join("'" + name + "'" for name in names) + ")",
    )


def upgrade() -> None:
    replace_check(OLD + NEW)


def downgrade() -> None:
    replace_check(OLD)
