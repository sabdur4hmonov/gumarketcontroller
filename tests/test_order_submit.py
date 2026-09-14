"""Submitting an order: exactly once, frozen, and pinged correctly.

THE SINGLE-FLIGHT TEST RACES TWO REAL CONNECTIONS. Two sequential calls would
pass against a check-then-insert, which is the implementation the unique index
exists to rule out: both taps read "no order yet", both insert. So the two
submits here run concurrently on separate connections against COMMITTED data,
and the assertion is on the row count, not on what either call returned.

THE SNAPSHOT TEST MUTATES THE SOURCE AFTERWARDS, because that is the situation
the columns exist for: the catalogue is rebuilt from a channel where the shop
edits prices and CP8 deletes posts that lose their hashtags. An order must not
change underneath the shop because a florist fixed a typo.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta

import psycopg
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker, create_async_engine
from tests.bot_harness import bound_session_factory

from gulbot.config import Settings
from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.services.orders import (
    OrderDraft,
    create_order,
    dates_at_capacity,
    materialize_order_pings,
    ping_times,
)

pytestmark = pytest.mark.infra

DELIVERY = date(2027, 3, 8)
HOUR = time(14, 0)


def draft(token: str = "tok-1", **overrides: object) -> OrderDraft:
    base = {
        "product_id": 0,
        "product_name": "Oq atirgul",
        "price_uzs": 450_000,
        "telegram_file_id": "file-original",
        "delivery_date": DELIVERY,
        "delivery_hour": HOUR,
        "landmark": "Ko'k eshik",
        "recipient_name": "Aziza",
        "submit_token": token,
    }
    base.update(overrides)
    base.setdefault("location_text", "Chilonzor 5")
    return OrderDraft(**base)  # type: ignore[arg-type]


# --- ping timing, pure -----------------------------------------------------


def test_a_ping_whose_moment_has_passed_is_not_created() -> None:
    """An order placed two hours before delivery gets ONE ping, not a backdated
    one. Firing "three hours to go" when it is two is worse than silence."""
    delivery = datetime(2027, 3, 8, 14, tzinfo=UTC)
    now = delivery - timedelta(hours=2)
    planned = ping_times(delivery, [3, 1], now)
    assert [number for number, _ in planned] == [2]
    assert planned[0][1] == delivery - timedelta(hours=1)


def test_both_pings_survive_when_there_is_time() -> None:
    delivery = datetime(2027, 3, 8, 14, tzinfo=UTC)
    planned = ping_times(delivery, [3, 1], delivery - timedelta(days=1))
    assert [n for n, _ in planned] == [1, 2]


def test_a_ping_exactly_now_is_not_created() -> None:
    """The boundary: due exactly now is already late by the time it is sent."""
    delivery = datetime(2027, 3, 8, 14, tzinfo=UTC)
    now = delivery - timedelta(hours=3)
    assert [n for n, _ in ping_times(delivery, [3, 1], now)] == [2]


def test_ping_numbers_follow_the_offset_array_positions() -> None:
    """Number 2 stays number 2 even when number 1 was skipped, so the unique
    key cannot be satisfied by a renumbered duplicate."""
    delivery = datetime(2027, 3, 8, 14, tzinfo=UTC)
    planned = ping_times(delivery, [6, 3, 1], delivery - timedelta(hours=4))
    assert [n for n, _ in planned] == [2, 3]


# --- against the database --------------------------------------------------


@pytest_asyncio.fixture
async def world(db: AsyncConnection) -> dict:
    shop = (
        await db.execute(
            text(
                "INSERT INTO shops (name, working_hours) "
                "VALUES ('S', CAST(:wh AS jsonb)) RETURNING id"
            ),
            {"wh": json.dumps(DEFAULT_WORKING_HOURS)},
        )
    ).scalar_one()
    customer = (
        await db.execute(
            text(
                "INSERT INTO customers (shop_id, telegram_user_id) VALUES (:s, 7001) RETURNING id"
            ),
            {"s": shop},
        )
    ).scalar_one()
    product = (
        await db.execute(
            text(
                "INSERT INTO products (shop_id, name, telegram_file_id, source, "
                " channel_message_id, price_uzs, price_confidence, finalized_at) "
                "VALUES (:s, 'Oq atirgul', 'file-original', 'channel', 1, 450000, 'high', now()) "
                "RETURNING id"
            ),
            {"s": shop},
        )
    ).scalar_one()
    return {
        "db": db,
        "shop": shop,
        "customer": customer,
        "product": product,
        "sessions": bound_session_factory(db),
    }


async def test_the_snapshot_survives_the_source_being_edited(world: dict) -> None:
    async with world["sessions"]() as session:
        order, created = await create_order(
            session,
            shop_id=world["shop"],
            customer_id=world["customer"],
            draft=draft(product_id=world["product"]),
        )
        await session.commit()
    assert created and order is not None

    # The florist fixes a price and renames the post; the indexer rewrites both.
    await world["db"].execute(
        text(
            "UPDATE products SET name = 'Qizil atirgul', price_uzs = 999999, "
            " telegram_file_id = 'file-replaced' WHERE id = :p"
        ),
        {"p": world["product"]},
    )

    row = (
        await world["db"].execute(
            text(
                "SELECT product_name_snapshot, price_uzs_snapshot, telegram_file_id_snapshot "
                "FROM orders WHERE id = :o"
            ),
            {"o": order.id},
        )
    ).one()
    assert row.product_name_snapshot == "Oq atirgul"
    assert row.price_uzs_snapshot == 450_000
    assert row.telegram_file_id_snapshot == "file-original"


async def test_the_order_outlives_the_product_being_deleted(world: dict) -> None:
    """CP8 deletes a product whose album loses its hashtags. The order stays."""
    async with world["sessions"]() as session:
        order, _ = await create_order(
            session,
            shop_id=world["shop"],
            customer_id=world["customer"],
            draft=draft(product_id=world["product"]),
        )
        await session.commit()

    await world["db"].execute(text("DELETE FROM products WHERE id = :p"), {"p": world["product"]})

    row = (
        await world["db"].execute(
            text("SELECT product_id, product_name_snapshot FROM orders WHERE id = :o"),
            {"o": order.id},
        )
    ).one()
    assert row.product_id is None, "the FK should have nulled, not cascaded the order away"
    assert row.product_name_snapshot == "Oq atirgul"


async def test_materialising_pings_twice_creates_them_once(world: dict) -> None:
    delivery_at = datetime(2027, 3, 8, 9, tzinfo=UTC)
    async with world["sessions"]() as session:
        order, _ = await create_order(
            session,
            shop_id=world["shop"],
            customer_id=world["customer"],
            draft=draft(product_id=world["product"]),
        )
        now = delivery_at - timedelta(days=1)
        first = await materialize_order_pings(
            session, order=order, delivery_at_utc=delivery_at, now_utc=now
        )
        await materialize_order_pings(
            session, order=order, delivery_at_utc=delivery_at, now_utc=now
        )
        await session.commit()

    assert first == 2
    rows = (
        (
            await world["db"].execute(
                text(
                    "SELECT ping_number FROM order_reminders "
                    "WHERE order_id = :o ORDER BY ping_number"
                ),
                {"o": order.id},
            )
        )
        .scalars()
        .all()
    )
    assert list(rows) == [1, 2], "running materialisation twice double-pinged the shop"


async def test_an_order_placed_late_gets_only_the_second_ping(world: dict) -> None:
    """End to end for the timing rule, not just the pure function."""
    delivery_at = datetime(2027, 3, 8, 9, tzinfo=UTC)
    async with world["sessions"]() as session:
        order, _ = await create_order(
            session,
            shop_id=world["shop"],
            customer_id=world["customer"],
            draft=draft(product_id=world["product"]),
        )
        written = await materialize_order_pings(
            session,
            order=order,
            delivery_at_utc=delivery_at,
            now_utc=delivery_at - timedelta(hours=2),
        )
        await session.commit()

    assert written == 1
    rows = (
        await world["db"].execute(
            text("SELECT ping_number, due_at_utc FROM order_reminders WHERE order_id = :o"),
            {"o": order.id},
        )
    ).all()
    assert [r.ping_number for r in rows] == [2]
    assert rows[0].due_at_utc == delivery_at - timedelta(hours=1)
    assert rows[0].due_at_utc > delivery_at - timedelta(hours=2), "a ping was backdated"


async def test_a_full_date_is_reported_at_capacity(world: dict) -> None:
    await world["db"].execute(
        text("UPDATE shops SET daily_order_cap = 1 WHERE id = :s"), {"s": world["shop"]}
    )
    async with world["sessions"]() as session:
        await create_order(
            session,
            shop_id=world["shop"],
            customer_id=world["customer"],
            draft=draft(product_id=world["product"]),
        )
        await session.commit()

    async with world["sessions"]() as session:
        full = await dates_at_capacity(
            session, shop_id=world["shop"], horizon_start=DELIVERY, horizon_end=DELIVERY
        )
    assert full == frozenset({DELIVERY})


async def test_no_cap_means_no_date_is_ever_full(world: dict) -> None:
    """Guards the guard: `daily_order_cap` is NULL by default and must not be
    read as zero."""
    async with world["sessions"]() as session:
        await create_order(
            session,
            shop_id=world["shop"],
            customer_id=world["customer"],
            draft=draft(product_id=world["product"]),
        )
        await session.commit()
    async with world["sessions"]() as session:
        assert (
            await dates_at_capacity(
                session, shop_id=world["shop"], horizon_start=DELIVERY, horizon_end=DELIVERY
            )
            == frozenset()
        )


# --- the race, on two real connections -------------------------------------


@pytest.fixture
def committed_world(settings: Settings) -> Iterator[dict]:
    """Committed, because the two racing submits use their own connections."""
    dsn = (
        f"host={settings.postgres_host} port={settings.postgres_port} "
        f"user={settings.postgres_user} password={settings.postgres_password.get_secret_value()} "
        f"dbname={settings.postgres_test_db}"
    )
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(
            "DELETE FROM order_reminders WHERE shop_id IN "
            "(SELECT id FROM shops WHERE name = 'submit-race')"
        )
        conn.execute(
            "DELETE FROM orders WHERE shop_id IN (SELECT id FROM shops WHERE name = 'submit-race')"
        )
        conn.execute(
            "DELETE FROM customers WHERE shop_id IN "
            "(SELECT id FROM shops WHERE name = 'submit-race')"
        )
        conn.execute("DELETE FROM shops WHERE name = 'submit-race'")
        shop = conn.execute(
            "INSERT INTO shops (name, working_hours) VALUES ('submit-race', %s) RETURNING id",
            (json.dumps(DEFAULT_WORKING_HOURS),),
        ).fetchone()[0]
        customer = conn.execute(
            "INSERT INTO customers (shop_id, telegram_user_id) VALUES (%s, 7777) RETURNING id",
            (shop,),
        ).fetchone()[0]
        try:
            yield {"conn": conn, "shop": shop, "customer": customer, "settings": settings}
        finally:
            conn.execute("DELETE FROM order_reminders WHERE shop_id = %s", (shop,))
            conn.execute("DELETE FROM orders WHERE shop_id = %s", (shop,))
            conn.execute("DELETE FROM customers WHERE shop_id = %s", (shop,))
            conn.execute("DELETE FROM shops WHERE id = %s", (shop,))


async def test_a_double_tap_creates_exactly_one_order(committed_world: dict) -> None:
    """CONCURRENT, not sequential. Sequential calls would pass against a
    check-then-insert, which is precisely the implementation this rules out.
    """
    settings = committed_world["settings"]
    engine = create_async_engine(
        settings.database_url(database=settings.postgres_test_db), future=True
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def submit() -> bool:
        async with sessions() as session:
            _, created = await create_order(
                session,
                shop_id=committed_world["shop"],
                customer_id=committed_world["customer"],
                draft=draft(token="double-tap"),
            )
            await session.commit()
            return created

    try:
        outcomes = await asyncio.gather(submit(), submit())
    finally:
        await engine.dispose()

    rows = (
        committed_world["conn"]
        .execute(
            "SELECT count(*) FROM orders WHERE shop_id = %s AND submit_token = 'double-tap'",
            (committed_world["shop"],),
        )
        .fetchone()[0]
    )
    assert rows == 1, f"a double tap created {rows} orders"
    assert sorted(outcomes) == [False, True], "both calls believed they created the order"
