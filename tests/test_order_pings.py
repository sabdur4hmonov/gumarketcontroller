"""The shop-facing outbox: what the group is told, and that it is told once.

Split deliberately. The wording is proven against a frozen `OrderCard` with no
database in sight, and the delivery guarantees are proven against real Postgres
rows, because "sent exactly once" is a claim about transactions and cannot be
demonstrated with a fake.

THE CLAIM IS THE POINT. `state` moves pending -> sending and COMMITS before
Telegram is called. Several tests here would pass against an implementation that
claimed after sending, or not at all, so the ones that would not are marked --
they are the reason this module exists rather than a single happy-path test.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from tests.bot_harness import bound_session_factory

from gulbot.config import Settings
from gulbot.models.order import Order, PingState
from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.sending.order_card import ANNOUNCEMENT, OrderCard, render_card
from gulbot.sending.order_pings import (
    CLAIM_TIMEOUT,
    MAX_PING_ATTEMPTS,
    claim_due_pings,
    hours_ahead,
    load_card,
    ping_targets,
    run_order_ping_tick,
)
from gulbot.sending.transport import CAPTION_LIMIT, SendResult
from gulbot.services.orders import announce_order

# --------------------------------------------------------------------------
# the card: pure, no database
# --------------------------------------------------------------------------

CARD = OrderCard(
    order_id=42,
    product_name="Oq atirgul",
    price_uzs=450000,
    telegram_file_id="file-1",
    delivery_date=date(2027, 3, 8),
    delivery_hour=time(14, 0),
    landmark="Ko'k eshik",
    customer_telegram_id=7001,
    location_text="Chilonzor 5",
    customer_phone="+998901234567",
    phone_verified=True,
)


def test_the_announcement_says_new_order() -> None:
    rendered = render_card(CARD, ping_number=ANNOUNCEMENT)
    assert "Yangi buyurtma" in rendered
    assert "#42" in rendered


def test_a_delivery_ping_says_how_many_hours_are_left() -> None:
    rendered = render_card(CARD, ping_number=1, hours_ahead=3)
    assert "3 soat" in rendered
    assert "Yangi buyurtma" not in rendered, "a reminder is not an announcement"


def test_the_card_carries_every_field_the_courier_needs() -> None:
    rendered = render_card(CARD, ping_number=ANNOUNCEMENT)
    for fragment in ("Oq atirgul", "450 000", "8-mart", "14:00", "Chilonzor 5", "Ko'k eshik"):
        assert fragment in rendered, f"missing from the shop's card: {fragment}"


def test_an_unpriced_bouquet_says_so_rather_than_showing_nothing() -> None:
    """The wording is the reminder's, not a second copy of it. The shop and the
    customer must never disagree about what an unpriced post means."""
    rendered = render_card(CARD.__class__(**{**CARD.__dict__, "price_uzs": None}), ping_number=0)
    assert "narx operator tomonidan tasdiqlanadi" in rendered


def test_a_dropped_pin_shows_the_coordinates_and_a_link() -> None:
    """Both, on purpose. A courier without data, or with a maps app that is not
    Google's, still has numbers to type in."""
    pinned = OrderCard(
        **{
            **CARD.__dict__,
            "location_text": None,
            "location_lat": 41.311081,
            "location_lon": 69.240562,
        }
    )
    rendered = render_card(pinned, ping_number=ANNOUNCEMENT)
    assert "41.311081" in rendered
    assert "69.240562" in rendered
    assert "maps.google.com" in rendered


def test_a_verified_number_is_shown_plainly() -> None:
    assert "tasdiqlanmagan" not in render_card(CARD, ping_number=ANNOUNCEMENT)
    assert "+998901234567" in render_card(CARD, ping_number=ANNOUNCEMENT)


def test_an_unverified_number_is_shown_and_marked() -> None:
    """SHOWN, not withheld. The courier still needs something to dial, and
    typing the number by hand is a choice the customer is allowed to make."""
    rendered = render_card(
        OrderCard(**{**CARD.__dict__, "phone_verified": False}), ping_number=ANNOUNCEMENT
    )
    assert "+998901234567" in rendered
    assert "tasdiqlanmagan" in rendered


