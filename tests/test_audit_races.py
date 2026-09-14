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
from datetime import UTC, date, datetime, time
from pathlib import Path

import pytest
import pytest_asyncio
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from tests.bot_harness import bound_session_factory, make_bot

from gulbot.bot.callbacks import OrderConfirmCB, OrderHourCB, OrderStartCB
from gulbot.bot.factory import build_dispatcher
from gulbot.bot.states import PlaceOrder
from gulbot.config import Settings
from gulbot.i18n.catalog import CATALOG
from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.services.order_status import reject_order
from gulbot.services.orders import OrderDraft, create_order

pytestmark = pytest.mark.infra

REPO_ROOT = Path(__file__).resolve().parents[1]

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
        f"user={settings.postgres_user} password={settings.postgres_password.get_secret_value()} "
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


# --------------------------------------------------------------------------
# the order button on a withdrawn product
# --------------------------------------------------------------------------


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


# --------------------------------------------------------------------------
# the real flow, driven through the real dispatcher
# --------------------------------------------------------------------------


def confirm_tap(*, user_id: int, update_id: int) -> Update:
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id=f"cb{update_id}",
            from_user=User(id=user_id, is_bot=False, first_name="Mijoz"),
            chat_instance=f"chat{update_id}",
            data=OrderConfirmCB(action="submit").pack(),
            message=Message(
                message_id=update_id,
                date=datetime.now(tz=UTC),
                chat=Chat(id=user_id, type="private"),
                from_user=User(id=1, is_bot=True, first_name="bot"),
                text="confirm",
            ),
        ),
    )


async def _armed_dispatcher(settings: Settings, shop: int, user_id: int, *, day: date):  # type: ignore[no-untyped-def]
    """A dispatcher on its OWN engine, with one customer parked on the
    confirmation screen having answered every question."""
    engine = engine_for(settings)
    bot, recorder = make_bot()
    dispatcher = build_dispatcher(
        session_factory=async_sessionmaker(engine, expire_on_commit=False),
        shop_id=shop,
        storage=MemoryStorage(),
        schedule_finalize=lambda **kwargs: None,
    )
    context = dispatcher.fsm.get_context(bot, user_id, user_id)
    await context.set_state(PlaceOrder.confirming)
    await context.update_data(
        product_id=None,  # filled by the caller
        delivery_date=day.isoformat(),
        delivery_hour=14,
        landmark="Kok eshik",
        recipient_name="Dilnoza",
        location_text="Chilonzor 5",
        submit_token=f"flow-{user_id}",
    )
    return engine, bot, recorder, dispatcher, context


async def test_two_concurrent_submits_leave_exactly_one_order_on_a_cap_of_one(
    committed: dict,
) -> None:
    """THE regression test for the cap, at the level a customer meets it.

    Two customers, two connections, two dispatchers, one slot. Exactly one
    order may land. The loser must be TOLD and sent back to date selection --
    not silently accepted (the shop is overcommitted) and not silently dropped
    (the customer thinks they ordered).
    """
    settings, shop, product = committed["settings"], committed["shop"], committed["product"]

    async def submit(user_id: int, update_id: int) -> list[str]:
        engine, bot, recorder, dispatcher, context = await _armed_dispatcher(
            settings, shop, user_id, day=DELIVERY
        )
        await context.update_data(
            product_id=product,
            product_name="Oq atirgul",
            price_uzs=450_000,
            telegram_file_id="f",
        )
        try:
            await dispatcher.feed_update(bot, confirm_tap(user_id=user_id, update_id=update_id))
            return recorder.sent_texts
        finally:
            await engine.dispose()

    both = await asyncio.gather(submit(880_000, 1), submit(880_001, 2))

    placed = (
        committed["conn"]
        .execute(
            "SELECT count(*) FROM orders WHERE shop_id = %s AND delivery_date = %s",
            (shop, DELIVERY),
        )
        .fetchone()[0]
    )
    assert placed == 1, f"{placed} orders landed on a date whose cap is 1"

    filled = [texts for texts in both if any("joylar tugadi" in x for x in texts)]
    accepted = [
        texts for texts in both if any("qabul qilindi" in x or "Buyurtma" in x for x in texts)
    ]
    assert len(filled) == 1, "the loser was not told the date had filled"
    assert len(accepted) == 1, "the winner was not confirmed"


