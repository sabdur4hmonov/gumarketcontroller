"""PASS 2 of the pre-deployment audit: races nothing else covers.

Every load-bearing constraint in this project has been mutation-proven on its
own. This module goes looking for a race BETWEEN mechanisms that were each
proven separately -- the gaps between them, which is where the ones nobody
wrote a test for live.

Anything claimed as a race is proven with two REAL connections, the standard
every prior concurrency proof here has held to. A sequential simulation of a
race proves only that the code runs twice.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime, time, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from tests.bot_harness import bound_session_factory

from gulbot.config import Settings
from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.services.order_status import reject_order
from gulbot.services.orders import OrderDraft, create_order, dates_at_capacity

pytestmark = pytest.mark.infra

DELIVERY = date(2027, 3, 8)
HOUR = time(14, 0)
SHOP_NAME = "audit-race"


def draft(*, token: str, product_id: int, day: date = DELIVERY) -> OrderDraft:
    return OrderDraft(
        product_id=product_id,
        product_name="Oq atirgul",
        price_uzs=450_000,
        telegram_file_id="f",
        delivery_date=day,
        delivery_hour=HOUR,
        landmark="Kok eshik",
        recipient_name="Dilnoza",
        submit_token=token,
        # `ck_orders_exactly_one_location` requires one of text or lat/lon.
        location_text="Chilonzor 5",
    )


@pytest.fixture
def committed(settings: Settings):  # type: ignore[no-untyped-def]
    """Committed rows on their own connection, so other connections see them.

    The savepoint-joined `db` fixture cannot express a race: every session it
    hands out shares one connection, so they serialise and the race is won by
    construction rather than by the database.
    """
    import psycopg

    dsn = (
        f"host={settings.postgres_host} port={settings.postgres_port} "
        f"user={settings.postgres_user} password={settings.postgres_password} "
        f"dbname={settings.postgres_test_db}"
    )
    with psycopg.connect(dsn, autocommit=True) as conn:
        for table in ("order_reminders", "orders", "products", "customers"):
            conn.execute(
                f"DELETE FROM {table} WHERE shop_id IN "
                f"(SELECT id FROM shops WHERE name = '{SHOP_NAME}')"
            )
        conn.execute(f"DELETE FROM shops WHERE name = '{SHOP_NAME}'")

        shop = conn.execute(
            "INSERT INTO shops (name, working_hours, group_chat_id, daily_order_cap) "
            "VALUES (%s, %s, -100999, 1) RETURNING id",
            (SHOP_NAME, json.dumps(DEFAULT_WORKING_HOURS)),
        ).fetchone()[0]
        customers = [
            conn.execute(
                "INSERT INTO customers (shop_id, telegram_user_id) VALUES (%s, %s) RETURNING id",
                (shop, 880_000 + n),
            ).fetchone()[0]
            for n in range(2)
        ]
        product = conn.execute(
            "INSERT INTO products (shop_id, name, telegram_file_id, source, "
            " channel_chat_id, channel_message_id, price_uzs, price_confidence, "
            " caption_raw, indexed_at, finalized_at, active) "
            "VALUES (%s, 'Oq atirgul', 'f', 'channel', -100777, 9001, 450000, 'high', "
            " 'caption', now(), now(), true) RETURNING id",
            (shop,),
        ).fetchone()[0]
        try:
            yield {
                "conn": conn,
                "shop": shop,
                "customers": customers,
                "product": product,
                "settings": settings,
            }
        finally:
            for table in ("order_reminders", "orders", "products", "customers"):
                conn.execute(f"DELETE FROM {table} WHERE shop_id = %s", (shop,))
            conn.execute("DELETE FROM shops WHERE id = %s", (shop,))


def engine_for(settings: Settings):  # type: ignore[no-untyped-def]
    return create_async_engine(
        settings.database_url(database=settings.postgres_test_db), future=True
    )


# --------------------------------------------------------------------------
# the daily order cap
# --------------------------------------------------------------------------


async def test_two_concurrent_submits_both_pass_a_cap_of_one(committed: dict) -> None:
    """THE CAP IS NOT ENFORCED AT SUBMIT. Two real connections, one cap slot.

    `dates_at_capacity` hides a full date from the PICKER, which was the
    standing design decision -- a full date is absent rather than offered and
    then refused after the customer has answered six questions. `create_order`
    then writes unconditionally.

    So the check and the write are not only separated, they are separated by
    the entire FSM: date, hour, location, landmark, recipient, phone, confirm.
    The window is minutes wide, not microseconds, which makes this less a race
    than a gap that two ordinary customers can walk through without hurrying.

    Documented rather than fixed: closing it changes what a customer is told
    after they have finished the flow, which is the owner's call.
    """
    settings = committed["settings"]
    shop, product = committed["shop"], committed["product"]
    customers = committed["customers"]

    async def submit(customer_id: int, token: str) -> bool:
        engine = engine_for(settings)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                # What the picker would have told this customer.
                full = await dates_at_capacity(
                    session,
                    shop_id=shop,
                    horizon_start=DELIVERY - timedelta(days=1),
                    horizon_end=DELIVERY + timedelta(days=1),
                )
                if DELIVERY in full:
                    return False
                order, created = await create_order(
                    session,
                    shop_id=shop,
                    customer_id=customer_id,
                    draft=draft(token=token, product_id=product),
                )
                await session.commit()
                return created
        finally:
            await engine.dispose()

    results = await asyncio.gather(submit(customers[0], "race-a"), submit(customers[1], "race-b"))

    placed = (
        committed["conn"]
        .execute(
            "SELECT count(*) FROM orders WHERE shop_id = %s AND delivery_date = %s",
            (shop, DELIVERY),
        )
        .fetchone()[0]
    )

    assert results == [True, True], "both submits were accepted"
    assert placed == 2, f"{placed} orders on a date whose cap is 1"


async def test_the_cap_is_not_re_checked_at_submit_at_all(committed: dict) -> None:
    """Narrower and sharper: not a timing window, an absent check.

    Even with the date ALREADY visibly at capacity -- no concurrency, no
    window, the previous order committed and readable -- `create_order` writes
    the second one. Whatever the fix is, it is not "make the check atomic";
    there is no check to make atomic.
    """
    shop, product = committed["shop"], committed["product"]
    customers = committed["customers"]
    settings = committed["settings"]

    engine = engine_for(settings)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await create_order(
                session,
                shop_id=shop,
                customer_id=customers[0],
                draft=draft(token="cap-first", product_id=product),
            )
            await session.commit()

            full = await dates_at_capacity(
                session,
                shop_id=shop,
                horizon_start=DELIVERY - timedelta(days=1),
                horizon_end=DELIVERY + timedelta(days=1),
            )
            assert DELIVERY in full, "precondition: the picker now calls this date full"

            _, created = await create_order(
                session,
                shop_id=shop,
                customer_id=customers[1],
                draft=draft(token="cap-second", product_id=product),
            )
            await session.commit()
    finally:
        await engine.dispose()

    assert created, "create_order accepted an order for a date it knows is full"


# --------------------------------------------------------------------------
# the order button on a withdrawn product
# --------------------------------------------------------------------------


async def test_an_order_can_be_started_for_a_soft_deleted_product(committed: dict) -> None:
    """`start_order` does not ask whether the product is still sellable.

    `services/bouquets.py` has one `sellable()` predicate and three callers --
    the list, the chooser and `load_product` -- so the browse VIEW correctly
    says "browse.gone" for a withdrawn product. The ORDER BUTTON under that
    same view reaches `routers/orders.py:start_order`, which runs its own query
    filtered on id and shop only.

    Deletion in this project is a SOFT delete (`deleted_at`), which is why the
    `order.gone` branch never fires: the row is still there. So a customer with
    a browse card or a reminder card open can start, and complete, an order for
    a bouquet the shop has withdrawn.
    """
    from gulbot.models.product import Product

    shop, product = committed["shop"], committed["product"]
    committed["conn"].execute(
        "UPDATE products SET deleted_at = now(), active = false WHERE id = %s", (product,)
    )

    engine = engine_for(committed["settings"])
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            from sqlalchemy import select

            from gulbot.services.bouquets import load_product

            # What the browse view sees.
            assert await load_product(session, shop_id=shop, product_id=product) is None

            # What `start_order` sees, verbatim.
            found = await session.scalar(
                select(Product).where(Product.id == product, Product.shop_id == shop)
            )
    finally:
        await engine.dispose()

    assert found is not None, (
        "start_order's query still returns a withdrawn product, so the order "
        "button under a stale card remains live"
    )


# --------------------------------------------------------------------------
# two admins, opposite buttons
# --------------------------------------------------------------------------


async def test_two_concurrent_rejections_write_exactly_one_reason(committed: dict) -> None:
    """`test_confirm_and_reject_racing_leave_exactly_one_outcome` covers two
    admins pressing DIFFERENT buttons. This covers the same one twice, which is
    the case that could write two different reasons over each other.

    Both admins typed; only one rejection happened; the stored reason is one of
    theirs and not a mixture.
    """
    settings = committed["settings"]
    shop = committed["shop"]
    order = await _place(committed, token="reject-race")

    async def reject(reason: str) -> bool:
        engine = engine_for(settings)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                result = await reject_order(session, shop_id=shop, order_id=order, reason=reason)
                await session.commit()
                return result.changed
        finally:
            await engine.dispose()

    outcomes = await asyncio.gather(reject("gul tugadi"), reject("kuryer yo'q"))

    status, reason = (
        committed["conn"]
        .execute("SELECT status, rejection_reason FROM orders WHERE id = %s", (order,))
        .fetchone()
    )

    assert sorted(outcomes) == [False, True], outcomes
    assert status == "rejected"
    assert reason in {"gul tugadi", "kuryer yo'q"}, f"a mixed or missing reason: {reason!r}"


async def test_two_customers_ordering_the_same_product_get_independent_snapshots(
    committed: dict,
) -> None:
    """The snapshot is per ORDER, not per product. Two concurrent submits for
    one bouquet must each freeze their own copy rather than share a row."""
    settings, shop, product = committed["settings"], committed["shop"], committed["product"]
    customers = committed["customers"]

    async def submit(customer_id: int, token: str) -> None:
        engine = engine_for(settings)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await create_order(
                    session,
                    shop_id=shop,
                    customer_id=customer_id,
                    draft=draft(token=token, product_id=product),
                )
                await session.commit()
        finally:
            await engine.dispose()

    await asyncio.gather(submit(customers[0], "snap-a"), submit(customers[1], "snap-b"))

    rows = (
        committed["conn"]
        .execute(
            "SELECT customer_id, product_name_snapshot, price_uzs_snapshot, "
            "telegram_file_id_snapshot "
            "FROM orders WHERE shop_id = %s ORDER BY id",
            (shop,),
        )
        .fetchall()
    )

    assert len(rows) == 2
    assert {r[0] for r in rows} == set(customers), "each order belongs to its own customer"
    assert all(r[1:] == ("Oq atirgul", 450000, "f") for r in rows), "snapshots disagree"

    # And the product row is untouched by either -- no shared mutable state.
    live = (
        committed["conn"]
        .execute("SELECT name, price_uzs FROM products WHERE id = %s", (product,))
        .fetchone()
    )
    assert live == ("Oq atirgul", 450000)


async def test_a_repriced_product_does_not_rewrite_an_existing_order(committed: dict) -> None:
    """The snapshot's whole purpose, stated against the browse entry point.

    CP10a froze these columns for the reminder path. The browse path reaches
    the same `create_order`, so it inherits the freeze -- but that is an
    inheritance worth one test rather than an assumption.
    """
    product = committed["product"]
    order = await _place(committed, token="reprice")

    committed["conn"].execute(
        "UPDATE products SET price_uzs = 999999, name = 'Renamed' WHERE id = %s", (product,)
    )

    snapshot = (
        committed["conn"]
        .execute(
            "SELECT product_name_snapshot, price_uzs_snapshot FROM orders WHERE id = %s", (order,)
        )
        .fetchone()
    )
    assert snapshot == ("Oq atirgul", 450000), "the order followed the live product"


async def _place(committed: dict, *, token: str) -> int:
    """One committed order, through the real service."""
    engine = engine_for(committed["settings"])
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            order, _ = await create_order(
                session,
                shop_id=committed["shop"],
                customer_id=committed["customers"][0],
                draft=draft(token=token, product_id=committed["product"]),
            )
            await session.commit()
            return int(order.id)
    finally:
        await engine.dispose()


# --------------------------------------------------------------------------
# the keyset cursor, while the catalogue changes underneath it
# --------------------------------------------------------------------------


async def _catalogue(db, shop: int, count: int) -> list[int]:
    """`count` products, newest first, with explicit distinct indexed_at."""
    ids = []
    for n in range(count):
        ids.append(
            int(
                (
                    await db.execute(
                        text(
                            "INSERT INTO products (shop_id, name, telegram_file_id, source, "
                            " channel_chat_id, channel_message_id, price_uzs, price_confidence, "
                            " caption_raw, indexed_at, finalized_at, active) "
                            "VALUES (:s, :n, 'f', 'channel', -100777, :mid, 100000, 'high', "
                            " 'cap', now() - make_interval(mins => :age), now(), true) "
                            "RETURNING id"
                        ),
                        {"s": shop, "n": f"b{n}", "mid": 7000 + n, "age": n},
                    )
                ).scalar_one()
            )
        )
    return ids


@pytest_asyncio.fixture
async def browse_shop(db) -> int:  # type: ignore[no-untyped-def]
    return int(
        (
            await db.execute(
                text(
                    "INSERT INTO shops (name, working_hours) "
                    "VALUES ('browse-race', CAST(:wh AS jsonb)) RETURNING id"
                ),
                {"wh": json.dumps(DEFAULT_WORKING_HOURS)},
            )
        ).scalar_one()
    )


async def test_the_cursor_survives_its_own_row_being_deleted(db, browse_shop: int) -> None:  # type: ignore[no-untyped-def]
    """Page 2 is fetched with a cursor pointing at a product that no longer
    exists. Nothing may be skipped or repeated.

    This is the property keyset pagination is CHOSEN for -- the docstring says
    an OFFSET page shifts when the catalogue changes -- so it is worth proving
    for the deletion case specifically rather than assuming it from the shape.
    The comparison is against VALUES, not a row, so a deleted cursor is still a
    perfectly good position on the index.
    """
    from gulbot.services.bouquets import list_bouquets

    await _catalogue(db, browse_shop, 7)
    async with bound_session_factory(db)() as session:
        page1 = await list_bouquets(session, shop_id=browse_shop)
        assert len(page1.bouquets) == 5 and page1.has_more
        assert page1.cursor is not None

        # The cursor IS the last row of page 1. Delete exactly that row.
        cursor = page1.cursor
        await session.execute(
            text("UPDATE products SET deleted_at = now(), active = false WHERE id = :i"),
            {"i": cursor[1]},
        )
        await session.commit()

        page2 = await list_bouquets(session, shop_id=browse_shop, after=cursor)

    first_page_ids = [b.product_id for b in page1.bouquets]
    second_page_ids = [b.product_id for b in page2.bouquets]

    assert set(first_page_ids) & set(second_page_ids) == set(), "a product appeared on both pages"
    assert len(second_page_ids) == 2, f"expected the last two, got {second_page_ids}"


async def test_deleting_a_product_ahead_of_the_cursor_skips_nothing(db, browse_shop: int) -> None:  # type: ignore[no-untyped-def]
    """The other direction: a product still to come is withdrawn mid-browse.

    It must simply be absent from page 2 -- not shift a neighbour off the end,
    which is precisely what OFFSET would do.
    """
    from gulbot.services.bouquets import list_bouquets

    ids = await _catalogue(db, browse_shop, 7)
    async with bound_session_factory(db)() as session:
        page1 = await list_bouquets(session, shop_id=browse_shop)
        assert page1.cursor is not None

        # `_catalogue` makes each product a minute older than the last, so the
        # newest-first listing is the reverse of insertion order: the final id
        # is the oldest, and sits on page 2.
        doomed = ids[-1]
        await session.execute(
            text("UPDATE products SET deleted_at = now(), active = false WHERE id = :i"),
            {"i": doomed},
        )
        await session.commit()

        page2 = await list_bouquets(session, shop_id=browse_shop, after=page1.cursor)

    assert doomed not in [b.product_id for b in page2.bouquets]
    assert len(page2.bouquets) == 1, "the withdrawn product shifted a page instead of leaving"
    assert not page2.has_more


# --------------------------------------------------------------------------
# the album debounce, crossed with an edit that withdraws the post
# --------------------------------------------------------------------------


async def _post(db, shop: int, *, message_id: int, caption: str, finalized: bool) -> None:  # type: ignore[no-untyped-def]
    await db.execute(
        text(
            "INSERT INTO products (shop_id, name, telegram_file_id, source, "
            " channel_chat_id, channel_message_id, price_uzs, price_confidence, "
            " caption_raw, indexed_at, finalized_at, active) "
            "VALUES (:s, 'b', 'f', 'channel', -100777, :mid, 100000, 'high', "
            " :cap, now(), :fin, true)"
        ),
        {
            "s": shop,
            "mid": message_id,
            "cap": caption,
            "fin": datetime.now(UTC) if finalized else None,
        },
    )


@pytest.mark.parametrize("already_finalized", [False, True], ids=["mid-debounce", "settled"])
async def test_a_late_finalize_cannot_resurrect_a_withdrawn_product(
    db, browse_shop: int, already_finalized: bool
) -> None:  # type: ignore[no-untyped-def]
    """The dangerous ordering: the shop edits the hashtag away while a debounced
    finalize is still in flight, and the finalize lands AFTER the edit.

    If `finalize_product` re-parsed and re-activated unconditionally, a product
    the shop withdrew would come back into the catalogue and the withdrawal
    would look like it silently failed.

    Both starting states, because `_drop_untagged` deliberately treats them
    differently: a row that was never finalized is DELETED (it never qualified
    as a product), an already-finalized one is DEACTIVATED (the shop is hiding
    something that may already be referenced). The invariant across both is the
    same -- afterwards it is not sellable, and the late finalize does not
    change that.

    What makes it safe is not the debounce: the row is taken `with_for_update`,
    `caption_raw` is read from the ROW at finalize time rather than carried
    from the arrival, and a stamped row is a NOOP unless forced.
    """
    from gulbot.services.bouquets import load_product
    from gulbot.services.indexer import Finalize, finalize_product

    message_id = 7777
    await _post(
        db, browse_shop, message_id=message_id, caption="#lola 100000", finalized=already_finalized
    )

    async with bound_session_factory(db)() as session:
        product_id = (
            await session.execute(
                text("SELECT id FROM products WHERE channel_message_id = :m"), {"m": message_id}
            )
        ).scalar_one()

        # The edit: the shop strips the hashtag, and the edit path re-parses
        # with force because the caption really did change.
        await session.execute(
            text("UPDATE products SET caption_raw = 'just a photo' WHERE id = :i"),
            {"i": product_id},
        )
        await finalize_product(
            session, shop_id=browse_shop, channel_message_id=message_id, force=True
        )
        await session.commit()
        assert await load_product(session, shop_id=browse_shop, product_id=product_id) is None, (
            "precondition: the edit withdrew it"
        )

        # NOW the debounced finalize fires, unforced, as the worker would run it.
        late = await finalize_product(session, shop_id=browse_shop, channel_message_id=message_id)
        await session.commit()

        assert late.outcome in {Finalize.MISSING, Finalize.NOOP}, (
            f"the late finalize did real work: {late.outcome}"
        )
        assert await load_product(session, shop_id=browse_shop, product_id=product_id) is None, (
            "a withdrawn product was resurrected by a finalize already in flight"
        )


# --------------------------------------------------------------------------
# the order path crossed with the reminder path
# --------------------------------------------------------------------------


def test_the_two_ledgers_cannot_collide_on_one_customer() -> None:
    """Order outcomes and reminders share `message_log`, and its UNIQUE key is
    (customer_id, template_key, transition_key).

    So the question is whether one customer receiving a reminder and an order
    outcome in the same minute can have one suppress the other. They cannot:
    the template keys are different constants, and the uniqueness is scoped by
    template. Asserted against the constants rather than by reasoning about
    them, because the failure mode -- a customer silently not being told their
    order was rejected because a birthday reminder claimed the same key -- is
    invisible in both paths.
    """
    from gulbot.models.message_log import TEMPLATE_REMINDER
    from gulbot.services.order_notify import TEMPLATE_ORDER_STATUS

    assert TEMPLATE_REMINDER != TEMPLATE_ORDER_STATUS


async def test_an_order_outcome_and_a_reminder_coexist_for_one_customer(
    committed: dict,
) -> None:
    """The same claim, against real rows rather than two constants.

    One customer, one reminder ledger row and one order-outcome ledger row,
    both present. The order path and the reminder path were built four
    checkpoints apart and now write to the same table.
    """
    shop = committed["shop"]
    customer = committed["customers"][0]
    engine = engine_for(committed["settings"])
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            for template, key in (
                ("reminder.v1", "occasion:1:2027:0"),
                ("order_status.v1", "order:1:confirmed"),
            ):
                await session.execute(
                    text(
                        "INSERT INTO message_log (shop_id, customer_id, channel, "
                        " template_key, transition_key, status, claimed_at, attempts) "
                        "VALUES (:s, :c, 'telegram', :t, :k, 'claimed', now(), 1)"
                    ),
                    {"s": shop, "c": customer, "t": template, "k": key},
                )
            await session.commit()
    finally:
        await engine.dispose()

    rows = (
        committed["conn"]
        .execute(
            "SELECT template_key FROM message_log WHERE customer_id = %s ORDER BY template_key",
            (customer,),
        )
        .fetchall()
    )
    assert [r[0] for r in rows] == ["order_status.v1", "reminder.v1"], (
        "one path's ledger row displaced the other's"
    )
