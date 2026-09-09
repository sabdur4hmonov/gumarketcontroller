"""Moving an order between statuses, against real Postgres rows.

THE CLAIM IS THE COMPARE-AND-SWAP, and it cannot be demonstrated with a fake:
"two admins tapping at once produce one transition" is a statement about what
the database does with two concurrent UPDATEs, not about what this module
intends. Several tests below would pass against an implementation that read the
status and then wrote it; the ones that would not are marked.

The shop's group has several admins in it and the card sits there indefinitely.
Two taps in the same second is an ordinary Tuesday.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker, create_async_engine
from tests.bot_harness import bound_session_factory

from gulbot.config import Settings
from gulbot.models.order import OrderStatus, PingState
from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.sending.order_card import ANNOUNCEMENT
from gulbot.services.order_status import (
    REJECTION_REASON_MAX_LENGTH,
    cancel_pings,
    confirm_order,
    reject_order,
)

pytestmark = pytest.mark.infra


async def _shop(db: AsyncConnection, *, group: int = -1001234) -> int:
    return int(
        (
            await db.execute(
                text(
                    "INSERT INTO shops (name, working_hours, group_chat_id) "
                    "VALUES ('S', CAST(:wh AS jsonb), :g) RETURNING id"
                ),
                {"wh": json.dumps(DEFAULT_WORKING_HOURS), "g": group},
            )
        ).scalar_one()
    )


async def _customer(db: AsyncConnection, shop: int, *, tg: int = 7001) -> int:
    return int(
        (
            await db.execute(
                text(
                    "INSERT INTO customers (shop_id, telegram_user_id) VALUES (:s, :t) RETURNING id"
                ),
                {"s": shop, "t": tg},
            )
        ).scalar_one()
    )


async def _order(
    db: AsyncConnection, shop: int, customer: int, *, token: str = "t1", status: str = "placed"
) -> int:
    return int(
        (
            await db.execute(
                text(
                    "INSERT INTO orders (shop_id, customer_id, product_name_snapshot, "
                    " price_uzs_snapshot, telegram_file_id_snapshot, delivery_date, "
                    " delivery_hour, delivery_location_text, landmark, status, submit_token) "
                    "VALUES (:s, :c, 'Oq atirgul', 450000, 'file-snap', :d, '14:00', "
                    " 'Chilonzor 5', 'Ko''k eshik', :st, :tok) RETURNING id"
                ),
                {
                    "s": shop,
                    "c": customer,
                    "d": date(2027, 3, 8),
                    "st": status,
                    "tok": token,
                },
            )
        ).scalar_one()
    )


async def _ping(
    db: AsyncConnection, shop: int, order: int, *, number: int, state: str = "pending"
) -> int:
    return int(
        (
            await db.execute(
                text(
                    "INSERT INTO order_reminders (shop_id, order_id, ping_number, "
                    " due_at_utc, state) VALUES (:s, :o, :n, :d, :st) RETURNING id"
                ),
                {
                    "s": shop,
                    "o": order,
                    "n": number,
                    "d": datetime.now(UTC) - timedelta(seconds=1),
                    "st": state,
                },
            )
        ).scalar_one()
    )


@pytest_asyncio.fixture
async def world(db: AsyncConnection) -> dict:
    shop = await _shop(db)
    customer = await _customer(db, shop)
    order = await _order(db, shop, customer)
    return {"db": db, "shop": shop, "customer": customer, "order": order}


async def _status(db: AsyncConnection, order: int) -> str:
    return str(
        (
            await db.execute(text("SELECT status FROM orders WHERE id = :o"), {"o": order})
        ).scalar_one()
    )


# --------------------------------------------------------------------------
# the happy paths
# --------------------------------------------------------------------------


async def test_confirm_moves_a_placed_order(world: dict) -> None:
    async with bound_session_factory(world["db"])() as session:
        result = await confirm_order(session, shop_id=world["shop"], order_id=world["order"])
        await session.commit()
    assert result.changed
    assert not result.already_handled
    assert await _status(world["db"], world["order"]) == "confirmed"


async def test_reject_records_the_reason(world: dict) -> None:
    async with bound_session_factory(world["db"])() as session:
        result = await reject_order(
            session, shop_id=world["shop"], order_id=world["order"], reason="gul tugadi"
        )
        await session.commit()
    assert result.changed
    row = (
        await world["db"].execute(
            text("SELECT status, rejection_reason FROM orders WHERE id = :o"),
            {"o": world["order"]},
        )
    ).one()
    assert row.status == "rejected"
    assert row.rejection_reason == "gul tugadi"


async def test_a_transition_stamps_when_it_happened(world: dict) -> None:
    """NULL while an order is still placed, which makes "never acted on" a
    queryable state rather than an inference from created_at."""
    before = (
        await world["db"].execute(
            text("SELECT status_changed_at FROM orders WHERE id = :o"), {"o": world["order"]}
        )
    ).scalar_one()
    assert before is None

    async with bound_session_factory(world["db"])() as session:
        await confirm_order(session, shop_id=world["shop"], order_id=world["order"])
        await session.commit()
    after = (
        await world["db"].execute(
            text("SELECT status_changed_at FROM orders WHERE id = :o"), {"o": world["order"]}
        )
    ).scalar_one()
    assert after is not None


async def test_an_overlong_reason_is_cut_to_what_the_column_holds(world: dict) -> None:
    """The admin typed a paragraph. The column is 200. Truncating beats an
    exception that would leave the order placed and the admin thinking they
    rejected it."""
    async with bound_session_factory(world["db"])() as session:
        await reject_order(
            session, shop_id=world["shop"], order_id=world["order"], reason="x" * 500
        )
        await session.commit()
    stored = (
        await world["db"].execute(
            text("SELECT rejection_reason FROM orders WHERE id = :o"), {"o": world["order"]}
        )
    ).scalar_one()
    assert len(stored) == REJECTION_REASON_MAX_LENGTH


# --------------------------------------------------------------------------
# what may NOT happen. These are the fence.
# --------------------------------------------------------------------------


async def test_only_a_placed_order_can_be_confirmed(world: dict) -> None:
    """WOULD FAIL against a read-then-write implementation only under
    concurrency -- but it fails immediately against one with no status guard at
    all, which is the likelier mistake."""
    async with bound_session_factory(world["db"])() as session:
        await reject_order(session, shop_id=world["shop"], order_id=world["order"], reason="yo'q")
        await session.commit()
    async with bound_session_factory(world["db"])() as session:
        second = await confirm_order(session, shop_id=world["shop"], order_id=world["order"])
        await session.commit()
    assert not second.changed
    assert second.already_handled
    assert await _status(world["db"], world["order"]) == "rejected"


async def test_a_confirmed_order_cannot_be_rejected_by_a_late_tap(world: dict) -> None:
    """A card scrolled back to is still a card with live buttons on it."""
    async with bound_session_factory(world["db"])() as session:
        await confirm_order(session, shop_id=world["shop"], order_id=world["order"])
        await session.commit()
    async with bound_session_factory(world["db"])() as session:
        late = await reject_order(
            session, shop_id=world["shop"], order_id=world["order"], reason="kech"
        )
        await session.commit()
    assert not late.changed
    assert late.already_handled
    assert await _status(world["db"], world["order"]) == "confirmed"


async def test_confirming_twice_changes_the_order_once(world: dict) -> None:
    async with bound_session_factory(world["db"])() as session:
        first = await confirm_order(session, shop_id=world["shop"], order_id=world["order"])
        await session.commit()
    async with bound_session_factory(world["db"])() as session:
        second = await confirm_order(session, shop_id=world["shop"], order_id=world["order"])
        await session.commit()
    assert first.changed
    assert not second.changed
    assert second.already_handled


async def test_another_shops_order_is_invisible(world: dict) -> None:
    """The shop id is in the WHERE clause, not checked afterwards. A bot
    serving two shops must not let one confirm the other's orders."""
    other_shop = await _shop(world["db"], group=-1009999)
    other_customer = await _customer(world["db"], other_shop, tg=7002)
    other_order = await _order(world["db"], other_shop, other_customer, token="t-other")

    async with bound_session_factory(world["db"])() as session:
        result = await confirm_order(session, shop_id=world["shop"], order_id=other_order)
        await session.commit()
    assert result.missing
    assert not result.changed
    assert await _status(world["db"], other_order) == "placed"