def test_a_missing_number_says_so_rather_than_leaving_a_gap() -> None:
    rendered = render_card(
        OrderCard(**{**CARD.__dict__, "customer_phone": None}), ping_number=ANNOUNCEMENT
    )
    assert "telefon raqami yo" in rendered


def test_the_card_links_to_the_customer_chat() -> None:
    assert "tg://user?id=7001" in render_card(CARD, ping_number=ANNOUNCEMENT)


def test_a_hostile_product_name_cannot_inject_markup() -> None:
    """The name comes from a shop's channel caption -- arbitrary text -- and the
    bot sends with parse_mode=HTML. Same hazard CP9 closed for the caption."""
    hostile = OrderCard(**{**CARD.__dict__, "product_name": "<b>x</b> & <a href='#'>y</a>"})
    rendered = render_card(hostile, ping_number=ANNOUNCEMENT)
    assert "&lt;b&gt;x&lt;/b&gt;" in rendered
    assert "<a href='#'>" not in rendered


def test_a_hostile_landmark_cannot_inject_markup() -> None:
    """The landmark is free text the CUSTOMER typed, which makes it the more
    dangerous of the two."""
    hostile = OrderCard(**{**CARD.__dict__, "landmark": "<i>metro</i>"})
    assert "&lt;i&gt;metro&lt;/i&gt;" in render_card(hostile, ping_number=ANNOUNCEMENT)


def test_hours_ahead_is_read_from_the_ping_not_the_clock() -> None:
    """A tick that runs late must still say the number the ping was created to
    say. Deriving it from `now` would quietly rewrite it."""
    delivery = datetime(2027, 3, 8, 14, 0, tzinfo=UTC) - timedelta(hours=5)
    assert hours_ahead(CARD, delivery - timedelta(hours=3)) == 3
    assert hours_ahead(CARD, delivery - timedelta(hours=1)) == 1


# --------------------------------------------------------------------------
# delivery, against real rows
# --------------------------------------------------------------------------


class FakeTransport:
    """Records calls. `results` is consumed one per call; the default is success."""

    def __init__(self, results: list[SendResult] | None = None) -> None:
        self.photos: list[dict] = []
        self.texts: list[dict] = []
        self._results = list(results or [])

    def _next(self) -> SendResult:
        return self._results.pop(0) if self._results else SendResult.sent(1)

    async def send_text(self, *, chat_id: int, text: str) -> SendResult:
        self.texts.append({"chat_id": chat_id, "text": text})
        return self._next()

    async def send_photo(self, *, chat_id: int, file_id: str, caption: str, **kw: object):  # type: ignore[no-untyped-def]
        self.photos.append({"chat_id": chat_id, "file_id": file_id, "caption": caption})
        return self._next()

    @property
    def calls(self) -> int:
        return len(self.photos) + len(self.texts)


async def _make_order(
    db: AsyncConnection,
    shop: int,
    customer: int,
    *,
    token: str = "t1",
    name: str = "Oq atirgul",
    delivery: date = date(2027, 3, 8),
) -> int:
    return int(
        (
            await db.execute(
                text(
                    "INSERT INTO orders (shop_id, customer_id, product_name_snapshot, "
                    " price_uzs_snapshot, telegram_file_id_snapshot, delivery_date, "
                    " delivery_hour, delivery_location_text, landmark, status, submit_token) "
                    "VALUES (:s, :c, :n, 450000, 'file-snap', :d, '14:00', 'Chilonzor 5', "
                    " 'Ko''k eshik', 'placed', :tok) RETURNING id"
                ),
                {"s": shop, "c": customer, "n": name, "d": delivery, "tok": token},
            )
        ).scalar_one()
    )


@pytest_asyncio.fixture
async def world(db: AsyncConnection) -> dict:
    shop = (
        await db.execute(
            text(
                "INSERT INTO shops (name, working_hours, group_chat_id, owner_telegram_ids) "
                "VALUES ('S', CAST(:wh AS jsonb), -1001234, '{555,556}') RETURNING id"
            ),
            {"wh": json.dumps(DEFAULT_WORKING_HOURS)},
        )
    ).scalar_one()
    customer = (
        await db.execute(
            text(
                "INSERT INTO customers (shop_id, telegram_user_id, phone, phone_verified) "
                "VALUES (:s, 7001, '+998901234567', true) RETURNING id"
            ),
            {"s": shop},
        )
    ).scalar_one()
    order = await _make_order(db, shop, customer)
    return {"db": db, "shop": shop, "customer": customer, "order": order}


