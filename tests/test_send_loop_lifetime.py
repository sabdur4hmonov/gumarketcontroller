"""CP6's send path, audited for the defect CP8's debouncer actually had.

THE DEFECT, RESTATED. An `aiohttp.ClientSession` -- like a `redis.asyncio`
connection -- is bound to the event loop that opened it. Celery wraps every task
in `asyncio.run()`, which creates a loop and then CLOSES it. Any I/O client
cached beyond one task therefore hands the NEXT task a dead socket, and it fails
with `RuntimeError: Event loop is closed`. It fails on the SECOND task, never the
first, which is why a green suite can miss it entirely: every other test in this
repo runs inside one pytest event loop.

THE AUDIT RESULT: the send path does NOT have it. Structurally it cannot,
for three reasons that these tests pin down so they stay true:

  * `build_bot()` constructs a new `Bot` on every call. No `@lru_cache`, no
    module-level singleton. A new Bot means a new `AiohttpSession`, which means
    a new `ClientSession` opened inside whichever loop is running.
  * `TelegramTransport` holds its bot as an INSTANCE attribute, and is itself
    constructed inside `_send_due_reminders`, i.e. inside the task's own loop.
  * `_send_due_reminders` closes the session in a `finally`, so the client does
    not merely go unused after the loop dies -- it is released before it.

WHY THE TESTS STILL EXIST. "Structurally it cannot happen" is exactly what
anyone would have said about the debouncer's cached Redis client. These are the
guard against someone later "optimising" `build_bot` into a module-level cache,
which would look like a sensible saving and would break the second tick of every
worker process.

THE GAP THIS CLOSES IN CP6'S OWN EVIDENCE. CP6's live proof ran a second tick
and showed zero real API calls -- that tested IDEMPOTENCY, not client lifetime.
Two ticks that each really send, in one process, was never proven until now.

NO NETWORK, NO REAL TOKEN. The bot is pointed at `tests/telegram_stub.py`, a
real HTTP server on localhost, and built with `bot_harness.TEST_TOKEN`. The
request is a genuine aiohttp round trip -- which is the whole point, since a
mocked session would replace the very connector whose loop binding is at issue.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from aiogram.client.telegram import TelegramAPIServer
from tests.bot_harness import TEST_TOKEN
from tests.telegram_stub import FakeTelegram

import gulbot.bot.factory as factory_module
import gulbot.worker.tasks as tasks_module
from gulbot.config import Settings
from gulbot.db.session import task_session_factory
from gulbot.sending.telegram import TelegramTransport

SHOP_NAME = "loop-lifetime-probe"

#: Children first. `orders.customer_id` is ON DELETE RESTRICT, so an order left
#: behind blocks the whole teardown -- which is how CP10b's test found that this
#: list predated the orders table.
_PURGE_ORDER = (
    "order_reminders",
    "orders",
    "message_log",
    "scheduled_notifications",
    "consent_events",
    "occasions",
    "recipients",
    "customers",
)


@pytest.fixture
def fake_telegram() -> Iterator[FakeTelegram]:
    with FakeTelegram() as api:
        yield api


@pytest.fixture
def production_bot_at_the_stub(
    fake_telegram: FakeTelegram, monkeypatch: pytest.MonkeyPatch
) -> Iterator[FakeTelegram]:
    """`build_bot()` runs FOR REAL; only its destination and token change.

    This matters. Replacing `build_bot` with a hand-rolled Bot would test a
    Bot the production code never builds, and would keep passing if somebody
    cached the real one. The wrapper calls the real factory on every call, so a
    cached factory returns the same dead-session Bot twice and the tests below
    fail exactly as production would.
    """
    local_api = TelegramAPIServer.from_base(fake_telegram.base_url)
    real_build_bot = factory_module.build_bot

    monkeypatch.setattr(factory_module, "get_settings", lambda: Settings(bot_token=TEST_TOKEN))

    def build_bot_at_the_stub():  # type: ignore[no-untyped-def]
        bot = real_build_bot()
        bot.session.api = local_api
        return bot

    monkeypatch.setattr(factory_module, "build_bot", build_bot_at_the_stub)
    yield fake_telegram


# --- 1. the transport, twice, in two loops ---------------------------------


def test_the_transport_survives_a_fresh_event_loop_per_call(
    production_bot_at_the_stub: FakeTelegram,
) -> None:
    """NOT an async test, deliberately -- that is the entire point.

    pytest-asyncio would run both sends inside ONE loop and the defect would be
    invisible. `asyncio.run` twice is the worker's actual shape.

    AND IT DOES NOT CLOSE THE SESSION, also deliberately. The send path has TWO
    independent protections, and closing here would mask the one under test:

      1. `build_bot()` is not cached, so every tick gets a new AiohttpSession;
      2. `_send_due_reminders` closes the session in a `finally`, and aiogram's
         `create_session()` rebuilds a closed one -- so even a CACHED Bot would
         survive.

    Either alone is sufficient, which means a test that does both cannot tell
    you which one is holding; the first mutation run proved that by leaving this
    test green with `build_bot` cached. Leaving the session open isolates
    protection 1: if `build_bot` is ever cached, the second loop inherits a LIVE
    ClientSession belonging to the first, now-dead loop, and raises.
    """
    api = production_bot_at_the_stub
    built = []

    async def one_task() -> object:
        bot = factory_module.build_bot()
        built.append(bot)
        # No close, on purpose. See the docstring.
        return await TelegramTransport(bot).send_text(chat_id=555, text="salom")

    first = asyncio.run(one_task())
    # The call that would raise RuntimeError: Event loop is closed.
    second = asyncio.run(one_task())

    assert first.ok is True  # type: ignore[attr-defined]
    assert second.ok is True  # type: ignore[attr-defined]
    assert built[0] is not built[1], "build_bot handed out the same Bot twice"
    assert api.calls == ["sendMessage", "sendMessage"], (
        "both loops must have made a REAL API call; a skipped send proves nothing"
    )


def test_the_tick_closes_the_session_it_opened(
    production_bot_at_the_stub: FakeTelegram,
) -> None:
    """Protection 2, pinned on its own.

    `_send_due_reminders` closes the bot session in a `finally`. That is what
    would make even a cached Bot survive, and it is the difference between this
    path and the debouncer's, which cached a client AND never closed it.
    """
    api = production_bot_at_the_stub
    built = []

    async def one_task() -> None:
        bot = factory_module.build_bot()
        built.append(bot)
        try:
            await TelegramTransport(bot).send_text(chat_id=555, text="salom")
        finally:
            await bot.session.close()

    asyncio.run(one_task())

    assert api.calls == ["sendMessage"]
    underlying = built[0].session._session
    assert underlying is not None and underlying.closed, (
        "the aiohttp session outlived its task; that is how the debouncer bug happened"
    )


# --- 2. the whole tick, twice, each really sending -------------------------


@pytest.fixture
def committed_world(settings) -> Iterator[dict]:  # type: ignore[no-untyped-def]
    """Committed, because `_send_due_reminders` opens its own connection."""
    dsn = (
        f"host={settings.postgres_host} port={settings.postgres_port} "
        f"user={settings.postgres_user} password={settings.postgres_password.get_secret_value()} "
        f"dbname={settings.postgres_test_db}"
    )

    def purge(conn: psycopg.Connection) -> None:
        shops = [
            row[0]
            for row in conn.execute("SELECT id FROM shops WHERE name = %s", (SHOP_NAME,)).fetchall()
        ]
        if not shops:
            return
        for table in _PURGE_ORDER:
            conn.execute(f"DELETE FROM {table} WHERE shop_id = ANY(%s)", (shops,))
        conn.execute("DELETE FROM shops WHERE id = ANY(%s)", (shops,))

    with psycopg.connect(dsn, autocommit=True) as conn:
        purge(conn)
        shop = conn.execute(
            "INSERT INTO shops (name, working_hours) VALUES (%s, '{}'::jsonb) RETURNING id",
            (SHOP_NAME,),
        ).fetchone()[0]
        customer = conn.execute(
            "INSERT INTO customers (shop_id, telegram_user_id) VALUES (%s, 880011) RETURNING id",
            (shop,),
        ).fetchone()[0]
        recipient = conn.execute(
            "INSERT INTO recipients (shop_id, customer_id, label, type) "
            "VALUES (%s, %s, 'Onam', 'mother') RETURNING id",
            (shop, customer),
        ).fetchone()[0]
        try:
            yield {"conn": conn, "shop": shop, "customer": customer, "recipient": recipient}
        finally:
            purge(conn)


def add_due_row(world: dict, *, day: int) -> None:
    conn = world["conn"]
    occasion = conn.execute(
        "INSERT INTO occasions "
        "(shop_id, customer_id, recipient_id, label, type, kind, month, day) "
        "VALUES (%s, %s, %s, 'Onam', 'mother', 'birthday', 3, %s) RETURNING id",
        (world["shop"], world["customer"], world["recipient"], day),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO scheduled_notifications "
        "(shop_id, customer_id, occasion_id, occurrence_year, offset_days, due_at_utc, "
        " channel, merge_key) "
        "VALUES (%s, %s, %s, 2027, %s, %s, 'telegram', %s)",
        (
            world["shop"],
            world["customer"],
            occasion,
            -day,
            datetime.now(UTC) - timedelta(minutes=1),
            f"loop-probe-{day}",
        ),
    )


@pytest.mark.infra
def test_two_ticks_in_one_process_both_really_send(
    production_bot_at_the_stub: FakeTelegram,
    committed_world: dict,
    settings,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE gap in CP6's live evidence, closed.

    The live second-tick proof showed zero real API calls, which demonstrated
    idempotency and nothing about client lifetime. Here a second due row is
    added BETWEEN the ticks so the second tick has real work, and both ticks
    make a real HTTP request -- in two separate event loops, in one process.

    Only two things are patched: where the database is (the test DB, not the
    dev one) and where Telegram is (the localhost stub). Everything else is the
    production function.
    """
    api = production_bot_at_the_stub

    # The REAL production context manager, pointed at the test database. Using
    # it rather than a hand-rolled factory keeps engine DISPOSAL under test too:
    # if the task ever went back to a non-disposing factory, this patch would
    # never be called and `engines` below would be empty.
    engines: list[tuple[object, object]] = []

    @asynccontextmanager
    async def test_session_factory(*_a: object, **_k: object):  # type: ignore[no-untyped-def]
        async with task_session_factory(settings.postgres_test_db) as factory:
            engine = factory.kw["bind"]
            engines.append((engine, engine.pool))
            yield factory

    monkeypatch.setattr(tasks_module, "task_session_factory", test_session_factory)

    add_due_row(committed_world, day=8)
    first = asyncio.run(tasks_module._send_due_reminders())

    add_due_row(committed_world, day=9)
    # The tick that would raise RuntimeError: Event loop is closed.
    second = asyncio.run(tasks_module._send_due_reminders())

    assert first == {"groups": 1, "sent": 1}
    assert second == {"groups": 1, "sent": 1}, "the second tick must really send, not skip"
    assert api.calls == ["sendMessage", "sendMessage"]

    assert len(engines) == 2, "each tick must build its own engine"
    for engine, pool_before in engines:
        assert engine.pool is not pool_before, "the tick leaked its connection pool"

    states = (
        committed_world["conn"]
        .execute(
            "SELECT state, count(*) FROM scheduled_notifications WHERE shop_id = %s GROUP BY state",
            (committed_world["shop"],),
        )
        .fetchall()
    )
    assert states == [("sent", 2)]


