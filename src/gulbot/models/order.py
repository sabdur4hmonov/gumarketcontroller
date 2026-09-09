"""Orders, and the admin-ping outbox that follows them.

CP7 deliberately did NOT create this table. Its column list had already drifted
once between the original design and the CP7 brief, and `op.create_table` on an
empty table is the cheapest migration there is -- so it was left until something
actually needed it. This is that moment, and the columns below are what CP10
uses rather than what CP7 guessed.

THE SNAPSHOT COLUMNS ARE THE POINT. The catalogue is rebuilt continuously from
a channel the shop edits and deletes posts in: CP8's finalize deletes a group
that loses its hashtags, an edit rewrites a price, a deletion sweep will one day
set `deleted_at`. A live FK to `products` would let a bouquet change price, or
vanish, underneath an order already placed. So name, price and file id are
FROZEN at submit, and `product_id` is nullable with ON DELETE SET NULL: the link
is a convenience, the snapshot is the record.

STATUS holds five values from the start though this checkpoint only ever writes
'placed'. Widening a CHECK later is cheap; what is expensive is discovering the
column should have existed. Nothing here transitions a status -- no confirm, no
reject, no delivery -- and `tests/test_order_scope.py` fails the build if that
changes.
"""

from __future__ import annotations

from datetime import date, datetime, time
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from gulbot.db.base import Base, IdMixin, TimestampMixin

#: Room for "Metro yonida, 3-qavat, ko'k eshik" without inviting an essay.
LANDMARK_MAX_LENGTH = 200

#: A person's name, not a description. Shorter than the landmark on
#: purpose: a courier reads this out loud at a door.
RECIPIENT_NAME_MAX_LENGTH = 100


class OrderStatus(StrEnum):
    """Every state an order will ever have.

    CP10 writes only PLACED. The rest exist in the CHECK now so the migration
    that starts using them is additive.
    """

    PLACED = "placed"
    CONFIRMED = "confirmed"
    DELIVERED = "delivered"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class PingState(StrEnum):
    """Mirrors NotificationState, minus the states a ping cannot reach.

    There is no EXPIRED: a ping whose moment has passed is simply not created
    (see `materialize_order_pings`), and no CANCELLED, because a ping goes to
    the shop's own group -- there is no one to block the bot.

    SENDING is the CLAIM, and it is why this table needs no `message_log` row.
    CP6 needed a separate ledger because a GROUP of notification rows shares one
    message, so the claim had to live somewhere that could name the group. Here
    one ping is one message, so the row claims itself: pending -> sending is a
    compare-and-swap that COMMITS BEFORE Telegram is called, which is the whole
    reason a worker that dies mid-send cannot cause a second one.

    FAILED is retryable, not terminal -- the tick picks up 'failed' rows again.
    DEAD_LETTER is where a row stops.
    """

    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


#: States the tick will pick up and try to send.
SENDABLE_PING_STATES = (PingState.PENDING.value, PingState.FAILED.value)


ORDER_STATUSES_SQL = ", ".join(f"'{s.value}'" for s in OrderStatus)
PING_STATES_SQL = ", ".join(f"'{s.value}'" for s in PingState)