async def _ping(
    db: AsyncConnection,
    shop: int,
    order: int,
    *,
    number: int = ANNOUNCEMENT,
    due: datetime | None = None,
    state: str = "pending",
    attempts: int = 0,
    claimed_at: datetime | None = None,
) -> int:
    return int(
        (
            await db.execute(
                text(
                    "INSERT INTO order_reminders (shop_id, order_id, ping_number, due_at_utc, "
                    " state, attempts, claimed_at) "
                    "VALUES (:s, :o, :n, :d, :st, :a, :c) RETURNING id"
                ),
                {
                    "s": shop,
                    "o": order,
                    "n": number,
                    # A SECOND IN THE PAST, not `now`. A test that captures
                    # `now` and then inserts gets a due time strictly later than
                    # it, so `due_at_utc <= now_utc` is false and the row is not
                    # due at all -- the claim logic under test never runs. On
                    # Windows the ~15.6ms clock granularity usually makes the
                    # two reads equal, which hid this until a loaded machine
                    # stretched one full-suite run to 1818s and they straddled a
                    # tick. Reproduced deterministically with a 50ms sleep.
                    "d": due if due is not None else datetime.now(UTC) - timedelta(seconds=1),
                    "st": state,
                    "a": attempts,
                    "c": claimed_at,
                },
            )
        ).scalar_one()
    )


async def _state(db: AsyncConnection, ping_id: int) -> tuple[str, int, datetime | None]:
    row = (
        await db.execute(
            text("SELECT state, attempts, sent_at FROM order_reminders WHERE id = :i"),
            {"i": ping_id},
        )
    ).one()
    return row.state, row.attempts, row.sent_at


# --- routing ---------------------------------------------------------------


@pytest.mark.infra
async def test_the_group_is_where_pings_go(world: dict) -> None:
    async with bound_session_factory(world["db"])() as session:
        assert await ping_targets(session, shop_id=world["shop"]) == [-1001234]


@pytest.mark.infra
async def test_without_a_group_every_owner_is_told(world: dict) -> None:
    """The standing decision: order first, then group, then owners, then a loud
    log. This is the middle rung."""
    await world["db"].execute(
        text("UPDATE shops SET group_chat_id = NULL WHERE id = :s"), {"s": world["shop"]}
    )
    async with bound_session_factory(world["db"])() as session:
        assert await ping_targets(session, shop_id=world["shop"]) == [555, 556]


@pytest.mark.infra
async def test_a_shop_with_neither_has_nowhere_to_send(world: dict) -> None:
    await world["db"].execute(
        text("UPDATE shops SET group_chat_id = NULL, owner_telegram_ids = '{}' WHERE id = :s"),
        {"s": world["shop"]},
    )
    async with bound_session_factory(world["db"])() as session:
        assert await ping_targets(session, shop_id=world["shop"]) == []


@pytest.mark.infra
async def test_the_group_wins_even_when_owners_are_set(world: dict) -> None:
    """Guards the guard: the fallback must be a FALLBACK, not an addition. Both
    firing would mean every order is announced three times."""
    async with bound_session_factory(world["db"])() as session:
        assert await ping_targets(session, shop_id=world["shop"]) == [-1001234]


# --- the announcement row --------------------------------------------------


@pytest.mark.infra
async def test_placing_an_order_queues_the_announcement(world: dict) -> None:
    async with bound_session_factory(world["db"])() as session:
        order = await session.get(Order, world["order"])
        assert await announce_order(session, order=order) is True
        await session.commit()
    count = (
        await world["db"].execute(
            text("SELECT count(*) FROM order_reminders WHERE order_id = :o AND ping_number = 0"),
            {"o": world["order"]},
        )
    ).scalar_one()
    assert count == 1


