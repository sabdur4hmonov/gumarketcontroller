"""Every outbound message, claimed BEFORE it is sent.

This is an idempotency ledger, not a log. The distinction is the whole point:
a log is written after the fact and cannot stop a duplicate, because the crash
window is exactly between "Telegram accepted" and "we wrote it down".

The sequence is:

    1. INSERT ... status='claimed' ... ON CONFLICT DO NOTHING
    2. if no row was inserted, SOMEONE ELSE OWNS THIS SEND -- do not call
       Telegram at all
    3. call Telegram
    4. UPDATE the claimed row to 'sent' or 'failed'

A retry after a network blip on step 3 re-runs step 1, fails to claim, and
skips. That is what makes "the API call succeeded but our commit did not" safe.

UNIQUE(customer_id, template_key, transition_key) is deliberately a DIFFERENT
key shape from scheduled_notifications' own unique constraint. That one stops
the materializer writing a duplicate ROW; this one stops the sender making a
duplicate CALL for a batch it has already processed. Reprocessing the same due
batch after a crash has to be caught here, because the notification rows are
still 'pending' and look perfectly sendable.

CLAIMED-ROW TIMEOUT: a worker that dies between steps 1 and 4 leaves a row
stuck in 'claimed' forever. After CLAIM_TIMEOUT the row is considered abandoned
and may be re-claimed. That accepts a rare duplicate for a genuinely dead
worker, in exchange for never silently dropping a reminder. The timeout is set
well beyond any plausible in-flight API call so a live worker is never
overtaken by its own retry.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from gulbot.db.base import Base, IdMixin

#: How long a 'claimed' row may sit unresolved before another worker may take
#: it. Far longer than any Telegram call, so a live worker is never overtaken;
#: short enough that a same-day reminder is not lost to one dead process.
CLAIM_TIMEOUT = timedelta(minutes=15)

#: The reminder template. Versioned so a future rewording is distinguishable.
TEMPLATE_REMINDER = "reminder.v1"


class MessageStatus(StrEnum):
    CLAIMED = "claimed"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MessageLog(IdMixin, Base):
    __tablename__ = "message_log"

    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    template_key: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Identifies WHICH occurrence of this template. For a merged reminder it is
    #: the merge_key; for a lone one, occasion + year + offset.
    transition_key: Mapped[str] = mapped_column(String(160), nullable=False)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'claimed'")
    )
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("1"))

    claimed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # The claim. Everything above depends on this being a real constraint.
        UniqueConstraint("customer_id", "template_key", "transition_key"),
        ForeignKeyConstraint(
            ["customer_id", "shop_id"],
            ["customers.id", "customers.shop_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('claimed', 'sent', 'failed', 'cancelled')", name="status_known"
        ),
        CheckConstraint("channel IN ('telegram')", name="channel_known"),
        CheckConstraint("attempts >= 1", name="attempts_at_least_one"),
        CheckConstraint(
            "status = 'claimed' OR resolved_at IS NOT NULL", name="resolved_needs_timestamp"
        ),
        Index("ix_message_log_stuck", "status", "claimed_at"),
    )

    def __repr__(self) -> str:
        return f"<MessageLog {self.template_key}/{self.transition_key} {self.status}>"
