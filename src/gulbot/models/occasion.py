"""Recurring personal dates.

Month and day are separate integers, never a DATE: most of these dates recur
every year and many have no known year at all. A DATE column would force a
fictional year on every row and make "the 29th of February" unstorable.
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from gulbot.db.base import Base, IdMixin, TimestampMixin


class RecipientType(StrEnum):
    """WHO the date is for. Declaration order is the button order.

    Renamed from OccasionType at the onboarding review: it never described the
    occasion, only the person, and calling it a type made the confirm screen
    say "Turi: Onam" -- the recipient's name in the slot meant for the kind of
    date. What kind of date it is now lives in OccasionKind.
    """

    MOTHER = "mother"
    SPOUSE = "spouse"
    OLDER_SISTER = "older_sister"
    YOUNGER_SISTER = "younger_sister"
    PATERNAL_AUNT = "paternal_aunt"
    MATERNAL_AUNT = "maternal_aunt"
    CUSTOM = "custom"


#: Kept as an alias so nothing breaks mid-refactor.
OccasionType = RecipientType


class OccasionKind(StrEnum):
    """WHAT the date is. Asked separately from who it is for."""

    BIRTHDAY = "birthday"
    ANNIVERSARY = "anniversary"
    OTHER = "other"


LABEL_MAX_LENGTH = 64

# Largest valid day per month, assuming a leap year. February allows 29 because
# a Feb 29 occasion is legitimate; CP4 decides that it fires on Feb 28 in common
# years. This list is the single source of truth, shared by the day picker, the
# Python validator and the database CHECK constraint.
MAX_DAY_IN_MONTH = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)

#: Rendered into the CHECK constraints, so adding a preset in one place
#: cannot leave the database refusing it.
RECIPIENT_TYPES_SQL = ", ".join(f"'{t.value}'" for t in RecipientType)
OCCASION_KINDS_SQL = ", ".join(f"'{k.value}'" for k in OccasionKind)

# Rendered into the CHECK constraint so Postgres refuses Feb 30 and Apr 31 on
# its own, not merely because the picker happens to be built correctly.
_DAY_LIMIT_SQL = " ".join(
    f"WHEN {month} THEN {max_day}" for month, max_day in enumerate(MAX_DAY_IN_MONTH, start=1)
)
DAY_MATCHES_MONTH_SQL = f"day <= CASE month {_DAY_LIMIT_SQL} END"

# A Feb 29 occasion may carry a year only if that year actually had one.
# Uses mod() rather than the % operator: Alembic renders % as %% for its own
# string interpolation, and the doubled literal reaches Postgres as invalid SQL.
LEAP_YEAR_SQL = (
    "year IS NULL OR NOT (month = 2 AND day = 29) "
    "OR (mod(year, 4) = 0 AND (mod(year, 100) <> 0 OR mod(year, 400) = 0))"
)


class Occasion(IdMixin, TimestampMixin, Base):
    __tablename__ = "occasions"

    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Nullable only between the two migrations that add it; migration
    # 6a4f76c77864 validates the backfill and sets NOT NULL.
    recipient_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # DEPRECATED as of CP3.5: the person now lives in `recipients`. Kept and
    # still written so the column can be dropped in its own release, once
    # nothing reads it. Do not add new readers.
    label: Mapped[str] = mapped_column(String(LABEL_MAX_LENGTH), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)

    # WHAT this date is: a birthday, an anniversary, something else. Asked as
    # its own question -- the customer picks the person first, then the kind.
    kind: Mapped[str] = mapped_column(String(16), nullable=False)

    month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    day: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # Optional: plenty of customers know the date but not the year.
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    __table_args__ = (
        # Cross-tenant rows are unrepresentable, not merely discouraged. This is
        # what UNIQUE(customers.id, shop_id) was added for at CP1.
        ForeignKeyConstraint(
            ["customer_id", "shop_id"],
            ["customers.id", "customers.shop_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("month BETWEEN 1 AND 12", name="month_range"),
        CheckConstraint("day BETWEEN 1 AND 31", name="day_range"),
        CheckConstraint(DAY_MATCHES_MONTH_SQL, name="day_matches_month"),
        CheckConstraint("year IS NULL OR year BETWEEN 1900 AND 2100", name="year_range"),
        CheckConstraint(LEAP_YEAR_SQL, name="feb29_needs_leap_year"),
        CheckConstraint(f"type IN ({RECIPIENT_TYPES_SQL})", name="type_known"),
        CheckConstraint(f"kind IN ({OCCASION_KINDS_SQL})", name="kind_known"),
        CheckConstraint("length(btrim(label)) > 0", name="label_not_blank"),
        # The recipient must belong to the same customer. Postgres enforces it.
        ForeignKeyConstraint(
            ["recipient_id", "customer_id"],
            ["recipients.id", "recipients.customer_id"],
            ondelete="CASCADE",
        ),
        # Double-tapping confirm must not create two identical occasions.
        #
        # Keyed on the RECIPIENT, not on (customer_id, label). Two recipients
        # may share a label -- a customer can have several friends called
        # "Do'stim" -- and the old label-based key wrongly rejected the second
        # one's date as a duplicate.
        UniqueConstraint("recipient_id", "month", "day"),
        # CP1's tenancy pattern, added at CP5: it is what lets
        # scheduled_notifications declare FOREIGN KEY (occasion_id, shop_id).
        UniqueConstraint("id", "shop_id"),
        Index("ix_occasions_customer_active", "customer_id", "active"),
        Index("ix_occasions_recipient", "recipient_id"),
    )

    def __repr__(self) -> str:
        return f"<Occasion {self.label!r} {self.day:02d}.{self.month:02d}>"