@pytest.mark.infra
async def test_announcing_twice_queues_one_message(world: dict) -> None:
    """A retried submit, or a second call from anywhere, must not tell the shop
    about the same order twice."""
    async with bound_session_factory(world["db"])() as session:
        order = await session.get(Order, world["order"])
        assert await announce_order(session, order=order) is True
        assert await announce_order(session, order=order) is False
        await session.commit()
    count = (
        await world["db"].execute(
            text("SELECT count(*) FROM order_reminders WHERE order_id = :o"),
            {"o": world["order"]},
        )
    ).scalar_one()
    assert count == 1


# --- sending ---------------------------------------------------------------


@pytest.mark.infra
async def test_a_due_announcement_reaches_the_group(world: dict) -> None:
    ping = await _ping(world["db"], world["shop"], world["order"])
    transport = FakeTransport()
    async with bound_session_factory(world["db"])() as session:
        result = await run_order_ping_tick(session, transport=transport, now_utc=datetime.now(UTC))
    assert result.sent == 1
    assert transport.photos[0]["chat_id"] == -1001234
    assert "Yangi buyurtma" in transport.photos[0]["caption"]
    state, _attempts, sent_at = await _state(world["db"], ping)
    assert state == PingState.SENT.value
    assert sent_at is not None


@pytest.mark.infra
async def test_the_photo_is_the_snapshot_not_the_live_product(world: dict) -> None:
    """The catalogue is rebuilt continuously from an editable channel. The shop
    must be shown what the customer agreed to buy."""
    await world["db"].execute(
        text("UPDATE orders SET product_name_snapshot = 'As sold' WHERE id = :o"),
        {"o": world["order"]},
    )
    await _ping(world["db"], world["shop"], world["order"])
    transport = FakeTransport()
    async with bound_session_factory(world["db"])() as session:
        await run_order_ping_tick(session, transport=transport, now_utc=datetime.now(UTC))
    assert "As sold" in transport.photos[0]["caption"]
    assert transport.photos[0]["file_id"] == "file-snap"


@pytest.mark.infra
async def test_a_ping_that_is_not_due_yet_is_left_alone(world: dict) -> None:
    await _ping(
        world["db"],
        world["shop"],
        world["order"],
        number=1,
        due=datetime.now(UTC) + timedelta(hours=2),
    )
    transport = FakeTransport()
    async with bound_session_factory(world["db"])() as session:
        result = await run_order_ping_tick(session, transport=transport, now_utc=datetime.now(UTC))
    assert result.claimed == 0
    assert transport.calls == 0


@pytest.mark.infra
async def test_a_second_tick_does_not_send_it_again(world: dict) -> None:
    """The ordinary case, and -- honestly -- NOT proof of the claim.

    A first draft claimed it was. It is not: the first tick resolves the row to
    'sent', so the second skips it for that reason alone, and this passes
    against an implementation with no claim at all. Removing the claim was the
    mutation that showed it. The claim is proven two tests below, by killing a
    worker between the claim and the resolve, which is the only situation where
    the two mechanisms differ.
    """
    await _ping(world["db"], world["shop"], world["order"])
    transport = FakeTransport()
    factory = bound_session_factory(world["db"])
    async with factory() as session:
        await run_order_ping_tick(session, transport=transport, now_utc=datetime.now(UTC))
    async with factory() as session:
        second = await run_order_ping_tick(session, transport=transport, now_utc=datetime.now(UTC))
    assert second.claimed == 0
    assert transport.calls == 1


@pytest.mark.infra
async def test_a_long_card_falls_back_to_text_rather_than_two_messages(world: dict) -> None:
    """ONE call either way. A photo followed by a text would be two, and a
    failure between them leaves a ping that is half sent."""
    await world["db"].execute(
        text("UPDATE orders SET landmark = :l WHERE id = :o"),
        {"l": "x" * 200, "o": world["order"]},
    )
    await world["db"].execute(
        text("UPDATE orders SET product_name_snapshot = :n WHERE id = :o"),
        {"n": "y" * 200, "o": world["order"]},
    )
    await _ping(world["db"], world["shop"], world["order"])
    transport = FakeTransport()
    async with bound_session_factory(world["db"])() as session:
        async with session.begin_nested():
            pass
        # Force the caption over the limit by lengthening the address too.
        await session.execute(
            text("UPDATE orders SET delivery_location_text = :a WHERE id = :o"),
            {"a": "z" * 700, "o": world["order"]},
        )
        result = await run_order_ping_tick(session, transport=transport, now_utc=datetime.now(UTC))
    assert result.sent == 1
    assert len(transport.texts) == 1, "a long card must go as text"
    assert transport.photos == []
    assert len(transport.texts[0]["text"]) > CAPTION_LIMIT


