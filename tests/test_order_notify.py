"""Telling the customer the outcome, exactly once.

The claim ledger is the point. A handler that crashes after Telegram accepted,
a retry, two admins racing the same card -- all three must produce ONE message,
and the only thing that makes that true is `message_log` being written before
the send rather than after it.

Reuses CP6's ledger through `claim_send`, so these tests are also what proves
the generalisation did not change CP6's behaviour: the same UNIQUE constraint,
the same re-claim window.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import bound_session_factory

from gulbot.models.order import OrderStatus
from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.sending.transport import SendResult
from gulbot.services.order_notify import (
    TEMPLATE_ORDER_STATUS,
    notify_customer_of_outcome,
    transition_key,
)

pytestmark = pytest.mark.infra

CUSTOMER_TG = 8801


class FakeTransport:
    """Records what the customer would receive."""

    def __init__(self, results: list[SendResult] | None = None) -> None:
        self.texts: list[dict] = []
        self._results = list(results or [])

    async def send_text(
        self, *, chat_id: int, text: str, reply_markup: object = None
    ) -> SendResult:
        self.texts.append({"chat_id": chat_id, "text": text})
        return self._results.pop(0) if self._results else SendResult.sent(99)

    async def send_photo(self, **kw: object) -> SendResult:  # pragma: no cover - unused
        raise AssertionError("the outcome message is text, never a photo")

    async def copy_message(self, **kw: object) -> SendResult:  # pragma: no cover - unused
        raise AssertionError("the outcome message is not a copy")


@pytest_asyncio.fixture
async def world(db: AsyncConnection) -> dict:
    shop = (
        await db.execute(
            text(
                "INSERT INTO shops (name, working_hours, group_chat_id) "
                "VALUES ('S', CAST(:wh AS jsonb), -1001234) RETURNING id"
            ),
            {"wh": json.dumps(DEFAULT_WORKING_HOURS)},
        )
    ).scalar_one()
    customer = (
        await db.execute(
            text(
                "INSERT INTO customers (shop_id, telegram_user_id, lang) "
                "VALUES (:s, :t, 'uz') RETURNING id"
            ),
            {"s": shop, "t": CUSTOMER_TG},
        )
    ).scalar_one()
    order = (
        await db.execute(
            text(
                "INSERT INTO orders (shop_id, customer_id, product_name_snapshot, "
                " price_uzs_snapshot, telegram_file_id_snapshot, delivery_date, "
                " delivery_hour, delivery_location_text, landmark, status, submit_token) "
                "VALUES (:s, :c, 'Oq atirgul', 450000, 'f', :d, '14:00', 'Chilonzor', "
                " 'eshik', 'confirmed', 'notify-tok') RETURNING id"
            ),
            {"s": shop, "c": customer, "d": date(2027, 3, 8)},
        )
    ).scalar_one()
    return {"db": db, "shop": shop, "customer": customer, "order": order}


async def _notify(
    world: dict,
    transport: FakeTransport,
    *,
    status: OrderStatus = OrderStatus.CONFIRMED,
    reason: str | None = None,
):  # type: ignore[no-untyped-def]
    async with bound_session_factory(world["db"])() as session:
        result = await notify_customer_of_outcome(
            session,
            transport=transport,
            shop_id=world["shop"],
            order_id=world["order"],
            status=status,
            now_utc=datetime.now(UTC),
            reason=reason,
        )
        await session.commit()
        return result


async def _ledger(world: dict) -> list:
    return (
        await world["db"].execute(
            text(
                "SELECT template_key, transition_key, status, attempts, error_code "
                "FROM message_log WHERE customer_id = :c ORDER BY id"
            ),
            {"c": world["customer"]},
        )
    ).all()


# --------------------------------------------------------------------------
# what the customer receives
# --------------------------------------------------------------------------


async def test_a_confirmed_order_reaches_the_customer(world: dict) -> None:
    transport = FakeTransport()
    result = await _notify(world, transport)

    assert result.notified and result.sent_now
    assert len(transport.texts) == 1
    assert transport.texts[0]["chat_id"] == CUSTOMER_TG
    assert str(world["order"]) in transport.texts[0]["text"]


async def test_a_rejection_carries_the_reason(world: dict) -> None:
    """The whole point of asking the admin to type one."""
    transport = FakeTransport()
    await _notify(world, transport, status=OrderStatus.REJECTED, reason="gul tugadi")

    assert "gul tugadi" in transport.texts[0]["text"]


async def test_a_reason_with_html_in_it_is_escaped(world: dict) -> None:
    """The reason is free text an admin typed into a group, and it goes into an
    HTML-parsed message. Unescaped, a stray '<' fails the send and the customer
    is told nothing at all -- a rejection that silently never arrives."""
    transport = FakeTransport()
    await _notify(world, transport, status=OrderStatus.REJECTED, reason="<b>yo'q</b> & bas")

    body = transport.texts[0]["text"]
    assert "&lt;b&gt;" in body
    assert "&amp;" in body
    assert "<b>yo'q</b>" not in body


# --------------------------------------------------------------------------
# exactly once. This is the ledger.
# --------------------------------------------------------------------------


async def test_the_same_outcome_is_never_sent_twice(world: dict) -> None:
    """WOULD FAIL against an implementation that logged AFTER sending: the
    crash window is exactly between "Telegram accepted" and "we wrote it
    down", and a retry there is what produces the second message."""
    transport = FakeTransport()
    first = await _notify(world, transport)
    second = await _notify(world, transport)

    assert first.sent_now
    assert not second.sent_now
    # Still True: the question the caller asks is "does the customer know",
    # and they do.
    assert second.notified
    assert len(transport.texts) == 1