# --- 3. the structural properties the two tests above depend on ------------


def test_build_bot_is_not_cached() -> None:
    """Fails fast, with a readable message, if someone adds an lru_cache.

    The tests above would also fail, but with `RuntimeError: Event loop is
    closed` from deep inside aiohttp -- true, and much harder to act on.
    """
    first, second = factory_module.build_bot(), factory_module.build_bot()
    try:
        assert first is not second, "build_bot is cached; the second Celery task will die"
        assert first.session is not second.session, "the aiohttp session is shared across loops"
    finally:
        # Never awaited a request, so nothing to close but the objects.
        del first, second


def test_the_session_factory_is_not_cached_either() -> None:
    """Same defect, database side.

    asyncpg's pool is loop-bound too. The send path is safe only because
    `build_session_factory()` builds a NEW engine per call; a module-level
    engine would fail on the second task in exactly the same way.
    """
    from gulbot.db.session import build_session_factory

    first, second = build_session_factory(), build_session_factory()
    assert first.kw["bind"] is not second.kw["bind"], (
        "the engine is shared between calls; its pool is bound to the first loop"
    )


# --- 4. CP10b's task, the same audit -----------------------------------------


def add_due_ping(world: dict, *, token: str, number: int = 0) -> int:
    """A committed order with one due ping, ready for the shop-facing tick."""
    conn = world["conn"]
    order = conn.execute(
        "INSERT INTO orders (shop_id, customer_id, product_name_snapshot, "
        " price_uzs_snapshot, telegram_file_id_snapshot, delivery_date, delivery_hour, "
        " delivery_location_text, landmark, status, submit_token) "
        "VALUES (%s, %s, 'Buket', 100000, 'file-x', '2027-03-08', '14:00', 'Chilonzor', "
        " 'eshik', 'placed', %s) RETURNING id",
        (world["shop"], world["customer"], token),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO order_reminders (shop_id, order_id, ping_number, due_at_utc) "
        "VALUES (%s, %s, %s, now())",
        (world["shop"], order, number),
    )
    return int(order)