async def test_an_order_that_does_not_exist_is_reported_missing(world: dict) -> None:
    async with bound_session_factory(world["db"])() as session:
        result = await confirm_order(session, shop_id=world["shop"], order_id=999_999)
        await session.commit()
    assert result.missing


# --------------------------------------------------------------------------
# the pings a rejected order must not fire
# --------------------------------------------------------------------------


async def test_rejecting_cancels_the_pings_that_have_not_gone_yet(world: dict) -> None:
    """A rejected order has no delivery. Reminding the shop about it three
    hours beforehand would be worse than saying nothing."""
    await _ping(world["db"], world["shop"], world["order"], number=1, state="pending")
    await _ping(world["db"], world["shop"], world["order"], number=2, state="failed")

    async with bound_session_factory(world["db"])() as session:
        await reject_order(
            session, shop_id=world["shop"], order_id=world["order"], reason="gul tugadi"
        )
        await session.commit()
    states = [
        row.state
        for row in (
            await world["db"].execute(
                text("SELECT state FROM order_reminders WHERE order_id = :o ORDER BY ping_number"),
                {"o": world["order"]},
            )
        ).all()
    ]
    assert states == [PingState.CANCELLED.value, PingState.CANCELLED.value]


async def test_a_ping_already_sent_stays_sent(world: dict) -> None:
    """WOULD FAIL against a blanket UPDATE. Rewriting a sent ping would lose a
    fact about what actually happened in exchange for tidiness -- the shop DID
    receive that announcement."""
    await _ping(world["db"], world["shop"], world["order"], number=ANNOUNCEMENT, state="sent")
    await _ping(world["db"], world["shop"], world["order"], number=1, state="dead_letter")

    async with bound_session_factory(world["db"])() as session:
        cancelled = await reject_order(
            session, shop_id=world["shop"], order_id=world["order"], reason="gul tugadi"
        )
        await session.commit()
    assert cancelled.changed

    states = sorted(
        row.state
        for row in (
            await world["db"].execute(
                text("SELECT state FROM order_reminders WHERE order_id = :o"),
                {"o": world["order"]},
            )
        ).all()
    )
    assert states == ["dead_letter", "sent"]


