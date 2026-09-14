# ruff: noqa: F811, F401  -- fixtures are imported by name; pytest injects them into
# the same-named test parameters, which ruff reads as a redefinition.
"""An answer that is not the Bot API must go through the breaker, not around it.

Found in the pre-deployment audit, pass 6, and the same shape as pass 1's
reminder-loss bug: an exception type that bypasses the protection built for its
exact case. During an incident Telegram's edge, or a proxy in front of it, can
answer with an HTML page instead of JSON. aiogram raises ClientDecodeError, which
is not a TelegramAPIError, so `TelegramTransport` did not translate it. Reproduced
through the real tick: it raised on the first send and left all three claims
stuck in 'claimed' for CLAIM_TIMEOUT.

The server here is real HTTP on localhost answering `502 Bad Gateway` with an
HTML body, and the bot and transport are the production ones.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker
from tests.bot_harness import bound_session_factory
from tests.test_audit_outage import CountingTransport, production_bot
from tests.test_dispatcher import add_due_row, sessions, tick
from tests.test_dispatcher import world as reminder_world
from tests.test_order_pings import _make_order, _ping
from tests.test_order_pings import world as ping_world

from gulbot.sending.order_card import ANNOUNCEMENT
from gulbot.sending.order_pings import run_order_ping_tick
from gulbot.sending.telegram import TelegramTransport

pytestmark = pytest.mark.infra

BAD_GATEWAY = b"<html><head><title>502 Bad Gateway</title></head><body>nginx</body></html>"


class _Html502(BaseHTTPRequestHandler):
    server: HtmlErrorServer  # type: ignore[assignment]

    def do_POST(self) -> None:  # noqa: N802
        self.server.requests += 1
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        self.send_response(502)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(BAD_GATEWAY)))
        self.end_headers()
        self.wfile.write(BAD_GATEWAY)

    def log_message(self, format: str, *args: object) -> None:
        return None


class HtmlErrorServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Html502)
        self.requests = 0

    @property
    def base_url(self) -> str:
        host, port = self.server_address[0], self.server_address[1]
        return f"http://{host}:{port}"


@pytest.fixture
def html_error() -> Iterator[HtmlErrorServer]:
    server = HtmlErrorServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


async def test_an_html_error_page_is_reported_as_unreachable(
    production_bot, html_error: HtmlErrorServer
) -> None:
    """DEFECT IF THIS FAILS. Before the fix this call RAISED."""
    bot = production_bot(html_error.base_url)
    try:
        outcome = await TelegramTransport(bot).send_text(chat_id=1, text="x")
    finally:
        await bot.session.close()
    assert (outcome.ok, outcome.network, outcome.error_code) == (
        False,
        True,
        "ClientDecodeError",
    )


async def test_copy_message_reports_an_html_error_page_as_unreachable(
    production_bot, html_error: HtmlErrorServer
) -> None:
    """The browse screen's path has its own try block; it gets the same branch."""
    bot = production_bot(html_error.base_url)
    try:
        outcome = await TelegramTransport(bot).copy_message(
            chat_id=1, from_chat_id=-100, message_id=5
        )
    finally:
        await bot.session.close()
    assert (outcome.ok, outcome.network) == (False, True)


async def test_an_html_error_page_trips_the_reminder_breaker_instead_of_crashing(
    db: AsyncConnection,
    reminder_world: dict,
    sessions: async_sessionmaker[AsyncSession],
    production_bot,
    html_error: HtmlErrorServer,
) -> None:
    """DEFECT IF THIS FAILS. The live reproduction, inverted: six due, the tick
    completes, three requests reach the server, three are handed back, and no
    claim is left stranded."""
    for n in range(6):
        await add_due_row(db, reminder_world, day=n + 1, merge_key=f"html-{n}")

    bot = production_bot(html_error.base_url)
    transport = CountingTransport(TelegramTransport(bot))
    try:
        result = await tick(sessions, transport)
    finally:
        await bot.session.close()

    assert html_error.requests == 3
    assert (result.failed, result.handed_back) == (3, 3)
    claims = (await db.execute(text("SELECT count(*) FROM message_log"))).scalar_one()
    assert claims == 0, "claims were stranded"


async def test_an_html_error_page_trips_the_ping_breaker_instead_of_crashing(
    ping_world: dict, production_bot, html_error: HtmlErrorServer
) -> None:
    db, shop, customer = ping_world["db"], ping_world["shop"], ping_world["customer"]
    await _ping(db, shop, ping_world["order"], number=ANNOUNCEMENT)
    for n in range(4):
        order = await _make_order(db, shop, customer, token=f"html-{n}")
        await _ping(db, shop, order, number=ANNOUNCEMENT)

    bot = production_bot(html_error.base_url)
    try:
        async with bound_session_factory(db)() as session:
            result = await run_order_ping_tick(
                session, transport=TelegramTransport(bot), now_utc=datetime.now(UTC)
            )
    finally:
        await bot.session.close()

    assert html_error.requests == 3
    assert (result.failed, result.handed_back) == (3, 2)
