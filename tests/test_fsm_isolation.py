"""C3 of AUDIT_MULTI_TENANT.md: one person, two shops' bots, one Redis.

REPRODUCED 2026-09-26 before it was fixed. With aiogram's default key builder
the FSM key is `fsm:<chat_id>:<user_id>`, and in a private chat chat_id IS the
user id -- so the key named the PERSON, not the conversation. Shop B's bot read
shop A's half-finished order, took the customer's next message as its address,
and on submit wrote a shop-B order for shop A's bouquet at shop A's price
(product_id NULL, so no composite FK could object).

WHY NO EARLIER TEST SAW IT. Every other test uses MemoryStorage, which keys on
the whole StorageKey -- bot id included -- so two bots never collide there. The
bug lived only in RedisStorage's string keys. These tests therefore run against
REAL Redis, through the REAL `build_storage()`, moved to the test db only.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.redis import RedisStorage
from redis import asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import (
    RecordingSession,
    bound_session_factory,
    callback_update,
    feed,
    text_update,
)

import gulbot.bot.factory as factory_module
from gulbot.bot.callbacks import (
    OrderConfirmCB,
    OrderDateCB,
    OrderHourCB,
    OrderLocationCB,
    OrderStartCB,
)
from gulbot.bot.factory import build_dispatcher, build_storage
from gulbot.bot.states import PlaceOrder
from gulbot.config import Settings
from gulbot.i18n.catalog import CATALOG
from gulbot.models.shop import DEFAULT_WORKING_HOURS

pytestmark = pytest.mark.infra

TOKEN_A = "111111:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
TOKEN_B = "222222:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
#: The one person who is a customer of both shops. Only keys naming this id are
#: ever read or deleted, so the test db's other tenants are left alone.
USER = 7_770_101

ADDRESS = "Chilonzor 5, 12-uy"
LANDMARK_PROMPT = CATALOG["order.enter_landmark"]["uz"]


class Side:
    """One shop's bot, as the customer sees it."""

    def __init__(self, dispatcher: Dispatcher, bot: Bot, recorder: RecordingSession) -> None:
        self.dispatcher, self.bot, self.recorder = dispatcher, bot, recorder
        self._update = 0

    def _next(self) -> int:
        self._update += 1
        return self._update

    async def tap(self, data: str) -> None:
        await feed(
            self.dispatcher, self.bot, callback_update(data, user_id=USER, update_id=self._next())
        )

    async def say(self, body: str) -> None:
        await feed(
            self.dispatcher, self.bot, text_update(body, user_id=USER, update_id=self._next())
        )

    async def state(self) -> tuple[str | None, dict[str, Any]]:
        context = self.dispatcher.fsm.get_context(bot=self.bot, chat_id=USER, user_id=USER)
        return await context.get_state(), await context.get_data()

    async def start_order_up_to_the_address(self, product_id: int) -> None:
        await self.tap(OrderStartCB(product_id=product_id).pack())
        await self.tap(OrderDateCB(offset=1).pack())
        await self.tap(OrderHourCB(hour=14).pack())
        await self.tap(OrderLocationCB(mode="text").pack())

    async def finish_order(self) -> None:
        """Address -> landmark -> recipient -> submit, from `entering_address`."""
        await self.say(ADDRESS)
        await self.say("Ko'k eshik")
        await self.say("Aziza")
        await self.tap(OrderConfirmCB(action="submit").pack())


