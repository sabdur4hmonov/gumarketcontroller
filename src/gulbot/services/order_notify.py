"""Telling the customer what the shop decided.

CLAIMED BEFORE IT IS SENT, through the same `message_log` ledger CP6 uses for
reminders. The transition key is the order and the outcome -- `order:41:rejected`
-- so the message is one call for one decision no matter how many times this
runs. Two admins racing the same card cannot produce two "your order is
confirmed" messages, and neither can a handler that crashes after Telegram
accepted but before the transaction committed.

THIS FUNCTION COMMITS. It is handed a session it did not open and commits it
twice: once after claiming, before Telegram, and once after resolving. That is
not tidy, and it is not optional -- a claim left inside the caller's
transaction is not a claim at all. The pre-deployment audit found exactly that:
the card edit failing after the customer had been messaged rolled the whole
handler back, the ledger forgot the message, and the next tap sent a second
one. See `tests/test_audit_claim_durability.py`.

BEST EFFORT, AND HONEST ABOUT IT. This sends inline, in the handler, rather than
through a queue a worker drains later, because the customer is owed the answer
now and because there is no customer-facing outbox to put it in -- `message_log`
is a claim ledger, not a queue: it has no due time and no pending state.

So a send can fail and stay failed. The commonest reason is the one no retry
fixes -- the customer blocked the bot -- and the honest response to that is not
a silent retry loop but TELLING THE SHOP, in the group, that this customer needs
a phone call. The card carries their number. `notified` False is what the
caller turns into that line, and it is the difference between a gap someone
closes and a gap nobody knows about.

The status change is NOT rolled back when the message fails. The shop decided;
that decision is a fact, and unwinding it would mean the card showed an outcome
the database disagreed with.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.i18n import t
from gulbot.models.customer import Customer
from gulbot.models.message_log import MessageStatus
from gulbot.models.order import Order, OrderStatus
from gulbot.sending.dispatcher import claim_send, resolve_send
from gulbot.sending.transport import Transport
from gulbot.utils.render import escape

log = logging.getLogger("gulbot.services.order_notify")

#: Versioned like CP6's `reminder.v1`, so a future rewording is distinguishable
#: in the ledger rather than blurred into the old one.
TEMPLATE_ORDER_STATUS = "order_status.v1"

#: The copy key for each outcome the customer is told about. A status missing
#: from here is one nobody has written a message for, which must be a loud
#: failure rather than a silent no-op -- see `_copy_key`.
OUTCOME_COPY = {
    OrderStatus.CONFIRMED: "order.status.confirmed",
    OrderStatus.REJECTED: "order.status.rejected",
}


@dataclass(frozen=True)
class Notification:
    """Whether the customer knows.

    `notified` is True when this call sent the message AND when a previous one
    already did -- both mean the customer has been told, which is the question
    the caller is actually asking. `sent_now` separates them for the log.
    """

    notified: bool
    sent_now: bool
    error: str | None = None


def transition_key(order_id: int, status: OrderStatus) -> str:
    """One key per order per outcome.

    Includes the STATUS rather than only the order id: an order that was
    confirmed and then, in some future checkpoint, cancelled, owes the customer
    two different messages and must not have the second suppressed by the
    first's claim.
    """
    return f"order:{order_id}:{status.value}"


def _copy_key(status: OrderStatus) -> str:
    key = OUTCOME_COPY.get(status)
    if key is None:  # pragma: no cover - guarded by tests/test_order_notify.py
        raise ValueError(f"no customer-facing copy for {status.value!r}")
    return key


async def notify_customer_of_outcome(
    session: AsyncSession,
    *,
    transport: Transport,
    shop_id: int,
    order_id: int,
    status: OrderStatus,
    now_utc: datetime,
    reason: str | None = None,
) -> Notification:
    """Tell the customer, exactly once."""
    row = (
        await session.execute(
            select(
                Order.customer_id,
                Customer.telegram_user_id,
                Customer.lang,
            )
            .join(Customer, Customer.id == Order.customer_id)
            .where(Order.id == order_id, Order.shop_id == shop_id)
        )
    ).one_or_none()
    if row is None:  # pragma: no cover - the caller has just transitioned it
        log.warning("order %s has no customer to notify", order_id)
        return Notification(notified=False, sent_now=False, error="order_missing")

    key = transition_key(order_id, status)
    claimed = await claim_send(
        session,
        shop_id=shop_id,
        customer_id=row.customer_id,
        template_key=TEMPLATE_ORDER_STATUS,
        transition_key=key,
        now_utc=now_utc,
        channel="telegram",
    )
    if not claimed:
        # Somebody else owns this send. Not an error and not a retry: the
        # customer either has the message or is about to.
        log.info("order %s outcome %s already claimed", order_id, status.value)
        return Notification(notified=True, sent_now=False)

    # THE PHASE BOUNDARY, and the reason this function commits a session it did
    # not open. A claim that is still inside the caller's transaction is not a
    # claim: if anything after this point rolls back -- a failed card edit, a
    # dropped connection, the process dying -- the ledger forgets a message the
    # customer already has, and the next tap sends it again.
    #
    # Same discipline as `sending/dispatcher.py`, which commits between claiming
    # and sending for exactly this reason and says so.
    await session.commit()

    # The reason is FREE TEXT an admin typed into a group. It goes into an
    # HTML-parsed message, so it is escaped here rather than trusted -- an
    # unescaped "<" would fail the send and leave the customer told nothing.
    text = t(
        _copy_key(status),
        row.lang,
        id=order_id,
        reason=escape(reason or ""),
    )
    outcome = await transport.send_text(chat_id=row.telegram_user_id, text=text)

    await resolve_send(
        session,
        customer_id=row.customer_id,
        template_key=TEMPLATE_ORDER_STATUS,
        transition_key=key,
        status=MessageStatus.SENT if outcome.ok else MessageStatus.FAILED,
        now_utc=now_utc,
        error_code=None if outcome.ok else (outcome.error_code or "unknown"),
    )
    # The outcome is durable too, so a later crash cannot turn a resolved send
    # back into an open claim.
    await session.commit()

    if outcome.ok:
        log.info(
            "order %s outcome %s -> customer as message %s",
            order_id,
            status.value,
            outcome.message_id,
        )
        return Notification(notified=True, sent_now=True)

    log.warning(
        "order %s outcome %s NOT delivered to customer: %s",
        order_id,
        status.value,
        outcome.error_code,
    )
    return Notification(notified=False, sent_now=False, error=outcome.error_code or "unknown")
