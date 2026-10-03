"""The tenancy root.

Every other table in this schema carries shop_id, even while there is exactly one
shop. Retrofitting tenancy is a data migration; carrying it from day one is a
column.
"""

from __future__ import annotations

from datetime import time
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from gulbot.db.base import Base, IdMixin, TimestampMixin

# Mon-Sun, "HH:MM" open/close pairs. null means closed that day.
# working_hours is AUTHORITATIVE for which delivery slots are offered. It is NOT
# the reminder send window (10:00-20:00), which is independent and governs
# outbound reminders only.
DEFAULT_WORKING_HOURS: dict[str, list[str] | None] = {
    "mon": ["09:00", "19:00"],
    "tue": ["09:00", "19:00"],
    "wed": ["09:00", "19:00"],
    "thu": ["09:00", "19:00"],
    "fri": ["09:00", "19:00"],
    "sat": ["09:00", "19:00"],
    "sun": ["10:00", "17:00"],
}

# Days before the occasion on which a reminder fires. -3 was deliberately dropped:
# it adds a message without adding a decision point. Per-shop only; there is no
# per-occasion override in v1.
DEFAULT_REMINDER_OFFSETS = [-7, -1, 0]


class Shop(IdMixin, TimestampMixin, Base):
    __tablename__ = "shops"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("'Asia/Tashkent'")
    )

    # Telegram wiring. Nullable: a shop exists before it is connected to a
    # channel and a group.
    channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    group_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    owner_telegram_ids: Mapped[list[int]] = mapped_column(
        ARRAY(BigInteger), nullable=False, server_default=text("'{}'::bigint[]")
    )

    # This shop's own bot, as Fernet CIPHERTEXT -- never the token itself. Read
    # and written only through gulbot.services.shop_tokens. Nullable: a shop
    # exists before its owner has handed over a token.
    bot_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    # True ONLY for the single shop that existed before per-shop tokens: it may
    # keep speaking through the process BOT_TOKEN until it stores its own. Set
    # by that migration and by nothing else; a registry logs every use of it.
    uses_process_bot_token: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # The bot's numeric id: the PUBLIC half of its token. UNIQUE -- no two shops
    # may hold one bot (two long-polls of it make Telegram answer 409 to both).
    # Written with the token, by gulbot.services.shop_tokens.
    bot_telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, unique=True)

    # The owner's own number, recorded at onboarding. Verified means Telegram's
    # contact button vouched it is the sender's -- as for customers.phone.
    owner_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    owner_phone_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    working_hours: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    # Ordering policy. Both same-day conditions must pass.
    same_day_cutoff: Mapped[time] = mapped_column(
        Time, nullable=False, server_default=text("'18:00'")
    )
    min_lead_time_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("180")
    )
    # Hours before delivery to ping the shop. An ARRAY, not two columns:
    # `reminder_offsets` already established that convention and a second one
    # would be drift. It also stops the ping count being frozen at two.
    order_ping_offset_hours: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False, server_default=text("'{3,1}'::integer[]")
    )

    # null means uncapped. Counted against delivery_date, never created_at.
    daily_order_cap: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Shop-level fallback for customers who never answered the send-time
    # question. Same representation as customers.preferred_send_time -- a real
    # time column -- so there is exactly one way to express this concept.
    #
    # NULLABLE despite having a default: it keeps the resolution chain TOTAL.
    # A shop row that somehow lacks a default still resolves, via the constant.
    # There is no admin UI to change this yet; set it in the seed or in psql.
    default_send_time: Mapped[time | None] = mapped_column(
        Time, nullable=True, server_default=text("'20:00'")
    )

    reminder_offsets: Mapped[list[int]] = mapped_column(
        ARRAY(SmallInteger), nullable=False, server_default=text("'{-7,-1,0}'::smallint[]")
    )
    # Per-customer ceiling on outbound reminders in any rolling 7 days.
    reminder_weekly_cap: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("4")
    )
    # Occasions whose dates fall within this many days collapse into one message.
    reminder_merge_window_days: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("2")
    )

    # Peak mode trips on whichever threshold comes first; the manual toggle is
    # the one that will actually get used (the shop knows March 8 is coming).
    peak_pending_threshold: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("15")
    )
    peak_hourly_threshold: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("40")
    )
    peak_manual_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    __table_args__ = (
        # A pasted plaintext token ("123456:ABC...") starts with digits; every
        # Fernet token starts "gAAAAA" -- version byte 0x80, then the high
        # bytes of a 64-bit timestamp that stay zero until the year 2106.
        CheckConstraint(
            "bot_token_encrypted IS NULL OR bot_token_encrypted LIKE 'gAAAAA%'",
            name="bot_token_is_ciphertext",
        ),
    )

    def __repr__(self) -> str:
        # Deliberately id and name only: never the token column.
        return f"<Shop id={getattr(self, 'id', None)} name={self.name!r}>"