async def test_confirming_leaves_the_delivery_pings_armed(world: dict) -> None:
    """The opposite of rejection. A confirmed order IS being delivered, so the
    three-hour warning is exactly what the shop wants."""
    await _ping(world["db"], world["shop"], world["order"], number=1, state="pending")

    async with bound_session_factory(world["db"])() as session:
        await confirm_order(session, shop_id=world["shop"], order_id=world["order"])
        await session.commit()
    state = (
        await world["db"].execute(
            text("SELECT state FROM order_reminders WHERE order_id = :o"), {"o": world["order"]}
        )
    ).scalar_one()
    assert state == PingState.PENDING.value


async def test_cancelling_pings_does_not_reach_another_orders(world: dict) -> None:
    other = await _order(world["db"], world["shop"], world["customer"], token="t2")
    await _ping(world["db"], world["shop"], world["order"], number=1)
    await _ping(world["db"], world["shop"], other, number=1)

    async with bound_session_factory(world["db"])() as session:
        count = await cancel_pings(session, shop_id=world["shop"], order_id=world["order"])
        await session.commit()

    assert count == 1
    survivor = (
        await world["db"].execute(
            text("SELECT state FROM order_reminders WHERE order_id = :o"), {"o": other}
        )
    ).scalar_one()
    assert survivor == PingState.PENDING.value


# --------------------------------------------------------------------------
# two admins, one card
# --------------------------------------------------------------------------


SHOP_NAME = "status-race"


