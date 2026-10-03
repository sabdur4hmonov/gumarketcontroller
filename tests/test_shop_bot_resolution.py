"""Which bot speaks for a shop: its own stored token, the legacy fallback, or none.

The rule, in order:

1. The shop has a stored token -> that token. Always, even for the legacy shop.
2. The shop is the legacy one (`uses_process_bot_token`, set by the migration
   only on the single pre-existing shop) -> the process BOT_TOKEN, LOGGED every
   time a registry falls back, because that path is meant to die.
3. Anything else -> `ShopBotUnavailable`, one clear sentence, never a secret.

And what "fails loudly and clearly" means once a tick meets rule 3: ONE error
line naming the shop and what to fix, that shop's row marked failed (so it
retries and eventually parks), and every OTHER shop in the batch still served.
Not a silent skip, and not a stack trace that stops the fleet.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from aiogram import Bot
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import TEST_TOKEN, RecordingSession, bound_session_factory

import gulbot.bot.factory as factory_module
import gulbot.services.shop_tokens as shop_tokens_module
from gulbot.bot.registry import BotRegistry, registry_for, stored_tokens
from gulbot.config import Settings
from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.sending.dispatcher import run_tick
from gulbot.sending.order_card import ANNOUNCEMENT
from gulbot.sending.order_pings import run_order_ping_tick
from gulbot.sending.render import render_reminder
from gulbot.sending.telegram import TelegramTransport
from gulbot.sending.transport import ShopBotUnavailable
from gulbot.services.shop_tokens import ShopBotCredential, encrypt_token, set_shop_bot_token

TOKEN_A = "111111:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
TOKEN_B = "222222:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
SECRETS = [t.split(":", 1)[1] for t in (TOKEN_A, TOKEN_B, TEST_TOKEN)]


@pytest.fixture
def key(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> str:
    fresh = Fernet.generate_key().decode()
    moved = settings.model_copy(update={"shop_token_encryption_key": SecretStr(fresh)})
    monkeypatch.setattr(shop_tokens_module, "get_settings", lambda: moved)
    return fresh


@pytest.fixture
def process_token(monkeypatch: pytest.MonkeyPatch) -> str:
    """BOT_TOKEN as the legacy fallback would see it."""
    monkeypatch.setattr(factory_module, "get_settings", lambda: Settings(bot_token=TEST_TOKEN))
    return TEST_TOKEN


@pytest.fixture
def no_process_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory_module, "get_settings", lambda: Settings(bot_token=""))


class Bots:
    """A bot factory that records which token each Bot was built for."""

    def __init__(self) -> None:
        self.built: list[str | None] = []
        self.sessions: dict[str, RecordingSession] = {}

    def __call__(self, token: str | None) -> Bot:
        self.built.append(token)
        real = token if token is not None else TEST_TOKEN
        session = self.sessions.setdefault(real, RecordingSession())
        return Bot(token=real, session=session)

    def calls(self, token: str) -> list[Any]:
        return self.sessions[token].calls if token in self.sessions else []


def credential(
    shop_id: int, token: str | None = None, *, legacy: bool = False
) -> ShopBotCredential:
    return ShopBotCredential(
        shop_id=shop_id,
        token_encrypted=encrypt_token(token) if token is not None else None,
        uses_process_bot_token=legacy,
    )


def registry(*credentials: ShopBotCredential, bots: Bots) -> BotRegistry:
    return BotRegistry(
        token_for=stored_tokens({c.shop_id: c for c in credentials}), bot_factory=bots
    )


def no_secret_in(text_: str) -> None:
    for secret in SECRETS:
        assert secret not in text_


# --- the resolution rule ---------------------------------------------------


async def test_a_shop_s_own_stored_token_builds_its_bot(key: str) -> None:
    bots = Bots()
    reg = registry(credential(1, TOKEN_A), credential(2, TOKEN_B), bots=bots)
    try:
        assert reg.bot_for(1).token == TOKEN_A
        assert reg.bot_for(2).token == TOKEN_B
        assert bots.built == [TOKEN_A, TOKEN_B]
    finally:
        await reg.close()


async def test_the_legacy_shop_falls_back_to_bot_token_and_says_so(
    key: str, process_token: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    bots = Bots()
    reg = registry(credential(5, legacy=True), bots=bots)
    try:
        reg.bot_for(5)
        reg.bot_for(5)
        reg.bot_for(5)
    finally:
        await reg.close()

    assert bots.built == [None], "None is the process BOT_TOKEN, via the real factory seam"
    fallbacks = [r for r in caplog.records if "fallback" in r.getMessage()]
    assert len(fallbacks) == 1, "once per registry, not once per row"
    assert fallbacks[0].levelno == logging.WARNING
    assert "shop 5" in fallbacks[0].getMessage()
    assert "BOT_TOKEN" in fallbacks[0].getMessage()
    no_secret_in(caplog.text)


async def test_the_legacy_shop_uses_its_own_token_once_it_has_one(
    key: str, process_token: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    bots = Bots()
    reg = registry(credential(5, TOKEN_A, legacy=True), bots=bots)
    try:
        assert reg.bot_for(5).token == TOKEN_A
    finally:
        await reg.close()
    assert bots.built == [TOKEN_A]
    assert "fallback" not in caplog.text


# --- item 4: no token, no fallback -> loud and clear -------------------------


async def test_a_shop_with_no_token_and_no_fallback_is_refused_clearly(key: str) -> None:
    bots = Bots()
    reg = registry(credential(7), bots=bots)
    with pytest.raises(ShopBotUnavailable) as refused:
        reg.bot_for(7)
    await reg.close()

    message = str(refused.value)
    assert refused.value.shop_id == 7
    assert "shop 7" in message
    assert "bot_token_encrypted" in message, "the message must say what to set"
    assert bots.built == [], "no Bot is built for a shop with nothing to build it from"
    assert isinstance(refused.value, LookupError)


async def test_the_legacy_shop_is_refused_clearly_when_bot_token_is_gone(
    key: str, no_process_token: None
) -> None:
    """The day BOT_TOKEN is dropped: the legacy shop, still without a token of
    its own, must say exactly that rather than build a Bot from an empty
    string and fail somewhere inside aiogram."""
    bots = Bots()
    reg = registry(credential(5, legacy=True), bots=bots)
    with pytest.raises(ShopBotUnavailable) as refused:
        reg.bot_for(5)
    await reg.close()
    assert "BOT_TOKEN" in str(refused.value)
    assert "shop 5" in str(refused.value)
    assert bots.built == []


async def test_a_shop_that_was_never_loaded_is_refused_clearly(key: str) -> None:
    reg = registry(credential(1, TOKEN_A), bots=Bots())
    with pytest.raises(ShopBotUnavailable, match="shop 99"):
        reg.bot_for(99)
    await reg.close()


async def test_an_unreadable_stored_token_is_refused_without_secrets(
    key: str, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored = credential(3, TOKEN_A)
    other = settings.model_copy(
        update={"shop_token_encryption_key": SecretStr(Fernet.generate_key().decode())}
    )
    monkeypatch.setattr(shop_tokens_module, "get_settings", lambda: other)

    reg = registry(stored, bots=Bots())
    with pytest.raises(ShopBotUnavailable) as refused:
        reg.bot_for(3)
    await reg.close()
    assert "shop 3" in str(refused.value)
    assert stored.token_encrypted is not None
    assert stored.token_encrypted not in str(refused.value)
    no_secret_in(str(refused.value))


async def test_a_stored_token_aiogram_rejects_becomes_a_clear_refusal(key: str) -> None:
    """Only reachable by writing ciphertext around `encrypt_token`'s own
    validation -- but if it happens, aiogram's TokenValidationError must not
    escape a tick as a bare crash."""
    fernet = Fernet(shop_tokens_module.get_settings().shop_token_encryption_key.get_secret_value())
    smuggled = ShopBotCredential(
        shop_id=4,
        token_encrypted=fernet.encrypt(b"not a token").decode(),
        uses_process_bot_token=False,
    )
    reg = BotRegistry(token_for=stored_tokens({4: smuggled}), bot_factory=factory_module.build_bot)
    with pytest.raises(ShopBotUnavailable, match="shop 4"):
        reg.bot_for(4)
    await reg.close()


# The bot process's own choice of bot is covered in tests/test_shop_pollers.py:
# it polls every shop, by this same resolution rule.


# --- item 4, inside a real tick: one shop down, the other still served --------


@pytest_asyncio.fixture
async def one_shop_without_a_bot(db: AsyncConnection, key: str) -> dict[str, Any]:
    """Shop A has its own token; shop B has none and is not the legacy shop.
    Each has a group, a customer, an order due to be announced and a reminder
    due to be sent."""
    due = datetime.now(UTC) - timedelta(seconds=1)
    out: dict[str, Any] = {"db": db, "shop": {}, "order": {}, "customer": {}}
    for label, group, tg in (("A", -1_001_111, 8_101), ("B", -1_002_222, 8_102)):
        shop = (
            await db.execute(
                text(
                    "INSERT INTO shops (name, working_hours, group_chat_id) "
                    "VALUES (:n, CAST(:wh AS jsonb), :g) RETURNING id"
                ),
                {"n": f"Shop {label}", "wh": json.dumps(DEFAULT_WORKING_HOURS), "g": group},
            )
        ).scalar_one()
        customer = (
            await db.execute(
                text(
                    "INSERT INTO customers (shop_id, telegram_user_id, phone, phone_verified) "
                    "VALUES (:s, :t, '+998901234567', true) RETURNING id"
                ),
                {"s": shop, "t": tg},
            )
        ).scalar_one()
        order = (
            await db.execute(
                text(
                    "INSERT INTO orders (shop_id, customer_id, product_name_snapshot, "
                    " price_uzs_snapshot, telegram_file_id_snapshot, delivery_date, "
                    " delivery_hour, delivery_location_text, landmark, status, submit_token) "
                    "VALUES (:s, :c, 'Guldasta', 450000, 'file', CURRENT_DATE + 1, '14:00', "
                    " 'Chilonzor', 'eshik', 'placed', 't') RETURNING id"
                ),
                {"s": shop, "c": customer},
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
                    "VALUES (:s, :c, 'Onam', 'mother') RETURNING id"
                ),
                {"s": shop, "c": customer},
            )
        ).scalar_one()
        occasion = (
            await db.execute(
                text(
                    "INSERT INTO occasions (shop_id, customer_id, recipient_id, type, kind, "
                    " label, month, day) "
                    "VALUES (:s, :c, :r, 'mother', 'birthday', 'Onam', 3, 8) RETURNING id"
                ),
                {"s": shop, "c": customer, "r": recipient},
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
        out["shop"][label], out["order"][label], out["customer"][label] = shop, order, customer

    async with bound_session_factory(db)() as session:
        await set_shop_bot_token(session, shop_id=out["shop"]["A"], token=TOKEN_A)
        await session.commit()
    return out


def _one_clear_error(caplog: pytest.LogCaptureFixture, shop: int) -> logging.LogRecord:
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1, [r.getMessage() for r in errors]
    record = errors[0]
    message = record.getMessage()
    assert f"shop {shop}" in message
    assert "bot_token_encrypted" in message
    assert record.exc_info is None, "a clear sentence, not a stack trace"
    no_secret_in(caplog.text)
    return record


@pytest.mark.infra
async def test_order_pings_a_shop_without_a_bot_fails_loudly_and_the_other_is_served(
    one_shop_without_a_bot: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    world = one_shop_without_a_bot
    caplog.set_level(logging.INFO)
    bots = Bots()
    async with bound_session_factory(world["db"])() as session:
        reg = await registry_for(session, bot_factory=bots)
        try:
            result = await run_order_ping_tick(
                session,
                transport_for=lambda shop_id: TelegramTransport(reg.bot_for(shop_id)),
                now_utc=datetime.now(UTC),
            )
        finally:
            await reg.close()

    assert (result.sent, result.failed, result.undeliverable) == (1, 1, 1)
    assert [c.chat_id for c in bots.calls(TOKEN_A)] == [-1_001_111]
    record = _one_clear_error(caplog, world["shop"]["B"])
    assert f"ORDER {world['order']['B']}" in record.getMessage()

    state = (
        await world["db"].execute(
            text("SELECT state FROM order_reminders WHERE order_id = :o"),
            {"o": world["order"]["B"]},
        )
    ).scalar_one()
    assert state == "failed", "retried next tick, and parked after the attempt cap"


@pytest.mark.infra
async def test_reminders_a_shop_without_a_bot_fails_loudly_and_the_other_is_served(
    one_shop_without_a_bot: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    world = one_shop_without_a_bot
    caplog.set_level(logging.INFO)
    bots = Bots()
    async with bound_session_factory(world["db"])() as session:
        reg = await registry_for(session, bot_factory=bots)
        try:
            result = await run_tick(
                session,
                transport_for=lambda shop_id: TelegramTransport(reg.bot_for(shop_id)),
                render=render_reminder,
                now_utc=datetime.now(UTC),
            )
        finally:
            await reg.close()

    assert (result.sent, result.failed) == (1, 1)
    assert result.errors == ["no_bot_token"]
    assert [c.chat_id for c in bots.calls(TOKEN_A)] == [8_101]
    _one_clear_error(caplog, world["shop"]["B"])

    # The ordinary generic-failure path: marked failed, deferred, claim
    # released -- so it retries, and parks after MAX_SEND_ATTEMPTS.
    state, due = (
        await world["db"].execute(
            text("SELECT state, due_at_utc FROM scheduled_notifications WHERE customer_id = :c"),
            {"c": world["customer"]["B"]},
        )
    ).one()
    assert state == "failed"
    assert due > datetime.now(UTC)
