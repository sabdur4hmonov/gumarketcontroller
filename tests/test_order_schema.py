"""The orders schema, proven at the database layer.

Every assertion goes through raw SQL and names the constraint it expects to
fire. Per CP1: an ORM-level check proves only that our Python agreed with
itself, and these constraints exist to hold against psql, against a future
admin tool, and against whatever writes orders next.

The unique key on `order_reminders` is proven BEHAVIOURALLY -- dropped inside a
savepoint, shown to admit a duplicate, rolled back -- the same way
`scheduled_notifications`' key was proven at CP5. Asserting it exists in
`pg_constraint` would pass just as happily against a constraint that constrains
nothing.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from gulbot.models.shop import DEFAULT_WORKING_HOURS

pytestmark = pytest.mark.infra


async def _shop(db: AsyncConnection, name: str = "S") -> int:
    return int(
        (
            await db.execute(
                text(
                    "INSERT INTO shops (name, working_hours) "
                    "VALUES (:n, CAST(:wh AS jsonb)) RETURNING id"
                ),
                {"n": name, "wh": json.dumps(DEFAULT_WORKING_HOURS)},
            )
        ).scalar_one()
    )


async def _customer(db: AsyncConnection, shop: int, tg: int = 5001) -> int:
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
    db: AsyncConnection,
    shop: int,
    customer: int,
    *,
    address: str | None = "Chilonzor 5",
    lat: float | None = None,
    lon: float | None = None,
    status: str = "placed",
    token: str = "tok1",
    price: int | None = 100000,
    delivery: date = date(2027, 3, 8),
) -> int:
    return int(
        (
            await db.execute(
                text(
                    "INSERT INTO orders (shop_id, customer_id, product_name_snapshot, "
                    " price_uzs_snapshot, telegram_file_id_snapshot, delivery_date, "
                    " delivery_hour, delivery_location_text, delivery_location_lat, "
                    " delivery_location_lon, landmark, status, submit_token) "
                    "VALUES (:s, :c, 'Buket', :p, 'file1', :d, '12:00', :addr, :lat, :lon, "
                    " 'Ko''k eshik', :st, :tok) RETURNING id"
                ),
                {
                    "s": shop,
                    "c": customer,
                    "p": price,
                    "d": delivery,
                    "addr": address,
                    "lat": lat,
                    "lon": lon,
                    "st": status,
                    "tok": token,
                },
            )
        ).scalar_one()
    )


# --- exactly one location --------------------------------------------------


async def test_a_written_address_is_accepted(db: AsyncConnection) -> None:
    shop = await _shop(db)
    assert await _order(db, shop, await _customer(db, shop), address="Chilonzor 5")


async def test_a_dropped_pin_is_accepted(db: AsyncConnection) -> None:
    shop = await _shop(db)
    assert await _order(db, shop, await _customer(db, shop), address=None, lat=41.31, lon=69.24)


async def test_neither_location_is_refused(db: AsyncConnection) -> None:
    """An order nobody can deliver is not an order."""
    shop = await _shop(db)
    customer = await _customer(db, shop)
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await _order(db, shop, customer, address=None)
    assert "ck_orders_exactly_one_location" in str(excinfo.value)


async def test_both_locations_are_refused(db: AsyncConnection) -> None:
    """The customer picks ONE. Storing both leaves the courier to guess which
    the customer meant, which is exactly the ambiguity the CHECK removes."""
    shop = await _shop(db)
    customer = await _customer(db, shop)
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await _order(db, shop, customer, address="Chilonzor 5", lat=41.31, lon=69.24)
    assert "ck_orders_exactly_one_location" in str(excinfo.value)


async def test_half_a_coordinate_is_refused(db: AsyncConnection) -> None:
    """A latitude with no longitude is a point on a line, not a place."""
    shop = await _shop(db)
    customer = await _customer(db, shop)
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await _order(db, shop, customer, address=None, lat=41.31, lon=None)
    assert "ck_orders_coordinates_come_in_pairs" in str(excinfo.value)


# --- the other constraints -------------------------------------------------


async def test_an_unknown_status_is_refused(db: AsyncConnection) -> None:
    shop = await _shop(db)
    customer = await _customer(db, shop)
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await _order(db, shop, customer, status="dispatched")
    assert "ck_orders_status_known" in str(excinfo.value)


@pytest.mark.parametrize("status", ["placed", "confirmed", "delivered", "rejected", "cancelled"])
async def test_every_declared_status_is_storable(db: AsyncConnection, status: str) -> None:
    """CP10 writes only 'placed'. The others must already be storable, or the
    migration that starts using them is not additive after all."""
    shop = await _shop(db)
    assert await _order(db, shop, await _customer(db, shop), status=status)


async def test_a_zero_snapshot_price_is_refused(db: AsyncConnection) -> None:
    shop = await _shop(db)
    customer = await _customer(db, shop)
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await _order(db, shop, customer, price=0)
    assert "ck_orders_snapshot_price_positive" in str(excinfo.value)


async def test_an_unpriced_order_is_accepted(db: AsyncConnection) -> None:
    """NULL is not zero. A bouquet whose post carried no price is orderable."""
    shop = await _shop(db)
    assert await _order(db, shop, await _customer(db, shop), price=None)


async def test_two_orders_cannot_share_a_submit_token(db: AsyncConnection) -> None:
    """The single-flight guard, at the layer that actually enforces it."""
    shop = await _shop(db)
    customer = await _customer(db, shop)
    await _order(db, shop, customer, token="same")
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await _order(db, shop, customer, token="same")
    assert "uq_orders_shop_id_submit_token" in str(excinfo.value)


async def test_another_shops_customer_cannot_be_ordered_for(db: AsyncConnection) -> None:
    """CP1's tenancy pattern, proven by the DATABASE rather than the ORM."""
    shop_a, shop_b = await _shop(db, "A"), await _shop(db, "B")
    theirs = await _customer(db, shop_b, tg=6002)
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await _order(db, shop_a, theirs)
    assert "fk_orders_customer_id_shop_id_customers" in str(excinfo.value)