async def test_the_loser_keeps_every_answer_they_already_gave(committed: dict) -> None:
    """Being bounced costs the DATE and nothing else.

    The point of the redirect over a plain refusal: re-asking for an address,
    a landmark, a recipient and a phone number would punish this customer for
    someone else's timing.
    """
    settings, shop, product = committed["settings"], committed["shop"], committed["product"]

    # Fill the date first, so the next submit is guaranteed to lose.
    await _place(committed, token="cap-taken")

    engine, bot, recorder, dispatcher, context = await _armed_dispatcher(
        settings, shop, 880_001, day=DELIVERY
    )
    await context.update_data(
        product_id=product,
        product_name="Oq atirgul",
        price_uzs=450_000,
        telegram_file_id="f",
    )
    try:
        await dispatcher.feed_update(bot, confirm_tap(user_id=880_001, update_id=3))
        kept = await context.get_data()
        state = await context.get_state()
    finally:
        await engine.dispose()

    assert any("joylar tugadi" in x for x in recorder.sent_texts), "the customer was not told"
    assert state == PlaceOrder.choosing_date.state, f"not returned to date selection: {state}"
    assert kept["landmark"] == "Kok eshik"
    assert kept["location_text"] == "Chilonzor 5"
    assert kept["recipient_name"] == "Dilnoza"
    assert kept["resume_at_confirm"] is True, "the resume flag was not set"

    placed = (
        committed["conn"]
        .execute("SELECT count(*) FROM orders WHERE shop_id = %s", (shop,))
        .fetchone()[0]
    )
    assert placed == 1, "the bounced submit still wrote an order"


async def test_the_order_button_on_a_withdrawn_bouquet_does_nothing(committed: dict) -> None:
    """THE regression test for the sellability gap, at the level a customer
    meets it: a real tap on a real stale card.

    `start_order` now goes through `load_product`, the same predicate the browse
    view uses, so the two can no longer disagree about what is sellable.
    """
    settings, shop, product = committed["settings"], committed["shop"], committed["product"]
    committed["conn"].execute(
        "UPDATE products SET deleted_at = now(), active = false WHERE id = %s", (product,)
    )

    engine = engine_for(settings)
    bot, recorder = make_bot()
    dispatcher = build_dispatcher(
        session_factory=async_sessionmaker(engine, expire_on_commit=False),
        shop_id=shop,
        storage=MemoryStorage(),
        schedule_finalize=lambda **kwargs: None,
    )
    tap_it = Update(
        update_id=9,
        callback_query=CallbackQuery(
            id="cb9",
            from_user=User(id=880_000, is_bot=False, first_name="Mijoz"),
            chat_instance="chat9",
            data=OrderStartCB(product_id=product).pack(),
            message=Message(
                message_id=9,
                date=datetime.now(tz=UTC),
                chat=Chat(id=880_000, type="private"),
                from_user=User(id=1, is_bot=True, first_name="bot"),
                text="card",
            ),
        ),
    )
    try:
        await dispatcher.feed_update(bot, tap_it)
        state = await dispatcher.fsm.get_context(bot, 880_000, 880_000).get_state()
    finally:
        await engine.dispose()

    assert any(CATALOG["order.gone"]["uz"] in x for x in recorder.sent_texts), (
        f"the customer was not told the bouquet is gone: {recorder.sent_texts}"
    )
    assert state is None, "the order flow started for a withdrawn bouquet"


def hour_tap(*, user_id: int, hour: int, update_id: int) -> Update:
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id=f"cb{update_id}",
            from_user=User(id=user_id, is_bot=False, first_name="Mijoz"),
            chat_instance=f"chat{update_id}",
            data=OrderHourCB(hour=hour).pack(),
            message=Message(
                message_id=update_id,
                date=datetime.now(tz=UTC),
                chat=Chat(id=user_id, type="private"),
                from_user=User(id=1, is_bot=True, first_name="bot"),
                text="hours",
            ),
        ),
    )