# --- failure and retry -----------------------------------------------------


@pytest.mark.infra
async def test_a_failed_send_is_retried_next_tick(world: dict) -> None:
    ping = await _ping(world["db"], world["shop"], world["order"])
    factory = bound_session_factory(world["db"])
    failing = FakeTransport([SendResult.failed("boom")])
    async with factory() as session:
        first = await run_order_ping_tick(session, transport=failing, now_utc=datetime.now(UTC))
    assert first.failed == 1
    assert (await _state(world["db"], ping))[0] == PingState.FAILED.value

    succeeding = FakeTransport()
    async with factory() as session:
        second = await run_order_ping_tick(session, transport=succeeding, now_utc=datetime.now(UTC))
    assert second.sent == 1
    assert (await _state(world["db"], ping))[0] == PingState.SENT.value


@pytest.mark.infra
async def test_an_exhausted_ping_is_parked_without_sending(world: dict) -> None:
    ping = await _ping(
        world["db"], world["shop"], world["order"], state="failed", attempts=MAX_PING_ATTEMPTS
    )
    transport = FakeTransport()
    async with bound_session_factory(world["db"])() as session:
        result = await run_order_ping_tick(session, transport=transport, now_utc=datetime.now(UTC))
    assert result.dead_lettered == 1
    assert transport.calls == 0, "a parked ping must not also be sent"
    assert (await _state(world["db"], ping))[0] == PingState.DEAD_LETTER.value


@pytest.mark.infra
async def test_a_dead_lettered_ping_is_never_picked_up_again(world: dict) -> None:
    await _ping(world["db"], world["shop"], world["order"], state="dead_letter", attempts=9)
    transport = FakeTransport()
    async with bound_session_factory(world["db"])() as session:
        result = await run_order_ping_tick(session, transport=transport, now_utc=datetime.now(UTC))
    assert result.claimed == 0
    assert transport.calls == 0


@pytest.mark.infra
async def test_an_undeliverable_ping_is_counted_and_the_order_survives(world: dict) -> None:
    """The order is written and safe; only the notification failed. Losing the
    order because nobody could be told about it would be far worse."""
    await world["db"].execute(
        text("UPDATE shops SET group_chat_id = NULL, owner_telegram_ids = '{}' WHERE id = :s"),
        {"s": world["shop"]},
    )
    ping = await _ping(world["db"], world["shop"], world["order"])
    transport = FakeTransport()
    async with bound_session_factory(world["db"])() as session:
        result = await run_order_ping_tick(session, transport=transport, now_utc=datetime.now(UTC))
    assert result.undeliverable == 1
    assert transport.calls == 0
    assert (await _state(world["db"], ping))[0] == PingState.FAILED.value
    still_there = (
        await world["db"].execute(
            text("SELECT count(*) FROM orders WHERE id = :o"), {"o": world["order"]}
        )
    ).scalar_one()
    assert still_there == 1


@pytest.mark.infra
async def test_one_owner_failing_does_not_lose_the_ping(world: dict) -> None:
    """Fan-out succeeds if ANY delivery does. One owner who blocked the bot must
    not make the whole shop's order look undelivered."""
    await world["db"].execute(
        text("UPDATE shops SET group_chat_id = NULL WHERE id = :s"), {"s": world["shop"]}
    )
    ping = await _ping(world["db"], world["shop"], world["order"])
    transport = FakeTransport([SendResult.forbidden(), SendResult.sent(9)])
    async with bound_session_factory(world["db"])() as session:
        result = await run_order_ping_tick(session, transport=transport, now_utc=datetime.now(UTC))
    assert result.sent == 1
    assert transport.calls == 2
    assert (await _state(world["db"], ping))[0] == PingState.SENT.value


