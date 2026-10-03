"""C1/C2 of AUDIT_MULTI_TENANT.md: every outbox row leaves through ITS shop's bot.

Both ticks drain a global outbox -- they select due rows across every shop, by
design. Until this fix they then pushed every one of those rows through a single
Bot. With one bot per shop that means shop A's order card, customer phone and
address included, sent by shop B's bot; or, if shop B's bot is not in shop A's
group, never delivered at all.

Two layers are proven here, because the bug had two:

* THE TICKS route per row: `transport_for(shop_id)`, real `Bot`s with distinct
  tokens, a real rolled-back database, no Telegram network.
* THE WORKER actually uses that: the Celery task bodies hand the ticks a
  per-shop resolver, not one transport. The old defect lived in the wiring --
  a tick that CAN route per shop is no use if the task never asks it to.
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
from aiogram.methods import SendMessage, SendPhoto
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import TEST_TOKEN, RecordingSession, bound_session_factory

import gulbot.sending.order_pings as order_pings_module
import gulbot.worker.tasks as tasks_module
from gulbot.bot.registry import BotRegistry
from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.sending.dispatcher import run_tick
from gulbot.sending.order_card import ANNOUNCEMENT
from gulbot.sending.order_pings import run_order_ping_tick
from gulbot.sending.render import render_reminder
from gulbot.sending.telegram import TelegramTransport

TOKEN = {
    "A": "111111:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    "B": "222222:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
}
GROUP = {"A": -1_001_111, "B": -1_002_222}
CUSTOMER_TG = {"A": 8_001, "B": 8_002}
BOUQUET = {"A": "Oq atirgul (SHOP A)", "B": "Qizil lola (SHOP B)"}


class Registry:
    """A real BotRegistry whose bots record instead of calling Telegram."""

    def __init__(self, token_by_shop: dict[int, str]) -> None:
        self.sessions: dict[str, RecordingSession] = {}
        self.built: list[str] = []
        self.registry = BotRegistry(token_for=token_by_shop.__getitem__, bot_factory=self._bot)

    def _bot(self, token: str | None) -> Bot:
        assert token is not None
        self.built.append(token)
        session = self.sessions[token] = RecordingSession()
        return Bot(token=token, session=session)

    def transport_for(self, shop_id: int) -> TelegramTransport:
        return TelegramTransport(self.registry.bot_for(shop_id))

    def calls(self, label: str) -> list[Any]:
        session = self.sessions.get(TOKEN[label])
        return [] if session is None else session.calls


def _body(call: Any) -> str:
    return getattr(call, "caption", None) or getattr(call, "text", None) or ""


@pytest_asyncio.fixture
async def world(db: AsyncConnection) -> dict[str, Any]:
    """Two shops, each with a group, a customer, an order and a due reminder."""
    out: dict[str, Any] = {"db": db, "shop": {}, "order": {}}
    due = datetime.now(UTC) - timedelta(seconds=1)
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
                    "INSERT INTO customers (shop_id, telegram_user_id, phone, phone_verified) "
                    "VALUES (:s, :t, '+998901234567', true) RETURNING id"
                ),
                {"s": shop, "t": CUSTOMER_TG[label]},
            )
        ).scalar_one()
        order = (
            await db.execute(
                text(
                    "INSERT INTO orders (shop_id, customer_id, product_name_snapshot, "
                    " price_uzs_snapshot, telegram_file_id_snapshot, delivery_date, "
                    " delivery_hour, delivery_location_text, landmark, status, submit_token) "
                    "VALUES (:s, :c, :n, 450000, :f, CURRENT_DATE + 1, '14:00', "
                    " :addr, 'Ko''k eshik', 'placed', 't') RETURNING id"
                ),
                {
                    "s": shop,
                    "c": customer,
                    "n": BOUQUET[label],
                    "f": f"file-{label}",
                    "addr": f"Address of {label}",
                },
            )
        ).scalar_one()
        await db.execute(
            text(
                "INSERT INTO order_reminders (shop_id, order_id, ping_number, due_at_utc) "
                "VALUES (:s, :o, :n, :d)"
            ),
            {"s": shop, "o": order, "n": ANNOUNCEMENT, "d": due},
        )
        recipient = (
            await db.execute(
                text(
                    "INSERT INTO recipients (shop_id, customer_id, label, type) "
                    "VALUES (:s, :c, :l, 'mother') RETURNING id"
                ),
                {"s": shop, "c": customer, "l": f"Onam {label}"},
            )
        ).scalar_one()
        occasion = (
            await db.execute(
                text(
                    "INSERT INTO occasions (shop_id, customer_id, recipient_id, type, kind, "
                    " label, month, day) "
                    "VALUES (:s, :c, :r, 'mother', 'birthday', :l, 3, 8) RETURNING id"
                ),
                {"s": shop, "c": customer, "r": recipient, "l": f"Onam {label}"},
            )
        ).scalar_one()
        await db.execute(
            text(
                "INSERT INTO scheduled_notifications (shop_id, customer_id, occasion_id, "
                " occurrence_year, offset_days, due_at_utc, channel) "
                "VALUES (:s, :c, :o, 2027, 0, :d, 'telegram')"
            ),
            {"s": shop, "c": customer, "o": occasion, "d": due},
        )
        out["shop"][label] = int(shop)
        out["order"][label] = int(order)
    return out


@pytest_asyncio.fixture
async def registry(world: dict[str, Any]) -> AsyncIterator[Registry]:
    shops = world["shop"]
    reg = Registry({shops["A"]: TOKEN["A"], shops["B"]: TOKEN["B"]})
    try:
        yield reg
    finally:
        await reg.registry.close()


# --- the order-ping tick (C2) ----------------------------------------------


@pytest.mark.infra
async def test_shop_a_s_order_never_reaches_shop_b_s_admin_group(
    world: dict[str, Any], registry: Registry
) -> None:
    """The headline guarantee, stated from shop B's side: nothing about shop A's
    order is sent into shop B's group, and shop B's bot sends nothing about it
    anywhere."""
    async with bound_session_factory(world["db"])() as session:
        result = await run_order_ping_tick(
            session, transport_for=registry.transport_for, now_utc=datetime.now(UTC)
        )
    assert result.sent == 2

    # Direction by direction, because a one-sided check passes vacuously. A
    # mutation run proved it: with every card sent by bot A, "bot B said
    # nothing about A" was true only because bot B said nothing at all.
    for us, them in (("A", "B"), ("B", "A")):
        ours = registry.calls(us)
        assert ours, f"shop {us}'s order must still reach shop {us}'s group"
        # Each bot speaks only about its own shop's order ...
        assert all(BOUQUET[us] in _body(c) for c in ours)
        assert not [c for c in ours if BOUQUET[them] in _body(c)]
        # ... and only into its own shop's group.
        assert {c.chat_id for c in ours} == {GROUP[us]}

    everything = registry.calls("A") + registry.calls("B")
    into_b_group = [c for c in everything if c.chat_id == GROUP["B"]]
    assert not [c for c in into_b_group if BOUQUET["A"] in _body(c)]


@pytest.mark.infra
async def test_each_order_card_is_sent_by_its_own_shop_s_bot_to_its_own_group(
    world: dict[str, Any], registry: Registry
) -> None:
    async with bound_session_factory(world["db"])() as session:
        await run_order_ping_tick(
            session, transport_for=registry.transport_for, now_utc=datetime.now(UTC)
        )

    for label in ("A", "B"):
        calls = registry.calls(label)
        assert [type(c) for c in calls] == [SendPhoto]
        assert calls[0].chat_id == GROUP[label]
        assert BOUQUET[label] in _body(calls[0])
        # The card's buttons act on THIS shop's order.
        buttons = [b.callback_data for row in calls[0].reply_markup.inline_keyboard for b in row]
        assert all(str(world["order"][label]) in data for data in buttons)


# --- the reminder tick (C1) -------------------------------------------------


@pytest.mark.infra
async def test_each_reminder_is_sent_by_its_customer_s_shop_s_bot(
    world: dict[str, Any], registry: Registry
) -> None:
    async with bound_session_factory(world["db"])() as session:
        result = await run_tick(
            session,
            transport_for=registry.transport_for,
            render=render_reminder,
            now_utc=datetime.now(UTC),
        )
    assert result.sent == 2

    for label in ("A", "B"):
        calls = registry.calls(label)
        assert [type(c) for c in calls] == [SendMessage]
        assert calls[0].chat_id == CUSTOMER_TG[label]


@pytest.mark.infra
async def test_one_bot_is_built_per_shop_within_a_tick(
    world: dict[str, Any], registry: Registry
) -> None:
    """A cache, not a Bot per row: both ticks in one registry build two."""
    async with bound_session_factory(world["db"])() as session:
        await run_tick(
            session,
            transport_for=registry.transport_for,
            render=render_reminder,
            now_utc=datetime.now(UTC),
        )
        await run_order_ping_tick(
            session, transport_for=registry.transport_for, now_utc=datetime.now(UTC)
        )
    assert sorted(registry.built) == sorted(TOKEN.values())


# --- the registry -----------------------------------------------------------


async def test_shops_sharing_a_token_share_one_bot() -> None:
    reg = Registry({1: TOKEN["A"], 2: TOKEN["A"], 3: TOKEN["B"]})
    try:
        assert reg.registry.bot_for(1) is reg.registry.bot_for(2)
        assert reg.registry.bot_for(1) is not reg.registry.bot_for(3)
        assert reg.built == [TOKEN["A"], TOKEN["B"]]
    finally:
        await reg.registry.close()


def test_a_tick_refuses_to_guess_between_one_transport_and_a_resolver() -> None:
    """Exactly one of `transport=` / `transport_for=`. Both, or neither, is a
    caller bug, and a silent choice between them is how a global bot returns."""
    from gulbot.sending.transport import per_shop

    only = object()
    with pytest.raises(TypeError):
        per_shop(None, None)
    with pytest.raises(TypeError):
        per_shop(only, lambda shop_id: only)  # type: ignore[arg-type]
    assert per_shop(only, None)(123) is only  # type: ignore[arg-type]


# --- the worker wiring -----------------------------------------------------


class _Session:
    async def commit(self) -> None:
        return None


@asynccontextmanager
async def _no_database() -> AsyncIterator[Any]:
    @asynccontextmanager
    async def session() -> AsyncIterator[_Session]:
        yield _Session()

    yield session


@pytest.fixture
def worker_with_two_shops(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The REAL task bodies, with the database and the ticks replaced by
    recorders. What is under test is only what the task hands the tick."""
    seen: dict[str, Any] = {"registries": []}

    async def registry(session: Any, **kwargs: Any) -> BotRegistry:
        # Stands in for `registry_for(session)`, which reads the shops' stored
        # tokens; the tokens themselves are covered in test_shop_bot_resolution.
        reg = Registry({1: TOKEN["A"], 2: TOKEN["B"]})
        seen["registries"].append(reg)
        return reg.registry

    async def fake_tick(session: Any, **kwargs: Any) -> Any:
        seen["kwargs"] = kwargs
        # Actually use it, while the task still holds the registry open.
        if "transport_for" in kwargs:
            for shop_id in (1, 2):
                await kwargs["transport_for"](shop_id).send_text(chat_id=shop_id, text="x")

        class Result:
            groups = sent = expired = failed = cancelled = handed_back = 0
            claimed = dead_lettered = undeliverable = 0

        return Result()

    # Belt and braces: whatever the task builds, it never sees the real token.
    import gulbot.bot.factory as factory_module
    from gulbot.config import Settings

    monkeypatch.setattr(factory_module, "get_settings", lambda: Settings(bot_token=TEST_TOKEN))
    monkeypatch.setattr(tasks_module, "registry_for", registry)
    monkeypatch.setattr(tasks_module, "task_session_factory", _no_database)
    monkeypatch.setattr(tasks_module, "run_tick", fake_tick)
    monkeypatch.setattr(order_pings_module, "run_order_ping_tick", fake_tick)
    return seen


@pytest.mark.parametrize("task", ["_send_due_reminders", "_send_order_pings"])
async def test_the_worker_sends_each_shop_through_its_own_bot(
    task: str, worker_with_two_shops: dict[str, Any]
) -> None:
    await getattr(tasks_module, task)()

    seen = worker_with_two_shops
    assert "transport" not in seen["kwargs"], "the task handed the tick ONE transport"
    (reg,) = seen["registries"]
    assert [c.chat_id for c in reg.calls("A")] == [1]
    assert [c.chat_id for c in reg.calls("B")] == [2]
