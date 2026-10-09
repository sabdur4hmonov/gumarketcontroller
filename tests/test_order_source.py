# ruff: noqa: F811, F401  -- fixtures are imported by name; pytest injects them into
# the same-named test parameters, which ruff reads as a redefinition.
"""CP18: where an order came from, recorded once, at submit.

- 'reminder': the order started from a reminder's bouquet button (the only
  button that names a person);
- 'page': the customer arrived in THIS shop's bot through a share page's
  "order flowers" link within ATTRIBUTION_WINDOW -- the most recent such page;
- 'direct': anything else.

Per shop, like everything else: the same person arriving through shop B's
page does not make their order at shop A a page order -- and the database
refuses an order pointing at another shop's page.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.test_order_submit import draft, world
from tests.test_share_pages_service import yesno

from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.services import share_pages
from gulbot.services.orders import ATTRIBUTION_WINDOW, create_order

pytestmark = pytest.mark.infra


async def a_page(
    world: dict[str, Any], *, shop: int | None = None, customer: int | None = None
) -> int:
    async with world["sessions"]() as session:
        page = await share_pages.create_page(
            session,
            shop_id=shop or world["shop"],
            customer_id=customer or world["customer"],
            bot_username="lola_bot",
            draft=yesno(),
        )
        await session.commit()
    return int(page.id)


async def arrived(
    world: dict[str, Any],
    page_id: int,
    *,
    ago: timedelta,
    shop: int | None = None,
    customer: int | None = None,
) -> None:
    await world["db"].execute(
        text(
            "INSERT INTO share_page_referrals (shop_id, page_id, customer_id, created_at) "
            "VALUES (:s, :p, :c, :at)"
        ),
        {
            "s": shop or world["shop"],
            "p": page_id,
            "c": customer or world["customer"],
            "at": datetime.now(UTC) - ago,
        },
    )


async def place(
    world: dict[str, Any], token: str, **overrides: object
) -> tuple[str | None, int | None]:
    async with world["sessions"]() as session:
        order, created = await create_order(
            session,
            shop_id=world["shop"],
            customer_id=world["customer"],
            draft=draft(token, product_id=world["product"], **overrides),
        )
        await session.commit()
    assert created
    return order.source, order.source_page_id


async def test_an_order_from_a_reminders_button_is_a_reminder_order(world: dict[str, Any]) -> None:
    page = await a_page(world)
    await arrived(world, page, ago=timedelta(days=1))
    # The reminder's button wins over an earlier page visit: it is what
    # the customer actually tapped.
    assert await place(world, "r1", from_reminder=True) == ("reminder", None)


async def test_an_order_after_arriving_through_a_page_is_that_pages(world: dict[str, Any]) -> None:
    older, newer = await a_page(world), await a_page(world)
    await arrived(world, older, ago=timedelta(days=5))
    await arrived(world, newer, ago=timedelta(days=1))
    assert await place(world, "p1") == ("page", newer)


async def test_a_page_visit_outside_the_window_does_not_count(world: dict[str, Any]) -> None:
    page = await a_page(world)
    await arrived(world, page, ago=ATTRIBUTION_WINDOW + timedelta(hours=1))
    assert await place(world, "d1") == ("direct", None)


async def test_with_nothing_behind_it_an_order_is_direct(world: dict[str, Any]) -> None:
    assert await place(world, "d2") == ("direct", None)


async def test_a_visit_to_another_shops_page_is_not_attributed_here(world: dict[str, Any]) -> None:
    db = world["db"]
    other = (
        await db.execute(
            text(
                "INSERT INTO shops (name, working_hours) "
                "VALUES ('B', CAST(:wh AS jsonb)) RETURNING id"
            ),
            {"wh": __import__("json").dumps(DEFAULT_WORKING_HOURS)},
        )
    ).scalar_one()
    same_person_there = (
        await db.execute(
            text(
                "INSERT INTO customers (shop_id, telegram_user_id) VALUES (:s, 7001) RETURNING id"
            ),
            {"s": other},
        )
    ).scalar_one()
    page = await a_page(world, shop=other, customer=same_person_there)
    await arrived(world, page, ago=timedelta(hours=1), shop=other, customer=same_person_there)
    # The service must not even propose the other shop's page: the composite
    # FK behind it would refuse the order, and the customer would lose it.
    try:
        outcome: object = await place(world, "x1")
    except Exception as error:  # noqa: BLE001 - an order lost to the FK is the failure
        outcome = error
    assert outcome == ("direct", None), repr(outcome)


async def _refusal(db: AsyncConnection, sql: str, params: dict[str, Any]) -> str:
    try:
        async with db.begin_nested():
            await db.execute(text(sql), params)
    except Exception as error:  # noqa: BLE001 - the constraint's name is the assertion
        return str(error)
    return ""


async def test_the_database_refuses_another_shops_page_or_a_page_on_a_non_page_order(
    world: dict[str, Any],
) -> None:
    db = world["db"]
    await place(world, "base")
    order_id = await db.scalar(text("SELECT max(id) FROM orders"))
    other = (
        await db.execute(
            text(
                "INSERT INTO shops (name, working_hours) "
                "VALUES ('C', CAST(:wh AS jsonb)) RETURNING id"
            ),
            {"wh": __import__("json").dumps(DEFAULT_WORKING_HOURS)},
        )
    ).scalar_one()
    stranger = (
        await db.execute(
            text(
                "INSERT INTO customers (shop_id, telegram_user_id) VALUES (:s, 7002) RETURNING id"
            ),
            {"s": other},
        )
    ).scalar_one()
    foreign_page = await a_page(world, shop=other, customer=stranger)
    own_page = await a_page(world)

    crossed = await _refusal(
        db,
        "UPDATE orders SET source = 'page', source_page_id = :p WHERE id = :o",
        {"p": foreign_page, "o": order_id},
    )
    assert "fk_orders_source_page_id_shop_id_share_pages" in crossed, crossed or "accepted"
    mislabelled = await _refusal(
        db,
        "UPDATE orders SET source = 'direct', source_page_id = :p WHERE id = :o",
        {"p": own_page, "o": order_id},
    )
    assert "ck_orders_source_page_only_for_pages" in mislabelled, mislabelled or "accepted"
    unknown = await _refusal(db, "UPDATE orders SET source = 'tv' WHERE id = :o", {"o": order_id})
    assert "ck_orders_source_known" in unknown, unknown or "accepted"
    # The control: its own shop's page, on a page order, is fine.
    accepted = await _refusal(
        db,
        "UPDATE orders SET source = 'page', source_page_id = :p WHERE id = :o",
        {"p": own_page, "o": order_id},
    )
    assert accepted == ""


async def test_an_order_keeps_its_shop_when_its_page_row_goes(world: dict[str, Any]) -> None:
    """ON DELETE SET NULL (source_page_id) -- column-scoped, so shop_id stays."""
    db = world["db"]
    page = await a_page(world)
    await arrived(world, page, ago=timedelta(hours=1))
    await place(world, "gone")
    await db.execute(text("DELETE FROM share_pages WHERE id = :p"), {"p": page})
    row = (await db.execute(text("SELECT shop_id, source, source_page_id FROM orders"))).one()
    assert row == (world["shop"], "page", None)