# --- order_reminders, proven behaviourally ---------------------------------


async def _ping(db: AsyncConnection, shop: int, order: int, number: int) -> None:
    await db.execute(
        text(
            "INSERT INTO order_reminders (shop_id, order_id, ping_number, due_at_utc) "
            "VALUES (:s, :o, :n, now())"
        ),
        {"s": shop, "o": order, "n": number},
    )


async def test_a_ping_cannot_be_scheduled_twice(db: AsyncConnection) -> None:
    shop = await _shop(db)
    order = await _order(db, shop, await _customer(db, shop))
    await _ping(db, shop, order, 1)
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await _ping(db, shop, order, 1)
    assert "uq_order_reminders_order_id_ping_number" in str(excinfo.value)


async def test_the_duplicate_is_only_refused_because_of_that_constraint(
    db: AsyncConnection,
) -> None:
    """The behavioural proof, same as CP5's for `scheduled_notifications`.

    Drop the constraint inside a savepoint and the duplicate goes straight in.
    That is the difference between a constraint that constrains and a name in
    `pg_constraint` -- asserting the latter would pass against either.
    """
    shop = await _shop(db)
    order = await _order(db, shop, await _customer(db, shop))
    await _ping(db, shop, order, 1)

    async with db.begin_nested() as nested:
        await db.execute(
            text(
                "ALTER TABLE order_reminders "
                "DROP CONSTRAINT uq_order_reminders_order_id_ping_number"
            )
        )
        await _ping(db, shop, order, 1)
        duplicates = (
            await db.execute(
                text(
                    "SELECT count(*) FROM order_reminders WHERE order_id = :o AND ping_number = 1"
                ),
                {"o": order},
            )
        ).scalar_one()
        assert duplicates == 2, "the constraint was not what refused the duplicate"
        await nested.rollback()

    # And with it restored, one row -- the duplicate never really existed.
    remaining = (
        await db.execute(
            text("SELECT count(*) FROM order_reminders WHERE order_id = :o"), {"o": order}
        )
    ).scalar_one()
    assert remaining == 1


async def test_two_pings_for_one_order_are_fine(db: AsyncConnection) -> None:
    """Guards the guard: the key must refuse a duplicate NUMBER, not a second
    ping."""
    shop = await _shop(db)
    order = await _order(db, shop, await _customer(db, shop))
    await _ping(db, shop, order, 1)
    await _ping(db, shop, order, 2)


async def test_deleting_an_order_takes_its_pings_with_it(db: AsyncConnection) -> None:
    shop = await _shop(db)
    order = await _order(db, shop, await _customer(db, shop))
    await _ping(db, shop, order, 1)
    await db.execute(text("DELETE FROM orders WHERE id = :o"), {"o": order})
    left = (
        await db.execute(
            text("SELECT count(*) FROM order_reminders WHERE order_id = :o"), {"o": order}
        )
    ).scalar_one()
    assert left == 0


async def test_an_unknown_ping_state_is_refused(db: AsyncConnection) -> None:
    shop = await _shop(db)
    order = await _order(db, shop, await _customer(db, shop))
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await db.execute(
                text(
                    "INSERT INTO order_reminders (shop_id, order_id, ping_number, due_at_utc, "
                    " state) VALUES (:s, :o, 1, now(), 'expired')"
                ),
                {"s": shop, "o": order},
            )
    assert "ck_order_reminders_state_known" in str(excinfo.value)


async def test_delivery_hour_is_a_time_not_an_integer(db: AsyncConnection) -> None:
    """Consistent with `same_day_cutoff` and `default_send_time`, which are the
    other two clock columns in the schema."""
    column = (
        await db.execute(
            text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'orders' AND column_name = 'delivery_hour'"
            )
        )
    ).scalar_one()
    assert column.startswith("time")
