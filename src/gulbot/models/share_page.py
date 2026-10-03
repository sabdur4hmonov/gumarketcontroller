"""Pages a customer makes in a shop's bot and shares as a link.

Two kinds, one table:

* ``yesno``  -- a single question with a Ha and a Yo'q button, the Yo'q button
  running away from the finger. Optionally the creator is told, once, when the
  answer is Ha.
* ``invite`` -- a taklifnoma: event, names, date and time, venue, an optional
  map pin and message, and an optional RSVP.

ONE TABLE, because everything the public web service does starts from the same
lookup -- an unguessable token -- and everything the bot does is "my pages".
Kind-specific columns are nullable and a CHECK per kind says which must be
filled while the page is live.

TENANCY. ``(customer_id, shop_id)`` is a composite FK onto customers, so a page
cannot be filed under one shop while belonging to another shop's customer.
RSVPs and referrals hang off ``(page_id, shop_id)`` the same way.

DELETION SCRUBS, IT DOES NOT DROP. When the creator deletes a page, or it
expires, every field a person typed is set to NULL and ``deleted_at`` is set;
the row stays so the shop keeps its counts (views, taps on its link, customers
who arrived from it). The completeness CHECKs are written "deleted, or
complete" for exactly that reason.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum
from typing import Final

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from gulbot.db.base import Base, IdMixin, TimestampMixin


class PageKind(StrEnum):
    YESNO = "yesno"
    INVITE = "invite"


#: The ten designs. Every one of them serves both kinds.
PAGE_TEMPLATES: Final = (
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
)

#: The language the PAGE is written in -- not the customer's bot language.
PAGE_LANGUAGES: Final = ("uz", "uz_cyrl", "ru", "en")

#: Ready-made questions, plus the customer's own.
QUESTION_PRESETS: Final = ("marry", "forgive", "date", "valentine", "together", "custom")

EVENT_TYPES: Final = (
    "wedding",
    "nikoh",
    "fotiha",
    "birthday",
    "beshik",
    "sunnat",
    "anniversary",
    "graduation",
    "corporate",
    "other",
)

#: Field caps. The columns are sized to these, so Postgres refuses anything
#: longer even if a caller forgets to trim.
QUESTION_MAX = 140
NAME_MAX = 60
VENUE_MAX = 160
MESSAGE_MAX = 400
GUEST_NAME_MAX = 60
#: secrets.token_urlsafe(16) is 22 characters; the column allows some room.
TOKEN_PATTERN = "^[A-Za-z0-9_-]{20,32}$"
MAX_GUESTS = 10


def _sql_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class SharePage(IdMixin, TimestampMixin, Base):
    __tablename__ = "share_pages"

    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    #: The ONLY way to reach a page from outside. Random, never sequential.
    token: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    template: Mapped[str] = mapped_column(String(16), nullable=False)
    lang: Mapped[str] = mapped_column(String(8), nullable=False)
    #: The shop bot the page links back to, as it was when the page was made.
    #: Taken from the bot that served the conversation, which IS this shop's.
    bot_username: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # --- yesno -----------------------------------------------------------
    question_preset: Mapped[str | None] = mapped_column(String(16), nullable=True)
    question: Mapped[str | None] = mapped_column(String(QUESTION_MAX), nullable=True)
    notify_creator: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    #: First Ha. Set once, by compare-and-swap; later presses change nothing.
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: The single "they said Ha" message to the creator, claimed before it is
    #: sent. Never set without answered_at.
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- invite ----------------------------------------------------------
    event_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    name_1: Mapped[str | None] = mapped_column(String(NAME_MAX), nullable=True)
    name_2: Mapped[str | None] = mapped_column(String(NAME_MAX), nullable=True)
    #: Local to the shop's timezone. A wall-clock date and time, as printed on
    #: the invitation; the page turns it into an instant for the countdown.
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    event_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    venue: Mapped[str | None] = mapped_column(String(VENUE_MAX), nullable=True)
    location_lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    location_lon: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    message: Mapped[str | None] = mapped_column(String(MESSAGE_MAX), nullable=True)
    rsvp_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    # --- lifecycle and attribution ---------------------------------------
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    #: Taps on "Gul buyurtma qilish" -- the shop's payoff for the feature.
    cta_click_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    __table_args__ = (
        ForeignKeyConstraint(
            ["customer_id", "shop_id"],
            ["customers.id", "customers.shop_id"],
            ondelete="CASCADE",
        ),
        # What RSVPs and referrals reference, so they cannot cross shops either.
        UniqueConstraint("id", "shop_id"),
        # "My pages" and the per-customer creation limit.
        Index("ix_share_pages_shop_customer_created", "shop_id", "customer_id", "created_at"),
        Index("ix_share_pages_expires_at", "expires_at"),
        CheckConstraint(f"kind IN ({_sql_list(tuple(PageKind))})", name="kind_known"),
        CheckConstraint(f"template IN ({_sql_list(PAGE_TEMPLATES)})", name="template_known"),
        CheckConstraint(f"lang IN ({_sql_list(PAGE_LANGUAGES)})", name="lang_known"),
        CheckConstraint(
            f"question_preset IS NULL OR question_preset IN ({_sql_list(QUESTION_PRESETS)})",
            name="question_preset_known",
        ),
        CheckConstraint(
            f"event_type IS NULL OR event_type IN ({_sql_list(EVENT_TYPES)})",
            name="event_type_known",
        ),
        CheckConstraint(f"token ~ '{TOKEN_PATTERN}'", name="token_shape"),
        CheckConstraint(
            "deleted_at IS NOT NULL OR kind <> 'yesno' "
            "OR (question IS NOT NULL AND question_preset IS NOT NULL)",
            name="yesno_complete",
        ),
        CheckConstraint(
            "deleted_at IS NOT NULL OR kind <> 'invite' "
            "OR (event_type IS NOT NULL AND name_1 IS NOT NULL AND event_date IS NOT NULL "
            "AND event_time IS NOT NULL AND venue IS NOT NULL)",
            name="invite_complete",
        ),
        CheckConstraint(
            "(location_lat IS NULL AND location_lon IS NULL) "
            "OR (location_lat IS NOT NULL AND location_lon IS NOT NULL)",
            name="location_pair",
        ),
        CheckConstraint("notified_at IS NULL OR answered_at IS NOT NULL", name="notified_after_ha"),
        CheckConstraint("view_count >= 0 AND cta_click_count >= 0", name="counts_not_negative"),
    )

    @property
    def is_live(self) -> bool:
        return self.deleted_at is None

    def __repr__(self) -> str:
        # Never the token: it is the page's only secret.
        return f"<SharePage id={getattr(self, 'id', None)} kind={self.kind} shop={self.shop_id}>"


class SharePageRsvp(IdMixin, TimestampMixin, Base):
    """One browser's answer to one invitation. Answering again changes it."""

    __tablename__ = "share_page_rsvps"

    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    page_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    #: A random value the page keeps in a cookie, so a guest who answers twice
    #: updates their answer rather than counting twice. Not an identity.
    voter_key: Mapped[str] = mapped_column(String(32), nullable=False)
    answer: Mapped[str] = mapped_column(String(4), nullable=False)
    guests: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    guest_name: Mapped[str | None] = mapped_column(String(GUEST_NAME_MAX), nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["page_id", "shop_id"],
            ["share_pages.id", "share_pages.shop_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("page_id", "voter_key"),
        CheckConstraint(
            "(answer = 'no' AND guests = 0) "
            f"OR (answer = 'yes' AND guests BETWEEN 1 AND {MAX_GUESTS})",
            name="answer_and_guests",
        ),
    )


class SharePageReferral(Base):
    """A customer who arrived in the shop's bot through a page's link.

    This is how a page's orders are attributed: the orders of customers who
    came from it. Recorded once per page and customer.
    """

    __tablename__ = "share_page_referrals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    page_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["page_id", "shop_id"],
            ["share_pages.id", "share_pages.shop_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["customer_id", "shop_id"],
            ["customers.id", "customers.shop_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("page_id", "customer_id"),
    )
