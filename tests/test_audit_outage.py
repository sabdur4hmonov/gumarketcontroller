# ruff: noqa: F811, F401  -- fixtures are imported by name; pytest injects them into
# the same-named test parameters, which ruff reads as a redefinition.
"""PASS 5: what a Telegram OUTAGE does to a tick -- and the circuit breaker.

THE FINDING. In a real outage nothing answers, so every send waits out the
request timeout and then raises TelegramNetworkError. The tick handled each one
-- no crash, nothing lost -- but it attempted EVERY claimed row, one after
another. At aiogram's default 60 s and BATCH_SIZE 100 that was up to 100 minutes
for one tick, on a worker that runs one task at a time.

THE FIX. The request timeout is 15 s (bot/factory.py), and a tick stops after
BREAKER_THRESHOLD consecutive network failures, handing everything it claimed
but never attempted back exactly as it was (sending/transport.py).

HOW THE OUTAGE IS SIMULATED. Not with a fake transport that returns a canned
failure -- that would test the breaker's arithmetic against a flag the test set
itself. The bot is the REAL production Bot from `build_bot()`, the transport is
the REAL `TelegramTransport`, and the Bot API it talks to is a real TCP listener
on localhost that accepts every connection, reads the request, and never
answers. The timeout that fires is aiohttp's, the exception is aiogram's, the
classification is ours. Only the timeout's LENGTH is shortened, so the suite
does not wait 15 s per send; one test below does wait the real 15 s once.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import TracebackType

import pytest
from aiogram import Bot
from aiogram.client.telegram import TelegramAPIServer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker
from tests.bot_harness import TEST_TOKEN, bound_session_factory
from tests.telegram_stub import FakeTelegram
from tests.test_dispatcher import NOW, FakeTransport, add_due_row, sessions, tick
from tests.test_dispatcher import world as reminder_world
from tests.test_order_pings import _make_order, _ping
from tests.test_order_pings import world as ping_world

import gulbot.bot.factory as factory_module
from gulbot.bot.factory import TELEGRAM_REQUEST_TIMEOUT
from gulbot.config import Settings
from gulbot.sending.order_card import ANNOUNCEMENT
from gulbot.sending.order_pings import run_order_ping_tick
from gulbot.sending.telegram import TelegramTransport
from gulbot.sending.transport import BREAKER_THRESHOLD, CircuitBreaker, SendResult

pytestmark = pytest.mark.infra

#: Stands in for the 15 s production timeout everywhere except the one test that
#: measures the real value.
OUTAGE_TIMEOUT = 0.3

#: More due work than the breaker lets through, so a missing breaker is visible.
DUE = 6


class Blackhole:
    """Telegram in an outage: the TCP connection opens, nothing ever answers.

    Connections are accepted on a thread and held open without a byte written
    back. Each accepted connection is one request put on the wire -- aiohttp
    cannot reuse a connection whose response never arrived.
    """

    def __init__(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(128)
        self._sock.settimeout(0.05)
        self._held: list[socket.socket] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    @property
    def requests(self) -> int:
        return len(self._held)

    @property
    def base_url(self) -> str:
        host, port = self._sock.getsockname()
        return f"http://{host}:{port}"

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except OSError:
                continue
            self._held.append(conn)

    def __enter__(self) -> Blackhole:
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        for conn in self._held:
            conn.close()
        self._sock.close()


class _BadRequestHandler(BaseHTTPRequestHandler):
    """Telegram UP and refusing: a 400, the way it reports a bad chat id."""

    def _respond(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        body = json.dumps(
            {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}
        ).encode()
        self.send_response(400)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_POST = _respond

    def log_message(self, format: str, *args: object) -> None:
        return None


class CountingTransport:
    """Counts what reaches the REAL transport. Delegates everything; decides nothing."""

    def __init__(self, inner: TelegramTransport) -> None:
        self.inner = inner
        self.outcomes: list[SendResult] = []

    async def send_text(self, **kw: object) -> SendResult:
        outcome = await self.inner.send_text(**kw)  # type: ignore[arg-type]
        self.outcomes.append(outcome)
        return outcome

    async def send_photo(self, **kw: object) -> SendResult:
        outcome = await self.inner.send_photo(**kw)  # type: ignore[arg-type]
        self.outcomes.append(outcome)
        return outcome


@pytest.fixture
def production_bot(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """`build_bot()` for real, with the test token and a chosen destination."""
    monkeypatch.setattr(factory_module, "get_settings", lambda: Settings(bot_token=TEST_TOKEN))

    def at(base_url: str, *, timeout: float | None = OUTAGE_TIMEOUT) -> Bot:
        bot = factory_module.build_bot()
        bot.session.api = TelegramAPIServer.from_base(base_url)
        if timeout is not None:
            bot.session.timeout = timeout
        return bot

    return at


@pytest.fixture
def blackhole() -> Iterator[Blackhole]:
    with Blackhole() as hole:
        yield hole


# --------------------------------------------------------------------------
# the transport tells "nothing answered" from "Telegram said no"
# --------------------------------------------------------------------------


async def test_a_request_nobody_answers_is_reported_as_unreachable(
    production_bot, blackhole: Blackhole
) -> None:
    bot = production_bot(blackhole.base_url)
    try:
        outcome = await TelegramTransport(bot).send_text(chat_id=1, text="x")
    finally:
        await bot.session.close()
    assert (outcome.ok, outcome.network, outcome.error_code) == (
        False,
        True,
        "TelegramNetworkError",
    )


async def test_a_refused_connection_is_reported_as_unreachable(production_bot) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    # Nothing listens on `port` now.
    bot = production_bot(f"http://127.0.0.1:{port}")
    try:
        outcome = await TelegramTransport(bot).send_text(chat_id=1, text="x")
    finally:
        await bot.session.close()
    assert outcome.network is True


async def test_telegram_answering_with_an_error_is_not_a_network_failure(production_bot) -> None:
    """A 400 proves Telegram is up. It must not count toward the breaker."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _BadRequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[0], server.server_address[1]
    bot = production_bot(f"http://{host}:{port}")
    try:
        outcome = await TelegramTransport(bot).send_text(chat_id=1, text="x")
    finally:
        await bot.session.close()
        server.shutdown()
        server.server_close()
    assert (outcome.ok, outcome.network) == (False, False)