@pytest.mark.infra
async def test_every_owner_failing_fails_the_ping(world: dict) -> None:
    await world["db"].execute(
        text("UPDATE shops SET group_chat_id = NULL WHERE id = :s"), {"s": world["shop"]}
    )
    ping = await _ping(world["db"], world["shop"], world["order"])
    transport = FakeTransport([SendResult.failed("a"), SendResult.failed("b")])
    async with bound_session_factory(world["db"])() as session:
        result = await run_order_ping_tick(session, transport=transport, now_utc=datetime.now(UTC))
    assert result.failed == 1
    assert (await _state(world["db"], ping))[0] == PingState.FAILED.value


# --- the claim -------------------------------------------------------------


@pytest.mark.infra
async def test_claiming_moves_the_row_to_sending(world: dict) -> None:
    """The compare-and-swap, in isolation. The tick commits this before Telegram
    is called, which is the whole reason a dead worker cannot double-send.

    The commit here is the CALLER's, exactly as in the tick -- without it the
    claim is rolled back with the session and the row is still pending, which is
    what the first version of this test accidentally proved.
    """
    ping = await _ping(world["db"], world["shop"], world["order"])
    async with bound_session_factory(world["db"])() as session:
        claimed = await claim_due_pings(session, now_utc=datetime.now(UTC))
        await session.commit()
    assert [c.id for c in claimed] == [ping]
    state, attempts, _ = await _state(world["db"], ping)
    assert state == PingState.SENDING.value
    assert attempts == 1


@pytest.mark.infra
async def test_a_worker_that_dies_after_claiming_causes_no_second_send(world: dict) -> None:
    """THE test the claim exists for, and the only one that isolates it.

    A worker claims, commits, and dies -- before Telegram, during it, or after
    it, which from the outside are indistinguishable. The message may already
    have reached the shop. A tick running a moment later must therefore NOT send
    it; it waits for the claim to go stale, by which time the answer is no
    longer in doubt.

    Every other double-send test in this module passes without a claim at all,
    because SKIP LOCKED covers two LIVE workers and the resolve covers a
    finished one. Neither covers a dead one. Proven by mutation: deleting the
    state change from `claim_due_pings` fails this and leaves those green.
    """
    now = datetime.now(UTC)
    # Explicitly due. These claim tests pass `now_utc=now` captured BEFORE the
    # insert, so the row must be due relative to THAT instant, not to the
    # insert's own clock read.
    ping = await _ping(world["db"], world["shop"], world["order"], due=now - timedelta(seconds=1))
    factory = bound_session_factory(world["db"])

    async with factory() as session:
        claimed = await claim_due_pings(session, now_utc=now)
        await session.commit()
    assert [c.id for c in claimed] == [ping], "the worker did take the row"
    # ... and here it dies, without ever resolving the row.

    transport = FakeTransport()
    async with factory() as session:
        result = await run_order_ping_tick(
            session, transport=transport, now_utc=now + timedelta(seconds=30)
        )
    assert result.claimed == 0
    assert transport.calls == 0, "the shop would have been told twice"


@pytest.mark.infra
async def test_the_claim_is_committed_before_telegram_is_called(
    committed_world: dict,
) -> None:
    """The phase boundary, observed from OUTSIDE the tick's transaction.

    The transport opens its own connection mid-send and reads the row. Seeing
    'sending' there proves the claim was committed first -- an uncommitted claim
    would be invisible to another connection, which is exactly the state that
    lets a crashed worker's retry send a duplicate.
    """
    import psycopg
    from sqlalchemy.ext.asyncio import async_sessionmaker

    settings = committed_world["settings"]
    dsn = (
        f"host={settings.postgres_host} port={settings.postgres_port} "
        f"user={settings.postgres_user} password={settings.postgres_password} "
        f"dbname={settings.postgres_test_db}"
    )
    observed: list[str] = []

    class ObservingTransport(FakeTransport):
        async def send_photo(self, **kw: object):  # type: ignore[no-untyped-def, override]
            with psycopg.connect(dsn, autocommit=True) as conn:
                observed.append(
                    conn.execute(
                        "SELECT state FROM order_reminders WHERE order_id = %s",
                        (committed_world["order"],),
                    ).fetchone()[0]
                )
            return await super().send_photo(**kw)  # type: ignore[arg-type]

    engine = create_async_engine(
        settings.database_url(database=settings.postgres_test_db), future=True
    )
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await run_order_ping_tick(
                session, transport=ObservingTransport(), now_utc=datetime.now(UTC)
            )
    finally:
        await engine.dispose()

    assert observed == [PingState.SENDING.value], (
        "another connection could not see the claim while the send was in flight"
    )