@pytest.fixture
def committed_order(settings: Settings):  # type: ignore[no-untyped-def]
    """Committed rows: a compare-and-swap across connections needs them.

    The savepoint-joined sessions the rest of this module uses cannot express
    this test at all -- they share one connection, so they serialise, and the
    race would be won by construction rather than by the database.
    """
    import psycopg

    dsn = (
        f"host={settings.postgres_host} port={settings.postgres_port} "
        f"user={settings.postgres_user} password={settings.postgres_password} "
        f"dbname={settings.postgres_test_db}"
    )
    with psycopg.connect(dsn, autocommit=True) as conn:
        for statement in (
            f"DELETE FROM order_reminders WHERE shop_id IN "
            f"(SELECT id FROM shops WHERE name = '{SHOP_NAME}')",
            f"DELETE FROM orders WHERE shop_id IN "
            f"(SELECT id FROM shops WHERE name = '{SHOP_NAME}')",
            f"DELETE FROM customers WHERE shop_id IN "
            f"(SELECT id FROM shops WHERE name = '{SHOP_NAME}')",
            f"DELETE FROM shops WHERE name = '{SHOP_NAME}'",
        ):
            conn.execute(statement)
        shop = conn.execute(
            "INSERT INTO shops (name, working_hours, group_chat_id) "
            "VALUES (%s, %s, -1009998) RETURNING id",
            (SHOP_NAME, json.dumps(DEFAULT_WORKING_HOURS)),
        ).fetchone()[0]
        customer = conn.execute(
            "INSERT INTO customers (shop_id, telegram_user_id) VALUES (%s, 7799) RETURNING id",
            (shop,),
        ).fetchone()[0]
        order = conn.execute(
            "INSERT INTO orders (shop_id, customer_id, product_name_snapshot, "
            " price_uzs_snapshot, telegram_file_id_snapshot, delivery_date, delivery_hour, "
            " delivery_location_text, landmark, status, submit_token) "
            "VALUES (%s, %s, 'Buket', 100000, 'f', '2027-03-08', '14:00', 'Chilonzor', "
            " 'eshik', 'placed', 'status-race-tok') RETURNING id",
            (shop, customer),
        ).fetchone()[0]
        try:
            yield {"conn": conn, "shop": shop, "order": order, "settings": settings}
        finally:
            conn.execute("DELETE FROM order_reminders WHERE shop_id = %s", (shop,))
            conn.execute("DELETE FROM orders WHERE shop_id = %s", (shop,))
            conn.execute("DELETE FROM customers WHERE shop_id = %s", (shop,))
            conn.execute("DELETE FROM shops WHERE id = %s", (shop,))


async def test_two_admins_tapping_at_once_produce_one_transition(committed_order: dict) -> None:
    """THE test this module exists for, and the one a fake cannot express.

    Two SEPARATE connections, so this is two real transactions racing. Exactly
    one must report `changed`; the other must report `already_handled` rather
    than an error, because from the second admin's point of view nothing went
    wrong -- somebody was quicker.

    WOULD FAIL against a read-then-write implementation: both would read
    'placed', both would report success, and the customer would be told twice.
    """
    settings = committed_order["settings"]
    shop_id = committed_order["shop"]
    order_id = committed_order["order"]

    async def tap() -> bool:
        engine = create_async_engine(
            settings.database_url(database=settings.postgres_test_db), future=True
        )
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                result = await confirm_order(session, shop_id=shop_id, order_id=order_id)
                await session.commit()
                return result.changed
        finally:
            await engine.dispose()

    outcomes = await asyncio.gather(tap(), tap())
    assert sorted(outcomes) == [False, True], outcomes

    status = (
        committed_order["conn"]
        .execute("SELECT status FROM orders WHERE id = %s", (order_id,))
        .fetchone()[0]
    )
    assert status == OrderStatus.CONFIRMED.value


async def test_confirm_and_reject_racing_leave_exactly_one_outcome(
    committed_order: dict,
) -> None:
    """The nastier race: two admins who DISAGREE, at the same moment.

    Whichever lands first wins, and the order ends in exactly one of the two
    states -- never both, never a rejected order with no reason, never a
    confirmed one that is also rejected.
    """
    settings = committed_order["settings"]
    shop_id = committed_order["shop"]
    order_id = committed_order["order"]

    async def tap(confirming: bool) -> bool:
        engine = create_async_engine(
            settings.database_url(database=settings.postgres_test_db), future=True
        )
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                if confirming:
                    result = await confirm_order(session, shop_id=shop_id, order_id=order_id)
                else:
                    result = await reject_order(
                        session, shop_id=shop_id, order_id=order_id, reason="gul tugadi"
                    )
                await session.commit()
                return result.changed
        finally:
            await engine.dispose()

    outcomes = await asyncio.gather(tap(True), tap(False))
    assert sorted(outcomes) == [False, True], outcomes

    status, reason = (
        committed_order["conn"]
        .execute("SELECT status, rejection_reason FROM orders WHERE id = %s", (order_id,))
        .fetchone()
    )
    assert status in {OrderStatus.CONFIRMED.value, OrderStatus.REJECTED.value}
    # A rejection without its reason is the silence this checkpoint removes.
    assert (reason is not None) == (status == OrderStatus.REJECTED.value)