async def test_the_production_bot_gives_up_after_fifteen_seconds_not_sixty(
    production_bot, blackhole: Blackhole
) -> None:
    """The real timeout, measured once, against a real silent server."""
    bot = production_bot(blackhole.base_url, timeout=None)
    assert bot.session.timeout == TELEGRAM_REQUEST_TIMEOUT == 15
    started = time.monotonic()
    try:
        outcome = await TelegramTransport(bot).send_text(chat_id=1, text="x")
    finally:
        await bot.session.close()
    took = time.monotonic() - started
    print(f"\n  one send into an outage took {took:.1f}s")
    assert outcome.network is True
    assert 14 <= took < 25, f"the send gave up after {took:.1f}s"


# --------------------------------------------------------------------------
# the reminder tick in a real outage
# --------------------------------------------------------------------------


async def _reminder_state(db: AsyncConnection) -> list[tuple[str, int, str]]:
    result = await db.execute(
        text("SELECT merge_key, attempts, state FROM scheduled_notifications ORDER BY merge_key")
    )
    return [tuple(r) for r in result]  # type: ignore[misc]


async def test_an_outage_stops_the_reminder_tick_after_three_sends(
    db: AsyncConnection,
    reminder_world: dict,
    sessions: async_sessionmaker[AsyncSession],
    production_bot,
    blackhole: Blackhole,
) -> None:
    """DEFECT IF THIS FAILS. Six groups are due and claimed; Telegram answers
    nothing. The tick must put exactly BREAKER_THRESHOLD requests on the wire and
    hand the other three back untouched: no attempt burned, no claim left behind,
    due time unchanged so the next tick takes them at once."""
    for n in range(DUE):
        await add_due_row(db, reminder_world, day=n + 1, merge_key=f"outage-{n}")

    bot = production_bot(blackhole.base_url)
    transport = CountingTransport(TelegramTransport(bot))
    started = time.monotonic()
    try:
        result = await tick(sessions, transport)
    finally:
        await bot.session.close()
    took = time.monotonic() - started

    print(f"\n  {DUE} due, {OUTAGE_TIMEOUT}s -> {len(transport.outcomes)} sends, {took:.1f}s")
    assert len(transport.outcomes) == BREAKER_THRESHOLD == 3
    assert blackhole.requests == 3, "requests reached the silent server"
    assert all(o.network for o in transport.outcomes)
    assert (result.failed, result.handed_back) == (3, 3)
    assert await _reminder_state(db) == [
        ("outage-0", 1, "failed"),
        ("outage-1", 1, "failed"),
        ("outage-2", 1, "failed"),
        ("outage-3", 0, "pending"),
        ("outage-4", 0, "pending"),
        ("outage-5", 0, "pending"),
    ]
    claims = (await db.execute(text("SELECT count(*) FROM message_log"))).scalar_one()
    assert claims == 0, "a claim was left behind; the next tick would skip those groups"