@pytest.mark.infra
async def test_a_row_already_sending_is_not_reclaimed_immediately(world: dict) -> None:
    """A worker that is merely SLOW must keep its claim. Retaking it early is
    exactly how a duplicate gets sent."""
    now = datetime.now(UTC)
    await _ping(
        world["db"],
        world["shop"],
        world["order"],
        state="sending",
        claimed_at=now,
        due=now - timedelta(seconds=1),
    )
    async with bound_session_factory(world["db"])() as session:
        assert await claim_due_pings(session, now_utc=now) == []


@pytest.mark.infra
async def test_an_abandoned_claim_is_retaken_after_the_timeout(world: dict) -> None:
    """The other half. A worker that died must not park the ping forever."""
    now = datetime.now(UTC)
    ping = await _ping(
        world["db"],
        world["shop"],
        world["order"],
        state="sending",
        claimed_at=now - CLAIM_TIMEOUT - timedelta(seconds=1),
        due=now - timedelta(seconds=1),
    )
    async with bound_session_factory(world["db"])() as session:
        claimed = await claim_due_pings(session, now_utc=now)
    assert [c.id for c in claimed] == [ping]


@pytest.mark.infra
async def test_the_timeout_boundary_is_not_off_by_one(world: dict) -> None:
    """Exactly at the timeout is still the other worker's. Only strictly older
    is abandoned."""
    now = datetime.now(UTC)
    await _ping(
        world["db"],
        world["shop"],
        world["order"],
        state="sending",
        claimed_at=now - CLAIM_TIMEOUT,
        due=now - timedelta(seconds=1),
    )
    async with bound_session_factory(world["db"])() as session:
        assert await claim_due_pings(session, now_utc=now) == []


# --- narrowing to one order ------------------------------------------------


@pytest.mark.infra
async def test_only_order_id_leaves_other_orders_alone(world: dict) -> None:
    """How the request handler delivers immediately without flushing the whole
    outbox from inside a Telegram update."""
    other = await _make_order(world["db"], world["shop"], world["customer"], token="t2")
    mine = await _ping(world["db"], world["shop"], world["order"])
    theirs = await _ping(world["db"], world["shop"], other)
    transport = FakeTransport()
    async with bound_session_factory(world["db"])() as session:
        result = await run_order_ping_tick(
            session,
            transport=transport,
            now_utc=datetime.now(UTC),
            only_order_id=world["order"],
        )
    assert result.sent == 1
    assert (await _state(world["db"], mine))[0] == PingState.SENT.value
    assert (await _state(world["db"], theirs))[0] == PingState.PENDING.value


@pytest.mark.infra
async def test_the_beat_finishes_what_the_handler_left(world: dict) -> None:
    """The immediate flush is an optimisation, not the mechanism. Whatever it
    did not send, the next beat picks up."""
    other = await _make_order(world["db"], world["shop"], world["customer"], token="t2")
    await _ping(world["db"], world["shop"], world["order"])
    theirs = await _ping(world["db"], world["shop"], other)
    transport = FakeTransport()
    factory = bound_session_factory(world["db"])
    async with factory() as session:
        await run_order_ping_tick(
            session,
            transport=transport,
            now_utc=datetime.now(UTC),
            only_order_id=world["order"],
        )
    async with factory() as session:
        rest = await run_order_ping_tick(session, transport=transport, now_utc=datetime.now(UTC))
    assert rest.sent == 1
    assert (await _state(world["db"], theirs))[0] == PingState.SENT.value


