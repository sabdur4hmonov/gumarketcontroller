"""Moving an order from `placed` to `confirmed` or `rejected`.

The one place in the project allowed to transition an order's status.
`tests/test_order_scope.py` still forbids it everywhere else -- CP10 wrote that
fence deliberately, and this is the checkpoint that makes ONE exception to it,
not the checkpoint that deletes it.

EVERY TRANSITION IS A COMPARE-AND-SWAP. The card lives in a group with several
admins in it, and two of them tapping Confirm within the same second is an
ordinary Tuesday, not a race worth being clever about:

    UPDATE orders SET status = 'confirmed'
    WHERE id = ... AND shop_id = ... AND status = 'placed'
    RETURNING ...

The loser gets zero rows and is told the order was already handled, rather than
both taps reporting success and the customer being messaged twice. Same
single-flight discipline as `submit_token`, `message_log` and the ping claim --
the fourth place in this project where the database, not the UI, decides.

ONLY FROM `placed`. An order already confirmed cannot be rejected by a late tap
on a card someone scrolled back to, and a rejected order cannot be confirmed.
That is the `status = 'placed'` clause doing the work, not a check in Python
that a concurrent transaction could step around.

REJECTING CANCELS THE PINGS. The 3-hour and 1-hour reminders exist to warn the
shop about a delivery; a rejected order has no delivery, and reminding anyone
about it would be worse than saying nothing. Done in the SAME transaction as
the status change, so there is no instant at which an order is rejected and its
reminders are still armed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.models.order import Order, OrderReminder, OrderStatus, PingState
from gulbot.services import premium

log = logging.getLogger("gulbot.services.order_status")

#: Long enough for a real explanation, short enough to read on a phone as part
#: of a message the customer receives.
REJECTION_REASON_MAX_LENGTH = 200

#: Ping states that are still going to fire. A sent or dead-lettered ping is
#: already finished and rewriting it would lose that fact.
CANCELLABLE_PING_STATES = (
    PingState.PENDING.value,
    PingState.FAILED.value,
    PingState.SENDING.value,
)


@dataclass(frozen=True)
class Transition:
    """What happened, in enough detail for the caller to say so.

    `changed` False with an `order` present means somebody else got there first
    -- the ordinary outcome of a double tap, and not an error.
    """

    order: Order | None
    changed: bool

    @property
    def missing(self) -> bool:
        return self.order is None

    @property
    def already_handled(self) -> bool:
        return self.order is not None and not self.changed


async def _transition(
    session: AsyncSession,
    *,
    shop_id: int,
    order_id: int,
    to: OrderStatus,
    now_utc: datetime,
    reason: str | None = None,
) -> Transition:
    """The compare-and-swap. Shared so confirm and reject cannot drift."""
    values: dict[str, object] = {"status": to.value, "status_changed_at": now_utc}
    if reason is not None:
        values["rejection_reason"] = reason[:REJECTION_REASON_MAX_LENGTH]

    changed = await session.scalar(
        update(Order)
        .where(
            Order.id == order_id,
            Order.shop_id == shop_id,
            # THE guard. Only an order nobody has acted on can move.
            Order.status == OrderStatus.PLACED.value,
        )
        .values(**values)
        .returning(Order.id)
    )
    await session.flush()

    order = await session.scalar(
        select(Order).where(Order.id == order_id, Order.shop_id == shop_id)
    )
    if order is None:
        log.warning("order %s not found for shop %s", order_id, shop_id)
        return Transition(order=None, changed=False)
    if changed is None:
        log.info("order %s was already %s", order_id, order.status)
        return Transition(order=order, changed=False)

    log.info("order %s -> %s", order_id, to.value)
    return Transition(order=order, changed=True)


async def confirm_order(
    session: AsyncSession, *, shop_id: int, order_id: int, now_utc: datetime | None = None
) -> Transition:
    """The shop has accepted it.

    CP18, the gift rule: the confirmation that actually happened (not a
    double tap's loser) also grants the customer premium share-page parts at
    this shop -- in the same transaction, so a rolled-back confirmation
    grants nothing. gulbot.services.premium decides whether it applies.
    """
    transition = await _transition(
        session,
        shop_id=shop_id,
        order_id=order_id,
        to=OrderStatus.CONFIRMED,
        now_utc=now_utc or datetime.now(UTC),
    )
    if transition.changed:
        await premium.grant_for_confirmed_order(session, shop_id=shop_id, order_id=order_id)
    return transition


async def reject_order(
    session: AsyncSession,
    *,
    shop_id: int,
    order_id: int,
    reason: str,
    now_utc: datetime | None = None,
) -> Transition:
    """The shop cannot fulfil it, and says why.

    The reason is required by the signature rather than defaulted, because a
    rejection with no explanation is the silence this whole checkpoint exists to
    remove.
    """
    now = now_utc or datetime.now(UTC)
    result = await _transition(
        session,
        shop_id=shop_id,
        order_id=order_id,
        to=OrderStatus.REJECTED,
        now_utc=now,
        reason=reason,
    )
    if result.changed:
        cancelled = await cancel_pings(session, order_id=order_id, shop_id=shop_id)
        log.info("order %s rejected; %s ping(s) cancelled", order_id, cancelled)
    return result


async def cancel_pings(session: AsyncSession, *, shop_id: int, order_id: int) -> int:
    """Stop the delivery reminders for an order that is not being delivered.

    Deliberately narrow: a ping already SENT stays sent, and a dead-lettered one
    stays parked. Rewriting either would lose a fact about what actually
    happened in exchange for tidiness.
    """
    cancelled = await session.scalars(
        update(OrderReminder)
        .where(
            OrderReminder.order_id == order_id,
            OrderReminder.shop_id == shop_id,
            OrderReminder.state.in_(CANCELLABLE_PING_STATES),
        )
        .values(state=PingState.CANCELLED.value, claimed_at=None)
        .returning(OrderReminder.id)
    )
    await session.flush()
    return len(list(cancelled))
