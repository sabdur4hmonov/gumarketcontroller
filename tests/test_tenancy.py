"""Tenancy invariants, enforced by POSTGRES -- not by the ORM.

Every assertion here goes through raw SQL on purpose. An ORM-level check proves
only that our Python agreed with itself; the point of these constraints is that
they hold against a psql session, a migration script, or a future bug.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from gulbot.models.shop import DEFAULT_WORKING_HOURS


async def _make_shop(db: AsyncConnection, name: str) -> int:
    result = await db.execute(
        text(
            "INSERT INTO shops (name, working_hours) "
            "VALUES (:name, CAST(:wh AS jsonb)) RETURNING id"
        ),
        {"name": name, "wh": json.dumps(DEFAULT_WORKING_HOURS)},
    )
    return int(result.scalar_one())


async def _make_customer(db: AsyncConnection, shop_id: int, tg_id: int) -> int:
    result = await db.execute(
        text("INSERT INTO customers (shop_id, telegram_user_id) VALUES (:s, :t) RETURNING id"),
        {"s": shop_id, "t": tg_id},
    )
    return int(result.scalar_one())


@pytest.mark.infra
async def test_customer_cannot_reference_a_nonexistent_shop(db: AsyncConnection) -> None:
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await _make_customer(db, shop_id=999_999, tg_id=1)
    assert "fk_customers_shop_id_shops" in str(excinfo.value)


@pytest.mark.infra
async def test_one_customer_row_per_telegram_user_per_shop(db: AsyncConnection) -> None:
    shop = await _make_shop(db, "Shop A")
    await _make_customer(db, shop, tg_id=555)
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await _make_customer(db, shop, tg_id=555)
    assert "uq_customers_shop_id_telegram_user_id" in str(excinfo.value)


@pytest.mark.infra
async def test_same_telegram_user_may_exist_in_two_shops(db: AsyncConnection) -> None:
    """The unique constraint is per shop, not global -- multi-tenant by design."""
    a, b = await _make_shop(db, "Shop A"), await _make_shop(db, "Shop B")
    await _make_customer(db, a, tg_id=777)
    await _make_customer(db, b, tg_id=777)  # must not raise


@pytest.mark.infra
async def test_unknown_status_is_rejected_by_the_database(db: AsyncConnection) -> None:
    shop = await _make_shop(db, "Shop A")
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await db.execute(
                text(
                    "INSERT INTO customers (shop_id, telegram_user_id, status) "
                    "VALUES (:s, :t, 'nonsense')"
                ),
                {"s": shop, "t": 1},
            )
    assert "ck_customers_status_known" in str(excinfo.value)


@pytest.mark.infra
async def test_shop_with_customers_cannot_be_deleted(db: AsyncConnection) -> None:
    shop = await _make_shop(db, "Shop A")
    await _make_customer(db, shop, tg_id=1)
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await db.execute(text("DELETE FROM shops WHERE id = :s"), {"s": shop})
    assert "fk_customers_shop_id_shops" in str(excinfo.value)


@pytest.mark.infra
async def test_composite_unique_makes_cross_tenant_rows_unrepresentable(
    db: AsyncConnection,
) -> None:
    """The payoff for UNIQUE(customers.id, shop_id), which looks pointless today.

    This is what occasions (CP3) and orders (CP10) will do. Building the child
    table here proves the constraint actually supports the composite FK, rather
    than merely asserting the constraint exists.
    """
    shop_a = await _make_shop(db, "Shop A")
    shop_b = await _make_shop(db, "Shop B")
    customer_a = await _make_customer(db, shop_a, tg_id=1)

    await db.execute(
        text(
            "CREATE TABLE child_probe ("
            "  id bigserial PRIMARY KEY,"
            "  customer_id bigint NOT NULL,"
            "  shop_id bigint NOT NULL,"
            "  FOREIGN KEY (customer_id, shop_id) REFERENCES customers (id, shop_id)"
            ")"
        )
    )

    # Same tenant: accepted.
    await db.execute(
        text("INSERT INTO child_probe (customer_id, shop_id) VALUES (:c, :s)"),
        {"c": customer_a, "s": shop_a},
    )

    # Customer of shop A claimed by shop B: Postgres refuses it outright.
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await db.execute(
                text("INSERT INTO child_probe (customer_id, shop_id) VALUES (:c, :s)"),
                {"c": customer_a, "s": shop_b},
            )
    assert "child_probe" in str(excinfo.value)