async def test_the_reminders_handed_back_go_out_on_the_next_tick(
    db: AsyncConnection,
    reminder_world: dict,
    sessions: async_sessionmaker[AsyncSession],
    production_bot,
    blackhole: Blackhole,
) -> None:
    """CONFIRMATION IF THIS PASSES. Telegram comes back. The three that were
    never attempted go at once; the three that failed wait out RETRY_BACKOFF."""
    for n in range(DUE):
        await add_due_row(db, reminder_world, day=n + 1, merge_key=f"outage-{n}")

    down = production_bot(blackhole.base_url)
    try:
        await tick(sessions, TelegramTransport(down))
    finally:
        await down.session.close()

    with FakeTelegram() as telegram:
        up = production_bot(telegram.base_url)
        try:
            result = await tick(sessions, TelegramTransport(up))
        finally:
            await up.session.close()

    assert result.sent == 3
    assert telegram.calls == ["sendMessage"] * 3
    assert [s for _, _, s in await _reminder_state(db)] == ["failed"] * 3 + ["sent"] * 3


async def test_a_network_failure_streak_is_reset_by_telegram_answering(
    db: AsyncConnection, reminder_world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """DEFECT IF THIS FAILS. Two timeouts, then Telegram answers -- a 400, a 403
    and a success all prove it is up -- then two more. Never three in a row, so
    every group is attempted. Scripted outcomes are right here: this is the
    counting rule, not the outage."""
    outcomes = [
        SendResult.unreachable("TelegramNetworkError"),
        SendResult.unreachable("TelegramNetworkError"),
        SendResult.failed("TelegramBadRequest"),
        SendResult.unreachable("TelegramNetworkError"),
        SendResult.unreachable("TelegramNetworkError"),
        SendResult.sent(1),
        SendResult.unreachable("TelegramNetworkError"),
        SendResult.unreachable("TelegramNetworkError"),
    ]
    for n in range(len(outcomes)):
        await add_due_row(db, reminder_world, day=n + 1, merge_key=f"streak-{n}")

    transport = FakeTransport(*outcomes)
    result = await tick(sessions, transport)

    assert len(transport.calls) == len(outcomes)
    assert result.handed_back == 0


def test_the_breaker_counts_only_consecutive_network_failures() -> None:
    unreachable = SendResult.unreachable("TelegramNetworkError")
    for answered in (
        SendResult.sent(1),
        SendResult.failed("TelegramBadRequest"),
        SendResult.forbidden(),
        SendResult.rate_limited(3),
    ):
        breaker = CircuitBreaker()
        for outcome in (unreachable, unreachable, answered, unreachable, unreachable):
            breaker.record(outcome)
        assert not breaker.open, f"{answered} did not reset the count"

    breaker = CircuitBreaker()
    for _ in range(BREAKER_THRESHOLD):
        breaker.record(unreachable)
    assert breaker.open


# --------------------------------------------------------------------------
# the order-ping tick in a real outage
# --------------------------------------------------------------------------


async def _ping_state(db: AsyncConnection) -> list[tuple[int, str, bool]]:
    result = await db.execute(
        text("SELECT attempts, state, claimed_at IS NULL FROM order_reminders ORDER BY id")
    )
    return [tuple(r) for r in result]  # type: ignore[misc]


async def test_an_outage_stops_the_order_ping_tick_after_three_sends(
    ping_world: dict, production_bot, blackhole: Blackhole
) -> None:
    """DEFECT IF THIS FAILS. Same claim for the shop-facing outbox: five
    announcements due, three requests reach the silent server, two go back to
    PENDING with no attempt counted and no claim held."""
    db, shop, customer = ping_world["db"], ping_world["shop"], ping_world["customer"]
    await _ping(db, shop, ping_world["order"], number=ANNOUNCEMENT)
    for n in range(4):
        order = await _make_order(db, shop, customer, token=f"outage-{n}")
        await _ping(db, shop, order, number=ANNOUNCEMENT)

    bot = production_bot(blackhole.base_url)
    transport = CountingTransport(TelegramTransport(bot))
    try:
        async with bound_session_factory(db)() as session:
            result = await run_order_ping_tick(
                session, transport=transport, now_utc=datetime.now(UTC)
            )
    finally:
        await bot.session.close()

    assert len(transport.outcomes) == 3
    assert blackhole.requests == 3
    assert (result.failed, result.handed_back) == (3, 2)
    assert await _ping_state(db) == [(1, "failed", True)] * 3 + [(0, "pending", True)] * 2


async def test_a_ping_handed_back_after_earlier_failures_stays_failed(
    ping_world: dict, production_bot, blackhole: Blackhole
) -> None:
    """The state a handed-back ping returns to is recovered from its attempts:
    one that had already failed goes back to FAILED with its count intact, not
    to PENDING as if it had never been tried."""
    db, shop, customer = ping_world["db"], ping_world["shop"], ping_world["customer"]
    for n in range(4):
        order = await _make_order(db, shop, customer, token=f"retry-{n}")
        await _ping(db, shop, order, number=ANNOUNCEMENT, state="failed", attempts=2)

    bot = production_bot(blackhole.base_url)
    try:
        async with bound_session_factory(db)() as session:
            await run_order_ping_tick(
                session, transport=TelegramTransport(bot), now_utc=datetime.now(UTC)
            )
    finally:
        await bot.session.close()

    ordered = await db.execute(
        text(
            "SELECT r.attempts, r.state FROM order_reminders r JOIN orders o ON o.id = r.order_id "
            "WHERE o.submit_token LIKE 'retry-%' ORDER BY r.id"
        )
    )
    assert [tuple(r) for r in ordered] == [(3, "failed")] * 3 + [(2, "failed")]


async def test_an_outage_stops_the_fan_out_to_owners_too(
    ping_world: dict, production_bot, blackhole: Blackhole
) -> None:
    """With no group chat the ping fans out to every owner, one send each. Five
    owners into an outage is five timeouts for ONE ping unless the breaker is
    consulted between them."""
    db, shop = ping_world["db"], ping_world["shop"]
    await db.execute(
        text(
            "UPDATE shops SET group_chat_id = NULL, owner_telegram_ids = '{501,502,503,504,505}' "
            "WHERE id = :s"
        ),
        {"s": shop},
    )
    await _ping(db, shop, ping_world["order"], number=ANNOUNCEMENT)

    bot = production_bot(blackhole.base_url)
    try:
        async with bound_session_factory(db)() as session:
            await run_order_ping_tick(
                session, transport=TelegramTransport(bot), now_utc=datetime.now(UTC)
            )
    finally:
        await bot.session.close()

    assert blackhole.requests == 3


async def test_an_outage_loses_nothing(ping_world: dict, production_bot, blackhole) -> None:
    """CONFIRMATION IF THIS PASSES. After an outage tick every ping it attempted
    is FAILED with one attempt, which the ping tick treats as sendable -- so it
    is retried once Telegram is back, and parks in dead_letter (and alerts) only
    after MAX_PING_ATTEMPTS. Nothing is dropped."""
    db, shop = ping_world["db"], ping_world["shop"]
    await _ping(db, shop, ping_world["order"], number=ANNOUNCEMENT)

    bot = production_bot(blackhole.base_url)
    try:
        async with bound_session_factory(db)() as session:
            await run_order_ping_tick(
                session, transport=TelegramTransport(bot), now_utc=datetime.now(UTC)
            )
    finally:
        await bot.session.close()

    assert await _ping_state(db) == [(1, "failed", True)]
