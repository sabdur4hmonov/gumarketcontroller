"""The health alerts and the daily summary go out through EACH shop's own bot.

The last of the single-bot send paths. `check_health` and `send_daily_summary`
already looped over every shop and already chose each shop's GROUP -- but sent
every shop's message through one global Bot, the same defect C1/C2 fixed for
reminders and order pings. A stall alert says how much of a shop's outbox is
stuck; delivered by another shop's bot, it is another shop's business in a
stranger's words, or it never arrives at all.

Two layers, as with C1/C2: the routing itself against a real rolled-back
database, and the Celery task body's wiring -- where the global bot lived.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from aiogram import Bot
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import TEST_TOKEN, RecordingSession, bound_session_factory

import gulbot.bot.factory as factory_module
import gulbot.sending.alerts as alerts_module
import gulbot.worker.tasks as tasks_module
from gulbot.bot.registry import BotRegistry
from gulbot.config import Settings
from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.sending.alerts import render_stalled, render_summary
from gulbot.sending.health import read_daily_totals, read_health
from gulbot.sending.telegram import TelegramTransport
from gulbot.sending.transport import ShopBotUnavailable

TOKEN = {
    "A": "111111:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    "B": "222222:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
}
GROUP = {"A": -1_001_111, "B": -1_002_222}
#: Different sizes on purpose, so each shop's message has different content
#: and a message in the wrong group is recognisable, not just misaddressed.
OVERDUE = {"A": 1, "B": 3}
SENT_TODAY = {"A": 2, "B": 5}


class Bots:
    def __init__(self) -> None:
        self.sessions: dict[str, RecordingSession] = {}

    def __call__(self, token: str | None) -> Bot:
        assert token is not None, "every shop here has its own token"
        session = self.sessions.setdefault(token, RecordingSession())
        return Bot(token=token, session=session)

    def texts(self, label: str) -> list[tuple[int, str]]:
        session = self.sessions.get(TOKEN[label])
        return [] if session is None else [(c.chat_id, c.text) for c in session.calls]


@pytest_asyncio.fixture
async def world(db: AsyncConnection) -> dict[str, Any]:
    now = datetime.now(UTC)
    out: dict[str, Any] = {"db": db, "now": now, "shop": {}}
    day = 0
    for label in ("A", "B"):
        shop = (
            await db.execute(
                text(
                    "INSERT INTO shops (name, working_hours, group_chat_id) "
                    "VALUES (:n, CAST(:wh AS jsonb), :g) RETURNING id"
                ),
                {"n": f"Shop {label}", "wh": json.dumps(DEFAULT_WORKING_HOURS), "g": GROUP[label]},
            )
        ).scalar_one()
        customer = (
            await db.execute(
                text(
                    "INSERT INTO customers (shop_id, telegram_user_id) VALUES (:s, :t) RETURNING id"
                ),
                {"s": shop, "t": 9_000 + shop % 1000},
            )
        ).scalar_one()
        recipient = (
            await db.execute(
                text(
                    "INSERT INTO recipients (shop_id, customer_id, label, type) "
                    "VALUES (:s, :c, 'Onam', 'mother') RETURNING id"
                ),
                {"s": shop, "c": customer},
            )
        ).scalar_one()
        rows = [("pending", now - timedelta(hours=2), None)] * OVERDUE[label] + [
            ("sent", now - timedelta(minutes=5), now - timedelta(minutes=5))
        ] * SENT_TODAY[label]
        for state, due, sent_at in rows:
            day += 1
            occasion = (
                await db.execute(
                    text(
                        "INSERT INTO occasions (shop_id, customer_id, recipient_id, label, type, "
                        " kind, month, day) "
                        "VALUES (:s, :c, :r, 'Onam', 'mother', 'birthday', 3, :d) RETURNING id"
                    ),
                    {"s": shop, "c": customer, "r": recipient, "d": day},
                )
            ).scalar_one()
            await db.execute(
                text(
                    "INSERT INTO scheduled_notifications (shop_id, customer_id, occasion_id, "
                    " occurrence_year, offset_days, due_at_utc, channel, state, sent_at) "
                    "VALUES (:s, :c, :o, 2027, 0, :due, 'telegram', :st, :sent)"
                ),
                {"s": shop, "c": customer, "o": occasion, "due": due, "st": state, "sent": sent_at},
            )
        out["shop"][label] = int(shop)
    return out


async def _run(world: dict[str, Any], job: str) -> tuple[Bots, dict[str, int], dict[str, str]]:
    """Run the job for every shop, and work out what each shop SHOULD be told."""
    from gulbot.sending.alerts import announce_for_every_shop

    bots = Bots()
    by_shop = {world["shop"][label]: TOKEN[label] for label in ("A", "B")}
    reg = BotRegistry(token_for=by_shop.__getitem__, bot_factory=bots)
    expected: dict[str, str] = {}
    async with bound_session_factory(world["db"])() as session:
        for label in ("A", "B"):
            shop = world["shop"][label]
            if job == "summary":
                totals = await read_daily_totals(session, shop_id=shop, now_utc=world["now"])
                expected[label] = render_summary(totals)
            else:
                health = await read_health(session, shop_id=shop, now_utc=world["now"])
                expected[label] = render_stalled(health)
        try:
            counts = await announce_for_every_shop(
                session,
                job=job,
                transport_for=lambda shop_id: TelegramTransport(reg.bot_for(shop_id)),
                now_utc=world["now"],
            )
        finally:
            await reg.close()
    assert expected["A"] != expected["B"], "the fixture must make the two messages differ"
    return bots, counts, expected


@pytest.mark.infra
@pytest.mark.parametrize("job", ["check", "summary"])
async def test_shop_a_s_alert_never_reaches_shop_b(world: dict[str, Any], job: str) -> None:
    bots, counts, expected = await _run(world, job)

    for us, them in (("A", "B"), ("B", "A")):
        ours = bots.texts(us)
        # Each shop hears its own message, from its own bot, in its own group.
        assert ours == [(GROUP[us], expected[us])]
        # And nothing of the other shop's, on any path.
        assert all(body != expected[them] for _, body in ours)
        assert all(chat != GROUP[them] for chat, _ in ours)
    assert counts["unreachable"] == 0


@pytest.mark.infra
async def test_a_shop_without_a_bot_is_skipped_loudly_and_the_rest_still_hear(
    world: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    from gulbot.sending.alerts import announce_for_every_shop
    from gulbot.sending.transport import ShopBotUnavailable

    bots = Bots()
    shop_a, shop_b = world["shop"]["A"], world["shop"]["B"]

    def token_for(shop_id: int) -> str:
        if shop_id == shop_b:
            raise ShopBotUnavailable(shop_id, "no bot token is stored (shops.bot_token_encrypted)")
        return TOKEN["A"]

    reg = BotRegistry(token_for=token_for, bot_factory=bots)
    async with bound_session_factory(world["db"])() as session:
        try:
            counts = await announce_for_every_shop(
                session,
                job="summary",
                transport_for=lambda shop_id: TelegramTransport(reg.bot_for(shop_id)),
                now_utc=world["now"],
            )
        finally:
            await reg.close()

    assert counts["unreachable"] == 1
    assert [chat for chat, _ in bots.texts("A")] == [GROUP["A"]]
    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(errors) == 1 and f"shop {shop_b}" in errors[0].getMessage()
    assert errors[0].exc_info is None
    assert shop_a != shop_b


# --- a shop the registry has no bot for (CP17) -------------------------------
#
# Found 2026-10-05: the job raised KeyError out of `BotRegistry.bot_for` on the
# first shop row its resolver had no entry for, and every shop after it went
# unalerted. The resolver's contract is ShopBotUnavailable; the registry now
# holds every resolver to it, so the job skips that one shop, says so, and the
# rest are still told.


async def _outcome(call: Any) -> BaseException | None:
    """What the call raised, if anything -- asserted on in the test, so a crash
    is a failed assertion and not an error."""
    try:
        await call
    except Exception as error:  # noqa: BLE001 - the type is the assertion
        return error
    return None


def test_a_resolver_with_no_entry_for_the_shop_is_a_clear_refusal() -> None:
    registry = BotRegistry(token_for={}.__getitem__, bot_factory=Bots())
    try:
        registry.bot_for(7)
    except Exception as error:  # noqa: BLE001 - the type is the assertion
        refused: BaseException | None = error
    else:
        refused = None
    assert isinstance(refused, ShopBotUnavailable), repr(refused)
    assert refused.shop_id == 7
    assert "no bot is registered" in str(refused)


@pytest.mark.infra
async def test_a_shop_row_with_no_registered_bot_does_not_stop_the_job(
    world: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    from gulbot.sending.alerts import announce_for_every_shop

    db = world["db"]
    shop_c = (
        await db.execute(
            text(
                "INSERT INTO shops (name, working_hours, group_chat_id) "
                "VALUES ('Shop C, onboarding never finished', CAST(:wh AS jsonb), -1003333) "
                "RETURNING id"
            ),
            {"wh": json.dumps(DEFAULT_WORKING_HOURS)},
        )
    ).scalar_one()
    bots = Bots()
    # Only A and B have a bot; C -- and any shop row this test did not make --
    # is a KeyError to this resolver, exactly the crash that was found.
    registered = {world["shop"][label]: TOKEN[label] for label in ("A", "B")}
    reg = BotRegistry(token_for=registered.__getitem__, bot_factory=bots)
    counts: dict[str, int] = {}

    async def job() -> None:
        counts.update(
            await announce_for_every_shop(
                session,
                job="summary",
                transport_for=lambda shop_id: TelegramTransport(reg.bot_for(shop_id)),
                now_utc=world["now"],
            )
        )

    async with bound_session_factory(db)() as session:
        try:
            crashed = await _outcome(job())
        finally:
            await reg.close()

    assert crashed is None, f"one shop without a bot stopped every shop's alerts: {crashed!r}"
    # Both shops with a bot were still told, each in its own group.
    assert [chat for chat, _ in bots.texts("A")] == [GROUP["A"]]
    assert [chat for chat, _ in bots.texts("B")] == [GROUP["B"]]
    # Every shop without one was skipped and counted -- C among them.
    assert counts["unreachable"] == counts["shops"] - 2 >= 1
    errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any(f"shop {shop_c} has no usable bot" in line for line in errors), errors
    assert all(r.exc_info is None for r in caplog.records if r.levelname == "ERROR")


# --- the worker wiring ------------------------------------------------------


class _Session:
    async def scalars(self, statement: Any) -> list[int]:
        return [1, 2]

    async def commit(self) -> None:
        return None


@asynccontextmanager
async def _no_database() -> AsyncIterator[Any]:
    @asynccontextmanager
    async def session() -> AsyncIterator[_Session]:
        yield _Session()

    yield session


@pytest.fixture
def worker(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The REAL `_for_every_shop`, with the database, the registry and the two
    alert functions replaced by recorders. Under test: which bot each shop's
    message went through."""
    bots = Bots()
    seen: dict[str, Any] = {"bots": bots}

    async def registry_for(session: Any, **kwargs: Any) -> BotRegistry:
        return BotRegistry(token_for={1: TOKEN["A"], 2: TOKEN["B"]}.__getitem__, bot_factory=bots)

    async def announce(session: Any, *, transport: Any, shop_id: int, **kwargs: Any) -> list[str]:
        await transport.send_text(chat_id=shop_id, text=f"for shop {shop_id}")
        return ["stalled"]

    # A global bot, if the task still builds one, records under TEST_TOKEN and
    # never reaches the network.
    global_session = RecordingSession()
    seen["global"] = global_session
    monkeypatch.setattr(factory_module, "get_settings", lambda: Settings(bot_token=TEST_TOKEN))
    monkeypatch.setattr(
        factory_module,
        "build_bot",
        lambda token=None: Bot(token=TEST_TOKEN, session=global_session),
    )
    monkeypatch.setattr(tasks_module, "task_session_factory", _no_database)
    monkeypatch.setattr(tasks_module, "registry_for", registry_for, raising=False)
    monkeypatch.setattr(alerts_module, "check_and_alert", announce)
    monkeypatch.setattr(alerts_module, "send_daily_summary", announce)
    return seen


@pytest.mark.parametrize("job", ["check", "summary"])
async def test_the_worker_sends_each_shop_s_alert_through_its_own_bot(
    job: str, worker: dict[str, Any]
) -> None:
    await tasks_module._for_every_shop(job)

    bots: Bots = worker["bots"]
    assert worker["global"].calls == [], "a single global bot sent the alerts"
    assert bots.texts("A") == [(1, "for shop 1")]
    assert bots.texts("B") == [(2, "for shop 2")]
