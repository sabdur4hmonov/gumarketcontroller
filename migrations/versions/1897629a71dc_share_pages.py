"""share pages: Ha/Yo'q pages and taklifnomas

Three new tables, nothing existing touched -- additive only:

  * `share_pages`          -- one row per page. The token is the page's whole
    address (UNIQUE, CHECK-shaped); kind-specific columns are nullable and a
    CHECK per kind says which must be filled while the page is live. Deleting
    or expiring a page NULLs what was typed and keeps the row for the shop's
    counts, which is why those CHECKs read "deleted, or complete".
  * `share_page_rsvps`     -- one browser's answer to one invitation.
  * `share_page_referrals` -- a customer who reached the shop's bot through a
    page's link: how a page's orders are attributed.

TENANCY, the CP1 pattern: `(customer_id, shop_id)` onto customers and
`(page_id, shop_id)` onto `share_pages(id, shop_id)`, so no row can join a page
of one shop to a customer or an answer of another.

Constraint order is dependency order: the parents' UNIQUE(id, shop_id) is
created with each table, before any child table names it (CONTRIBUTING, "The
migration only runs correctly on a database that does not exist yet").

Revision ID: 1897629a71dc
Revises: 0737b83c5742
Create Date: 2026-10-03 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1897629a71dc"
down_revision: str | None = "0737b83c5742"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TEMPLATES = (
    "'milliy', 'atlas', 'minimal', 'bog', 'romantik', 'oltin', 'quvnoq', 'tungi', 'pastel', "
    "'konvert'"
)
EVENTS = (
    "'wedding', 'nikoh', 'fotiha', 'birthday', 'beshik', 'sunnat', 'anniversary', "
    "'graduation', 'corporate', 'other'"
)


def upgrade() -> None:
    op.create_table(
        "share_pages",
        sa.Column("shop_id", sa.BigInteger(), nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("token", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("template", sa.String(length=16), nullable=False),
        sa.Column("lang", sa.String(length=8), nullable=False),
        sa.Column("bot_username", sa.String(length=64), nullable=True),
        sa.Column("question_preset", sa.String(length=16), nullable=True),
        sa.Column("question", sa.String(length=140), nullable=True),
        sa.Column("notify_creator", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_type", sa.String(length=16), nullable=True),
        sa.Column("name_1", sa.String(length=60), nullable=True),
        sa.Column("name_2", sa.String(length=60), nullable=True),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("event_time", sa.Time(), nullable=True),
        sa.Column("venue", sa.String(length=160), nullable=True),
        sa.Column("location_lat", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("location_lon", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("message", sa.String(length=400), nullable=True),
        sa.Column("rsvp_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("view_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("cta_click_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('yesno', 'invite')", name=op.f("ck_share_pages_kind_known")),
        sa.CheckConstraint(
            f"template IN ({TEMPLATES})", name=op.f("ck_share_pages_template_known")
        ),
        sa.CheckConstraint(
            "lang IN ('uz', 'uz_cyrl', 'ru', 'en')", name=op.f("ck_share_pages_lang_known")
        ),
        sa.CheckConstraint(
            "question_preset IS NULL OR question_preset IN ('marry', 'forgive', 'date', 'valentine', 'together', 'custom')",
            name=op.f("ck_share_pages_question_preset_known"),
        ),
        sa.CheckConstraint(
            f"event_type IS NULL OR event_type IN ({EVENTS})",
            name=op.f("ck_share_pages_event_type_known"),
        ),
        sa.CheckConstraint(
            "token ~ '^[A-Za-z0-9_-]{20,32}$'", name=op.f("ck_share_pages_token_shape")
        ),
        sa.CheckConstraint(
            "deleted_at IS NOT NULL OR kind <> 'yesno' OR (question IS NOT NULL AND question_preset IS NOT NULL)",
            name=op.f("ck_share_pages_yesno_complete"),
        ),
        sa.CheckConstraint(
            "deleted_at IS NOT NULL OR kind <> 'invite' OR (event_type IS NOT NULL AND name_1 IS NOT NULL AND event_date IS NOT NULL AND event_time IS NOT NULL AND venue IS NOT NULL)",
            name=op.f("ck_share_pages_invite_complete"),
        ),
        sa.CheckConstraint(
            "(location_lat IS NULL AND location_lon IS NULL) OR (location_lat IS NOT NULL AND location_lon IS NOT NULL)",
            name=op.f("ck_share_pages_location_pair"),
        ),
        sa.CheckConstraint(
            "notified_at IS NULL OR answered_at IS NOT NULL",
            name=op.f("ck_share_pages_notified_after_ha"),
        ),
        sa.CheckConstraint(
            "view_count >= 0 AND cta_click_count >= 0",
            name=op.f("ck_share_pages_counts_not_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["customer_id", "shop_id"],
            ["customers.id", "customers.shop_id"],
            name=op.f("fk_share_pages_customer_id_shop_id_customers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_share_pages")),
        sa.UniqueConstraint("id", "shop_id", name=op.f("uq_share_pages_id_shop_id")),
        sa.UniqueConstraint("token", name=op.f("uq_share_pages_token")),
    )
    op.create_index(
        "ix_share_pages_shop_customer_created",
        "share_pages",
        ["shop_id", "customer_id", "created_at"],
        unique=False,
    )
    op.create_index("ix_share_pages_expires_at", "share_pages", ["expires_at"], unique=False)

    op.create_table(
        "share_page_rsvps",
        sa.Column("shop_id", sa.BigInteger(), nullable=False),
        sa.Column("page_id", sa.BigInteger(), nullable=False),
        sa.Column("voter_key", sa.String(length=32), nullable=False),
        sa.Column("answer", sa.String(length=4), nullable=False),
        sa.Column("guests", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("guest_name", sa.String(length=60), nullable=True),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(answer = 'no' AND guests = 0) OR (answer = 'yes' AND guests BETWEEN 1 AND 10)",
            name=op.f("ck_share_page_rsvps_answer_and_guests"),
        ),
        sa.ForeignKeyConstraint(
            ["page_id", "shop_id"],
            ["share_pages.id", "share_pages.shop_id"],
            name=op.f("fk_share_page_rsvps_page_id_shop_id_share_pages"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_share_page_rsvps")),
        sa.UniqueConstraint(
            "page_id", "voter_key", name=op.f("uq_share_page_rsvps_page_id_voter_key")
        ),
    )

    op.create_table(
        "share_page_referrals",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("shop_id", sa.BigInteger(), nullable=False),
        sa.Column("page_id", sa.BigInteger(), nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["customer_id", "shop_id"],
            ["customers.id", "customers.shop_id"],
            name=op.f("fk_share_page_referrals_customer_id_shop_id_customers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["page_id", "shop_id"],
            ["share_pages.id", "share_pages.shop_id"],
            name=op.f("fk_share_page_referrals_page_id_shop_id_share_pages"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_share_page_referrals")),
        sa.UniqueConstraint(
            "page_id", "customer_id", name=op.f("uq_share_page_referrals_page_id_customer_id")
        ),
    )


def downgrade() -> None:
    # Children first, then the table they reference.
    op.drop_table("share_page_referrals")
    op.drop_table("share_page_rsvps")
    op.drop_index("ix_share_pages_expires_at", table_name="share_pages")
    op.drop_index("ix_share_pages_shop_customer_created", table_name="share_pages")
    op.drop_table("share_pages")