class Order(IdMixin, TimestampMixin, Base):
    __tablename__ = "orders"

    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    #: NULL for an order placed outside any occasion -- from a future browse
    #: screen, or from a reminder whose recipient was since removed.
    recipient_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    #: The catalogue row this came from, if it still exists. See the module
    #: docstring: the snapshot below is the record, this is a convenience.
    product_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    product_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    #: NULL means the post carried no parseable price. Shown to the shop as
    #: "narx operator tomonidan tasdiqlanadi", never hidden.
    price_uzs_snapshot: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_file_id_snapshot: Mapped[str] = mapped_column(Text, nullable=False)

    delivery_date: Mapped[date] = mapped_column(Date, nullable=False)
    #: Time, not an integer hour, to match `same_day_cutoff` and
    #: `default_send_time`. The picker only ever offers whole hours; the column
    #: does not need to know that.
    delivery_hour: Mapped[time] = mapped_column(Time, nullable=False)

    #: EXACTLY ONE of the text address or the lat/lon pair is stored -- the
    #: customer picks how to say where they are. Enforced by CHECK, not by
    #: application logic alone.
    delivery_location_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivery_location_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    delivery_location_lon: Mapped[float | None] = mapped_column(Float, nullable=True)

    #: WHO TAKES DELIVERY, as free text. Not the same thing as
    #: `recipient_id`: that is a saved person on the customer's own list, and
    #: the flowers are often handed to whoever answers the door. Asked at order
    #: time because only then is it knowable.
    recipient_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    #: Always asked, whichever location method was used. A dropped pin still
    #: needs "the blue gate behind the pharmacy" in Uzbekistan's addressing
    #: reality. Sanitised with CP3's sanitiser, not a second implementation.
    landmark: Mapped[str] = mapped_column(String(LANDMARK_MAX_LENGTH), nullable=False)

    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'placed'"))

    #: Minted when the confirmation screen is rendered, so both halves of a
    #: double-tap carry the SAME value. UNIQUE below is what actually makes
    #: submit single-flight: answering the callback and editing the keyboard
    #: away is a race the customer can win, a unique index is not.
    submit_token: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        # CP1's tenancy pattern, both directions: this row belongs to a shop,
        # and anything referencing it must name the shop too.
        UniqueConstraint("id", "shop_id"),
        # The single-flight guard. Two concurrent submits of one confirmation
        # screen collide here rather than both inserting.
        UniqueConstraint("shop_id", "submit_token"),
        ForeignKeyConstraint(
            ["customer_id", "shop_id"], ["customers.id", "customers.shop_id"], ondelete="RESTRICT"
        ),
        ForeignKeyConstraint(
            ["recipient_id", "shop_id"],
            ["recipients.id", "recipients.shop_id"],
            ondelete="SET NULL (recipient_id)",
        ),
        # SET NULL, not RESTRICT: the indexer legitimately deletes products, and
        # an order must survive its source post being edited away.
        # ON DELETE SET NULL (product_id), not a bare SET NULL. On a COMPOSITE
        # foreign key a bare SET NULL nulls EVERY referencing column -- here
        # that would include shop_id, which is NOT NULL, so deleting a product
        # would fail and take the indexer down with it. Postgres 15+ lets the
        # action name the column it should null. Found by the test that deletes
        # a product out from under an order.
        ForeignKeyConstraint(
            ["product_id", "shop_id"],
            ["products.id", "products.shop_id"],
            ondelete="SET NULL (product_id)",
        ),
        CheckConstraint(f"status IN ({ORDER_STATUSES_SQL})", name="status_known"),
        CheckConstraint(
            "price_uzs_snapshot IS NULL OR price_uzs_snapshot > 0", name="snapshot_price_positive"
        ),
        # The customer's choice, expressed as a constraint rather than a
        # convention: an address OR a pin, never both, never neither.
        CheckConstraint(
            "(delivery_location_text IS NOT NULL) <> (delivery_location_lat IS NOT NULL)",
            name="exactly_one_location",
        ),
        CheckConstraint(
            "(delivery_location_lat IS NULL) = (delivery_location_lon IS NULL)",
            name="coordinates_come_in_pairs",
        ),
        Index("ix_orders_shop_delivery_date", "shop_id", "delivery_date"),
        Index("ix_orders_customer", "customer_id"),
    )

    def __repr__(self) -> str:
        return f"<Order id={getattr(self, 'id', None)} status={self.status!r}>"


class OrderReminder(IdMixin, Base):
    """The admin-ping outbox. Same shape as `scheduled_notifications`.

    THE ROW IS ITS OWN LEDGER. CP6 needed a separate `message_log` because a
    GROUP of notification rows shares one message, so the claim had to live
    somewhere that could name the group. Here one ping is one row, so the row
    can be claimed in place with a state compare-and-swap -- no second table,
    and no loosening of message_log's `customer_id NOT NULL`, which an
    admin-facing ping has no value for.

    UNIQUE(order_id, ping_number) is load-bearing exactly as
    `scheduled_notifications`' key is: it is what makes materialisation
    idempotent, so running it twice cannot double-ping the shop.
    """

    __tablename__ = "order_reminders"

    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    #: 0 is the placement ANNOUNCEMENT -- due immediately, not in the offsets
    #: array. 1..n are the delivery reminders and index
    #: `shops.order_ping_offset_hours`. Both are the same kind of thing to the
    #: send path (one message to the shop, sent once, claimed the same way), so
    #: they share one outbox rather than growing a second.
    ping_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    due_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'pending'"))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    #: When this row entered SENDING. A claim older than the timeout belonged to
    #: a worker that died, and may be retaken -- the same contract message_log
    #: states for CP6, collapsed into the row it protects.
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("order_id", "ping_number"),
        ForeignKeyConstraint(
            ["order_id", "shop_id"], ["orders.id", "orders.shop_id"], ondelete="CASCADE"
        ),
        CheckConstraint(f"state IN ({PING_STATES_SQL})", name="state_known"),
        # >= 0, not > 0: ping 0 is the placement announcement. Widened at CP10b
        # by dropping and recreating this one constraint, which is what
        # CONTRIBUTING means by an additive enumeration change.
        CheckConstraint("ping_number >= 0", name="ping_number_positive"),
        # The send path's query: what is due, oldest first.
        Index("ix_order_reminders_due", "state", "due_at_utc"),
    )

    def __repr__(self) -> str:
        return f"<OrderReminder order={self.order_id} ping={self.ping_number}>"