@pytest.fixture
def fsm_on_the_test_db(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """`build_storage()` unchanged, pointed at the test db instead of db 2."""
    moved = settings.model_copy(update={"redis_db_fsm": settings.redis_db_test})
    monkeypatch.setattr(factory_module, "get_settings", lambda: moved)


@pytest_asyncio.fixture
async def raw_redis(settings: Settings) -> AsyncIterator[aioredis.Redis]:
    client = aioredis.from_url(settings.redis_url(settings.redis_db_test))

    async def forget_user() -> None:
        keys = await client.keys(f"*{USER}*")
        if keys:
            await client.delete(*keys)

    await forget_user()
    try:
        yield client
    finally:
        await forget_user()
        await client.aclose()


async def _shop(db: AsyncConnection, name: str, bouquet: str, price: int) -> tuple[int, int]:
    shop = (
        await db.execute(
            text(
                "INSERT INTO shops (name, working_hours) "
                "VALUES (:n, CAST(:wh AS jsonb)) RETURNING id"
            ),
            {"n": name, "wh": json.dumps(DEFAULT_WORKING_HOURS)},
        )
    ).scalar_one()
    product = (
        await db.execute(
            text(
                "INSERT INTO products (shop_id, name, telegram_file_id, source, "
                " channel_message_id,"
                " price_uzs, price_confidence, finalized_at) "
                "VALUES (:s, :n, :f, 'channel', 1, :p, 'high', now()) RETURNING id"
            ),
            {"s": shop, "n": bouquet, "f": f"file-{name}", "p": price},
        )
    ).scalar_one()
    # With a phone, so the flow does not detour through the phone step.
    await db.execute(
        text(
            "INSERT INTO customers (shop_id, telegram_user_id, phone, phone_verified) "
            "VALUES (:s, :t, '+998901112233', true)"
        ),
        {"s": shop, "t": USER},
    )
    return int(shop), int(product)


@pytest_asyncio.fixture
async def world(
    db: AsyncConnection, fsm_on_the_test_db: None, raw_redis: aioredis.Redis
) -> AsyncIterator[dict[str, Any]]:
    shop_a, product_a = await _shop(db, "Shop A", "Oq atirgul (A)", 450_000)
    shop_b, product_b = await _shop(db, "Shop B", "Qizil lola (B)", 300_000)
    sessions = bound_session_factory(db)

    # Two build_storage() calls, as two processes would make.
    storages: list[RedisStorage] = [build_storage(), build_storage()]
    sides = []
    for token, shop, storage in ((TOKEN_A, shop_a, storages[0]), (TOKEN_B, shop_b, storages[1])):
        recorder = RecordingSession()
        dispatcher = build_dispatcher(session_factory=sessions, shop_id=shop, storage=storage)
        sides.append(Side(dispatcher, Bot(token=token, session=recorder), recorder))
    try:
        yield {
            "a": sides[0],
            "b": sides[1],
            "shop_a": shop_a,
            "shop_b": shop_b,
            "product_a": product_a,
            "db": db,
            "redis": raw_redis,
            "sessions": sessions,
        }
    finally:
        for storage in storages:
            await storage.close()


async def _orders(db: AsyncConnection, shop: int) -> list[Any]:
    return list(
        (
            await db.execute(
                text(
                    "SELECT product_id, product_name_snapshot, price_uzs_snapshot "
                    "FROM orders WHERE shop_id = :s"
                ),
                {"s": shop},
            )
        ).all()
    )


def test_build_storage_puts_the_bot_id_in_every_key(fsm_on_the_test_db: None) -> None:
    key_builder = build_storage().key_builder
    same_person = {"chat_id": USER, "user_id": USER}
    a = key_builder.build(StorageKey(bot_id=111111, **same_person), "state")
    b = key_builder.build(StorageKey(bot_id=222222, **same_person), "state")
    assert a != b
    assert a == f"fsm:111111:{USER}:{USER}:state"


async def test_the_keys_written_to_redis_name_the_bot(world: dict[str, Any]) -> None:
    """The exact format, read back from Redis rather than asked of the builder."""
    await world["a"].start_order_up_to_the_address(world["product_a"])
    keys = sorted(k.decode() for k in await world["redis"].keys(f"*{USER}*"))
    assert keys == [f"fsm:111111:{USER}:{USER}:data", f"fsm:111111:{USER}:{USER}:state"]


async def test_shop_b_does_not_see_shop_a_s_order_in_progress(world: dict[str, Any]) -> None:
    await world["a"].start_order_up_to_the_address(world["product_a"])

    state_a, data_a = await world["a"].state()
    assert state_a == PlaceOrder.entering_address.state
    assert data_a["product_id"] == world["product_a"]

    assert await world["b"].state() == (None, {})


async def test_an_address_sent_to_shop_b_is_not_taken_for_shop_a_s_order(
    world: dict[str, Any],
) -> None:
    a, b = world["a"], world["b"]
    await a.start_order_up_to_the_address(world["product_a"])
    before = await a.state()

    await b.say(ADDRESS)

    # The reproduction's tell: shop B asked for a landmark, i.e. it had
    # accepted this as the address of an order it never started.
    assert LANDMARK_PROMPT not in b.recorder.sent_texts
    assert await b.state() == (None, {})
    assert await a.state() == before


async def test_shop_b_cannot_write_an_order_for_shop_a_s_bouquet(world: dict[str, Any]) -> None:
    """The full reproduction, end to end: the row that used to be written."""
    await world["a"].start_order_up_to_the_address(world["product_a"])

    await world["b"].finish_order()

    assert await _orders(world["db"], world["shop_b"]) == []


async def test_shop_a_s_order_still_completes_on_shop_a(world: dict[str, Any]) -> None:
    """Isolation must not cost the conversation that owns the state."""
    await world["a"].start_order_up_to_the_address(world["product_a"])
    await world["b"].say(ADDRESS)  # interleaved traffic to the other shop

    await world["a"].finish_order()

    assert await _orders(world["db"], world["shop_a"]) == [
        (world["product_a"], "Oq atirgul (A)", 450_000)
    ]
    assert await _orders(world["db"], world["shop_b"]) == []


async def test_the_state_survives_a_fresh_storage_for_the_same_bot(world: dict[str, Any]) -> None:
    """A restart builds a new storage. The same bot must find its own state
    again -- a key that also changed per process would lose every flow."""
    await world["a"].start_order_up_to_the_address(world["product_a"])

    storage = build_storage()
    try:
        restarted = build_dispatcher(
            session_factory=world["sessions"], shop_id=world["shop_a"], storage=storage
        )
        side = Side(restarted, world["a"].bot, world["a"].recorder)
        state, data = await side.state()
    finally:
        await storage.close()
    assert state == PlaceOrder.entering_address.state
    assert data["product_id"] == world["product_a"]
