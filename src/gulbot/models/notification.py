"""The outbox: one row per reminder that is due to be sent.

There are no per-reminder scheduled jobs. Rows are written ahead of time by the
nightly materializer and picked up by a beat tick (CP6).

UNIQUE(occasion_id, occurrence_year, offset_days, channel) is the only thing
preventing duplicate sends. It is a DATABASE constraint on purpose: an
application-level check loses the race between two concurrent materializer runs,
and the whole point is that a customer never gets the same reminder twice.

`occurrence_year` is the year of the OCCASION, never the year of the send. A
3 January birthday reminded on 27 December carries occurrence_year = the
January one. Key it on the send year instead and the December row and the
January row differ, so the materializer recreates both forever.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from gulbot.db.base import Base, IdMixin


class NotificationState(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    EXPIRED = "expired"


class NotificationChannel(StrEnum):
    TELEGRAM = "telegram"


#: States the materializer may delete. Anything else is HISTORY, not a
#: schedule, and reconciliation must never touch it.
RECONCILABLE_STATES = (NotificationState.PENDING.value,)


class ScheduledNotification(IdMixin, Base):
    __tablename__ = "scheduled_notifications"

    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    occasion_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    occurrence_year: Mapped[int] = mapped_column(Integer, nullable=False)
    offset_days: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    due_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'pending'"))
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Rows sharing a merge_key are ONE message covering several occasions.
    # Computed by the pure engine (CP4) and persisted verbatim; the materializer
    # never recomputes clustering.
    merge_key: Mapped[str | None] = mapped_column(String(128), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # LOAD-BEARING. The entire anti-duplicate design rests on this one line.
        UniqueConstraint("occasion_id", "occurrence_year", "offset_days", "channel"),
        ForeignKeyConstraint(
            ["occasion_id", "shop_id"],
            ["occasions.id", "occasions.shop_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["customer_id", "shop_id"],
            ["customers.id", "customers.shop_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("state IN ('pending', 'sent', 'failed', 'expired')", name="state_known"),
        CheckConstraint("channel IN ('telegram')", name="channel_known"),
        CheckConstraint("attempts >= 0", name="attempts_not_negative"),
        # A row cannot claim to have been sent without saying when.
        CheckConstraint("state <> 'sent' OR sent_at IS NOT NULL", name="sent_needs_timestamp"),
        # The CP6 beat tick scans exactly this.
        Index("ix_scheduled_notifications_due", "state", "due_at_utc"),
        Index("ix_scheduled_notifications_customer_state", "customer_id", "state"),
        Index("ix_scheduled_notifications_merge_key", "merge_key"),
    )

    def __repr__(self) -> str:
        return (
            f"<ScheduledNotification occasion={self.occasion_id} "
            f"year={self.occurrence_year} offset={self.offset_days} state={self.state}>"
        )