async def test_resuming_goes_straight_back_to_the_confirmation(committed: dict) -> None:
    """The promise the redirect makes: the customer re-picks a day and an hour
    and lands back on the confirmation screen.

    Without this the redirect would be a refusal wearing a friendly message --
    they would be asked for the address, the landmark, the recipient and the
    phone all over again.
    """
    settings, shop, product = committed["settings"], committed["shop"], committed["product"]
    engine, bot, recorder, dispatcher, context = await _armed_dispatcher(
        settings, shop, 880_000, day=DELIVERY
    )
    try:
        await context.update_data(
            product_id=product,
            product_name="Oq atirgul",
            price_uzs=450_000,
            telegram_file_id="f",
            resume_at_confirm=True,
        )
        await context.set_state(PlaceOrder.choosing_hour)
        await dispatcher.feed_update(bot, hour_tap(user_id=880_000, hour=15, update_id=11))
        state = await context.get_state()
        data = await context.get_data()
    finally:
        await engine.dispose()

    assert state == PlaceOrder.confirming.state, f"did not resume to confirmation: {state}"
    assert not any(CATALOG["order.choose_location"]["uz"] in x for x in recorder.sent_texts), (
        "the customer was asked for the address again"
    )
    assert data["resume_at_confirm"] is False, "the flag was not cleared after use"
    assert data["delivery_hour"] == 15, "the newly chosen hour was not kept"


async def test_the_resume_flag_cannot_leak_into_the_next_order(committed: dict) -> None:
    """An abandoned bounced order must not make the NEXT order skip questions.

    TWO THINGS KEEP THIS TRUE, and the first is the load-bearing one:

      * `start_order` is registered `StateFilter(None, Browse.viewing)`, and the
        only route to a stateless customer is `state.clear()`, which wipes FSM
        DATA as well as the state. There is no `set_state(None)` anywhere in the
        routers -- asserted below, because adding one later would silently
        reopen this.
      * `start_order` also resets the flag explicitly. Belt and braces, not the
        guarantee.
    """
    settings, shop, product = committed["settings"], committed["shop"], committed["product"]
    engine, bot, recorder, dispatcher, context = await _armed_dispatcher(
        settings, shop, 880_000, day=DELIVERY
    )
    try:
        await context.update_data(resume_at_confirm=True)

        # Abandoning is what a customer actually does: Cancel, which clears.
        await context.clear()
        assert await context.get_data() == {}, "clear() left FSM data behind"

        await dispatcher.feed_update(
            bot,
            Update(
                update_id=12,
                callback_query=CallbackQuery(
                    id="cb12",
                    from_user=User(id=880_000, is_bot=False, first_name="Mijoz"),
                    chat_instance="chat12",
                    data=OrderStartCB(product_id=product).pack(),
                    message=Message(
                        message_id=12,
                        date=datetime.now(tz=UTC),
                        chat=Chat(id=880_000, type="private"),
                        from_user=User(id=1, is_bot=True, first_name="bot"),
                        text="card",
                    ),
                ),
            ),
        )
        assert (await context.get_data()).get("resume_at_confirm") is False

        # A real date, as the flow would have stored one: `pick_hour` now refuses
        # an hour with no date behind it, which is the crafted-callback fix.
        await context.update_data(delivery_date=DELIVERY.isoformat())
        await context.set_state(PlaceOrder.choosing_hour)
        recorder.calls.clear()
        await dispatcher.feed_update(bot, hour_tap(user_id=880_000, hour=15, update_id=13))
        state = await context.get_state()
    finally:
        await engine.dispose()

    assert state == PlaceOrder.choosing_location.state, (
        f"a fresh order skipped the location question: {state}"
    )
    assert any(CATALOG["order.choose_location"]["uz"] in x for x in recorder.sent_texts)


def test_nothing_clears_the_state_without_clearing_the_data() -> None:
    """The load-bearing half of the test above, as its own claim.

    `start_order` is reachable only from no-state or Browse.viewing, and the
    only door to no-state is `state.clear()`, which wipes FSM data too. A
    `set_state(None)` added later would leave the data -- and `resume_at_confirm`
    with it -- which is how a fresh order would silently skip the location
    question carrying the previous order's address.
    """
    routers = REPO_ROOT / "src/gulbot/bot/routers"
    offenders = sorted(
        f.name for f in routers.rglob("*.py") if "set_state(None)" in f.read_text(encoding="utf-8")
    )
    assert offenders == [], (
        f"{offenders} clear the state without clearing data, which would let "
        "resume_at_confirm survive into an unrelated order"
    )