@pytest.mark.infra
async def test_the_card_is_loaded_from_the_order_and_the_customer(world: dict) -> None:
    async with bound_session_factory(world["db"])() as session:
        card = await load_card(session, order_id=world["order"])
    assert card is not None
    assert card.product_name == "Oq atirgul"
    assert card.customer_telegram_id == 7001
    assert card.customer_phone == "+998901234567"
    assert card.phone_verified is True


# --- two workers, two connections ------------------------------------------


@pytest.fixture
def committed_world(settings: Settings):  # type: ignore[no-untyped-def]
    """Committed rows, because SKIP LOCKED across connections needs them."""
    import psycopg

    dsn = (
        f"host={settings.postgres_host} port={settings.postgres_port} "
        f"user={settings.postgres_user} password={settings.postgres_password} "
        f"dbname={settings.postgres_test_db}"
    )
    with psycopg.connect(dsn, autocommit=True) as conn:
        for statement in (
            "DELETE FROM order_reminders WHERE shop_id IN "
            "(SELECT id FROM shops WHERE name = 'ping-race')",
            "DELETE FROM orders WHERE shop_id IN (SELECT id FROM shops WHERE name = 'ping-race')",
            "DELETE FROM customers WHERE shop_id IN "
            "(SELECT id FROM shops WHERE name = 'ping-race')",
            "DELETE FROM shops WHERE name = 'ping-race'",
        ):
            conn.execute(statement)
        shop = conn.execute(
            "INSERT INTO shops (name, working_hours, group_chat_id) "
            "VALUES ('ping-race', %s, -1009999) RETURNING id",
            (json.dumps(DEFAULT_WORKING_HOURS),),
        ).fetchone()[0]
        customer = conn.execute(
            "INSERT INTO customers (shop_id, telegram_user_id) VALUES (%s, 7788) RETURNING id",
            (shop,),
        ).fetchone()[0]
        order = conn.execute(
            "INSERT INTO orders (shop_id, customer_id, product_name_snapshot, "
            " price_uzs_snapshot, telegram_file_id_snapshot, delivery_date, delivery_hour, "
            " delivery_location_text, landmark, status, submit_token) "
            "VALUES (%s, %s, 'Buket', 100000, 'f', '2027-03-08', '14:00', 'Chilonzor', "
            " 'eshik', 'placed', 'race-tok') RETURNING id",
            (shop, customer),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO order_reminders (shop_id, order_id, ping_number, due_at_utc) "
            "VALUES (%s, %s, 0, now())",
            (shop, order),
        )
        try:
            yield {"conn": conn, "shop": shop, "order": order, "settings": settings}
        finally:
            conn.execute("DELETE FROM order_reminders WHERE shop_id = %s", (shop,))
            conn.execute("DELETE FROM orders WHERE shop_id = %s", (shop,))
            conn.execute("DELETE FROM customers WHERE shop_id = %s", (shop,))
            conn.execute("DELETE FROM shops WHERE id = %s", (shop,))


@pytest.mark.infra
async def test_two_workers_send_one_message(committed_world: dict) -> None:
    """CONCURRENT, on separate connections. A sequential pair would pass against
    an implementation with no claim at all, which is what this rules out.
    """
    import asyncio

    settings = committed_world["settings"]
    transports = [FakeTransport(), FakeTransport()]

    async def worker(transport: FakeTransport) -> int:
        engine = create_async_engine(
            settings.database_url(database=settings.postgres_test_db), future=True
        )
        try:
            from sqlalchemy.ext.asyncio import async_sessionmaker

            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                result = await run_order_ping_tick(
                    session, transport=transport, now_utc=datetime.now(UTC)
                )
                return result.sent
        finally:
            await engine.dispose()

    sent = await asyncio.gather(*(worker(t) for t in transports))
    assert sum(sent) == 1, f"the ping was sent {sum(sent)} times"
    assert sum(t.calls for t in transports) == 1

    state = (
        committed_world["conn"]
        .execute(
            "SELECT state FROM order_reminders WHERE order_id = %s",
            (committed_world["order"],),
        )
        .fetchone()[0]
    )
    assert state == PingState.SENT.value