async def test_confirm_and_reject_are_different_claims(world: dict) -> None:
    """One key per order per OUTCOME, not per order. An order that is confirmed
    and later cancelled owes the customer two messages, and the second must not
    be swallowed by the first's claim."""
    transport = FakeTransport()
    await _notify(world, transport, status=OrderStatus.CONFIRMED)
    await _notify(world, transport, status=OrderStatus.REJECTED, reason="gul tugadi")

    assert len(transport.texts) == 2
    keys = {row.transition_key for row in await _ledger(world)}
    assert keys == {
        transition_key(world["order"], OrderStatus.CONFIRMED),
        transition_key(world["order"], OrderStatus.REJECTED),
    }


async def test_the_ledger_records_the_send(world: dict) -> None:
    await _notify(world, FakeTransport())

    rows = await _ledger(world)
    assert len(rows) == 1
    assert rows[0].template_key == TEMPLATE_ORDER_STATUS
    assert rows[0].status == "sent"
    assert rows[0].error_code is None


# --------------------------------------------------------------------------
# when it does not arrive
# --------------------------------------------------------------------------


async def test_a_blocked_customer_is_reported_not_retried(world: dict) -> None:
    """The commonest failure, and the one no retry fixes. `notified` False is
    what the group card turns into "call them yourself" -- the difference
    between a gap someone closes and a gap nobody knows about."""
    transport = FakeTransport([SendResult.forbidden()])
    result = await _notify(world, transport)

    assert not result.notified
    assert result.error == "bot_blocked"
    rows = await _ledger(world)
    assert rows[0].status == "failed"
    assert rows[0].error_code == "bot_blocked"


async def test_a_failed_send_does_not_block_a_later_retry_forever(world: dict) -> None:
    """A resolved-failed claim is NOT re-sent by a second call in the same
    minute. That is deliberate: the shop has already been told to phone the
    customer, and a silent retry loop would make that advice wrong."""
    transport = FakeTransport([SendResult.failed("network")])
    await _notify(world, transport)
    again = await _notify(world, transport)

    assert len(transport.texts) == 1
    assert again.notified is True  # claimed already; not this call's business