@pytest.mark.infra
def test_two_order_ping_ticks_in_one_process_both_really_send(
    production_bot_at_the_stub: FakeTelegram,
    committed_world: dict,
    settings,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CP10b's task, audited for the defect CP8's debouncer actually had.

    A new Celery task is a new chance to cache a client at module level, and the
    failure would appear only on the SECOND tick of a worker -- never in a test
    that runs everything inside one pytest event loop. So this runs the real
    task twice through `asyncio.run`, exactly as Celery does, with a real
    aiohttp round trip to a localhost stub on each.

    A second due ping is added BETWEEN the ticks so the second tick has genuine
    work: two ticks where the second sends nothing would demonstrate idempotency
    and say nothing at all about client lifetime.
    """
    api = production_bot_at_the_stub
    committed_world["conn"].execute(
        "UPDATE shops SET group_chat_id = -1007777 WHERE id = %s", (committed_world["shop"],)
    )

    engines: list[tuple[object, object]] = []

    @asynccontextmanager
    async def test_session_factory(*_a: object, **_k: object):  # type: ignore[no-untyped-def]
        async with task_session_factory(settings.postgres_test_db) as factory:
            engine = factory.kw["bind"]
            engines.append((engine, engine.pool))
            yield factory

    monkeypatch.setattr(tasks_module, "task_session_factory", test_session_factory)

    add_due_ping(committed_world, token="lifetime-1", number=0)
    first = asyncio.run(tasks_module._send_order_pings())

    add_due_ping(committed_world, token="lifetime-2", number=0)
    # The tick that would raise RuntimeError: Event loop is closed.
    second = asyncio.run(tasks_module._send_order_pings())

    assert first == {"claimed": 1, "sent": 1}
    assert second == {"claimed": 1, "sent": 1}, "the second tick must really send, not skip"
    assert api.calls == ["sendPhoto", "sendPhoto"]

    assert len(engines) == 2, "each tick must build its own engine"
    for engine, pool_before in engines:
        assert engine.pool is not pool_before, "the tick leaked its connection pool"

    states = (
        committed_world["conn"]
        .execute(
            "SELECT state, count(*) FROM order_reminders WHERE shop_id = %s GROUP BY state",
            (committed_world["shop"],),
        )
        .fetchall()
    )
    assert states == [("sent", 2)]


# --- 5. CP11.5's health tasks, the same audit -------------------------------


@pytest.mark.infra
def test_two_health_checks_in_one_process_both_really_send(
    production_bot_at_the_stub: FakeTelegram,
    committed_world: dict,
    settings,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The health tasks touch THREE loop-bound clients, more than any other job
    in the project: the asyncpg pool, the aiohttp session, and -- uniquely --
    a Redis client for the alert cooldown.

    Redis is the one that actually caused the CP8 outage, so a task that opens
    one is exactly where the defect would come back. It would fail on the second
    tick and never the first, which is why this runs two.

    The daily summary is used rather than the alert check, because the summary
    sends unconditionally: an alert on a healthy shop correctly sends nothing,
    and a test where the second run does nothing proves nothing about client
    lifetime.
    """
    api = production_bot_at_the_stub
    committed_world["conn"].execute(
        "UPDATE shops SET group_chat_id = -1007777 WHERE id = %s", (committed_world["shop"],)
    )

    engines: list[tuple[object, object]] = []

    @asynccontextmanager
    async def test_session_factory(*_a: object, **_k: object):  # type: ignore[no-untyped-def]
        async with task_session_factory(settings.postgres_test_db) as factory:
            engine = factory.kw["bind"]
            engines.append((engine, engine.pool))
            yield factory

    monkeypatch.setattr(tasks_module, "task_session_factory", test_session_factory)

    first = asyncio.run(tasks_module._for_every_shop("summary"))
    # The tick that would raise RuntimeError: Event loop is closed.
    second = asyncio.run(tasks_module._for_every_shop("summary"))

    assert first["announced"] >= 1
    assert second["announced"] >= 1, "the second run must really send, not skip"
    assert api.calls == ["sendMessage", "sendMessage"]

    assert len(engines) == 2, "each run must build its own engine"
    for engine, pool_before in engines:
        assert engine.pool is not pool_before, "the run leaked its connection pool"


@pytest.mark.infra
def test_two_alert_checks_in_one_process_both_reach_redis(
    production_bot_at_the_stub: FakeTelegram,
    committed_world: dict,
    settings,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Redis half specifically, in two separate event loops.

    Nothing is due, so neither run alerts -- what is under test is that the
    SECOND run can still open a Redis client at all. A cached one would raise
    rather than return quietly.
    """
    committed_world["conn"].execute(
        "UPDATE shops SET group_chat_id = -1007777 WHERE id = %s", (committed_world["shop"],)
    )

    @asynccontextmanager
    async def test_session_factory(*_a: object, **_k: object):  # type: ignore[no-untyped-def]
        async with task_session_factory(settings.postgres_test_db) as factory:
            yield factory

    monkeypatch.setattr(tasks_module, "task_session_factory", test_session_factory)

    from gulbot.sending.health import alert_cooldown

    async def claim_twice() -> bool:
        async with alert_cooldown() as cooldown:
            return await cooldown.claim(shop_id=committed_world["shop"], kind="lifetime-probe")

    first = asyncio.run(claim_twice())
    second = asyncio.run(claim_twice())

    assert first is True, "the first claim in a fresh window must succeed"
    assert second is False, "and the second must see the key the first one wrote"
