"""Per-shop bot tokens, encrypted at rest.

A shop's bot token is the whole of its Telegram identity: whoever holds it can
read that shop's customers' messages and speak as the shop. So the database
holds only Fernet ciphertext, the key lives in SHOP_TOKEN_ENCRYPTION_KEY and
nowhere else, and no error message, log line or repr may carry the token, the
ciphertext or the key.

The marker token's secret half is what every leak assertion searches for: the
numeric half is the bot's public id and is fine to print.
"""

from __future__ import annotations

import json
import logging
import socket

import pytest
from aiogram import Bot
from aiogram.client.telegram import TelegramAPIServer
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import bound_session_factory

import gulbot.services.shop_tokens as shop_tokens_module
from gulbot.config import Settings
from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.sending.telegram import TelegramTransport
from gulbot.services.shop_tokens import (
    EncryptionKeyInvalid,
    EncryptionKeyMissing,
    InvalidBotToken,
    ShopBotCredential,
    TokenUndecryptable,
    decrypt_token,
    encrypt_token,
    load_bot_credentials,
    set_shop_bot_token,
)

TOKEN = "123456789:MARKERmarkerMARKERmarkerMARKERmarkerXX"
SECRET = TOKEN.split(":", 1)[1]


def use_keys(monkeypatch: pytest.MonkeyPatch, settings: Settings, *keys: str) -> None:
    moved = settings.model_copy(update={"shop_token_encryption_key": SecretStr(",".join(keys))})
    monkeypatch.setattr(shop_tokens_module, "get_settings", lambda: moved)


@pytest.fixture
def key(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> str:
    fresh = Fernet.generate_key().decode()
    use_keys(monkeypatch, settings, fresh)
    return fresh


# --- the cipher ------------------------------------------------------------


def test_a_token_round_trips(key: str) -> None:
    assert decrypt_token(encrypt_token(TOKEN)) == TOKEN


def test_the_stored_form_reveals_nothing(key: str) -> None:
    stored = encrypt_token(TOKEN)
    assert SECRET not in stored
    assert "123456789" not in stored
    # Fernet's version byte, base64'd. The column's CHECK relies on it.
    assert stored.startswith("gAAAAA")


def test_the_same_token_encrypts_differently_each_time(key: str) -> None:
    assert encrypt_token(TOKEN) != encrypt_token(TOKEN)


def test_no_key_fails_loudly_and_names_the_variable(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_keys(monkeypatch, settings, "")
    for attempt in (lambda: encrypt_token(TOKEN), lambda: decrypt_token("gAAAAAxyz")):
        with pytest.raises(EncryptionKeyMissing) as missing:
            attempt()
        assert "SHOP_TOKEN_ENCRYPTION_KEY" in str(missing.value)
        assert SECRET not in str(missing.value)


def test_a_malformed_key_is_refused_without_echoing_it(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad_key = "this-is-not-a-fernet-key-SEKRIT-7f3a"
    use_keys(monkeypatch, settings, bad_key)
    with pytest.raises(EncryptionKeyInvalid) as refused:
        encrypt_token(TOKEN)
    assert bad_key not in str(refused.value)
    assert "SEKRIT" not in str(refused.value)


def test_the_wrong_key_cannot_read_a_token_and_says_so_without_secrets(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    use_keys(monkeypatch, settings, first)
    stored = encrypt_token(TOKEN)

    use_keys(monkeypatch, settings, second)
    with pytest.raises(TokenUndecryptable) as unreadable:
        decrypt_token(stored)

    message = str(unreadable.value)
    assert "SHOP_TOKEN_ENCRYPTION_KEY" in message
    for secret in (SECRET, stored, first, second):
        assert secret not in message
    # Nothing chained underneath to print either.
    assert unreadable.value.__cause__ is None
    assert unreadable.value.__suppress_context__


def test_a_rotated_key_still_reads_tokens_stored_under_the_old_one(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    use_keys(monkeypatch, settings, old)
    stored_under_old = encrypt_token(TOKEN)

    use_keys(monkeypatch, settings, new, old)  # new first: it encrypts
    assert decrypt_token(stored_under_old) == TOKEN
    stored_under_new = encrypt_token(TOKEN)

    use_keys(monkeypatch, settings, new)
    assert decrypt_token(stored_under_new) == TOKEN


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "no-colon-at-all-MARKERmarkerMARKERmarker",
        "abc:MARKERmarkerMARKERmarkerMARKERmarkerXX",
        "123456789:short",
        "123456789:MARKER markerMARKERmarkerMARKERmarkerXX",
        "123456789:MARKERmarkerMARKERmarker/MARKERmarkerXX",
    ],
)
def test_a_malformed_token_is_refused_before_it_is_stored(key: str, bad: str) -> None:
    with pytest.raises(InvalidBotToken) as refused:
        encrypt_token(bad)
    if bad:
        assert bad not in str(refused.value)
        assert "MARKER" not in str(refused.value)


def test_a_credential_never_prints_its_ciphertext(key: str) -> None:
    stored = encrypt_token(TOKEN)
    credential = ShopBotCredential(shop_id=1, token_encrypted=stored, uses_process_bot_token=False)
    assert stored not in repr(credential)
    assert stored not in str(credential)


def test_settings_never_render_the_encryption_key() -> None:
    marker_key = Fernet.generate_key().decode()
    settings = Settings(shop_token_encryption_key=marker_key)
    for how, rendered in {
        "repr": repr(settings),
        "str": str(settings),
        "model_dump": str(settings.model_dump()),
        "f-string": f"{settings.shop_token_encryption_key}",
    }.items():
        assert marker_key not in rendered, f"the encryption key shows in {how}"


# --- the logs these tests read must actually be on -------------------------


@pytest.mark.infra
def test_running_migrations_does_not_silence_the_application_logs(settings: Settings) -> None:
    """Found while writing the leak test below: `migrations/env.py` called
    `fileConfig()` with its default `disable_existing_loggers=True`, and the
    test session runs Alembic -- so every gulbot logger already imported was
    switched off for the rest of the suite. A "no secret in the logs" check
    then passes because there ARE no logs. It would also silence the app's own
    loggers in any process that ran migrations in-process."""
    from alembic import command
    from tests.conftest import alembic_config_for

    watched = logging.getLogger("gulbot.sending.telegram")
    with alembic_config_for(settings.postgres_test_db) as cfg:
        command.upgrade(cfg, "head")  # already at head: only env.py runs
    assert watched.disabled is False


# --- a real Bot built from a decrypted token leaks nothing when it fails -----


async def test_a_failing_send_with_a_decrypted_token_logs_no_secret(
    key: str, caplog: pytest.LogCaptureFixture
) -> None:
    """The exception handlers around a real Bot, at the point a stored token is
    finally used. The request URL is https://.../bot<TOKEN>/sendMessage, so any
    handler that logged an exception's full text could print the token."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    bot = Bot(token=decrypt_token(encrypt_token(TOKEN)))
    bot.session.api = TelegramAPIServer.from_base(f"http://127.0.0.1:{port}")
    bot.session.timeout = 2
    caplog.set_level(logging.DEBUG)
    try:
        outcome = await TelegramTransport(bot).send_text(chat_id=1, text="x")
    finally:
        await bot.session.close()

    assert outcome.ok is False
    assert SECRET not in (outcome.error_code or "")
    assert caplog.records, "the failure must still be logged"
    assert SECRET not in caplog.text


# --- storage ---------------------------------------------------------------


async def _shop(db: AsyncConnection, name: str, *, legacy: bool = False) -> int:
    return int(
        (
            await db.execute(
                text(
                    "INSERT INTO shops (name, working_hours, uses_process_bot_token) "
                    "VALUES (:n, CAST(:wh AS jsonb), :legacy) RETURNING id"
                ),
                {"n": name, "wh": json.dumps(DEFAULT_WORKING_HOURS), "legacy": legacy},
            )
        ).scalar_one()
    )


async def _stored(db: AsyncConnection, shop: int) -> str | None:
    return (
        await db.execute(text("SELECT bot_token_encrypted FROM shops WHERE id = :s"), {"s": shop})
    ).scalar_one()


@pytest.mark.infra
async def test_setting_a_token_stores_only_ciphertext(db: AsyncConnection, key: str) -> None:
    shop = await _shop(db, "A")
    async with bound_session_factory(db)() as session:
        await set_shop_bot_token(session, shop_id=shop, token=TOKEN)
        await session.commit()

    stored = await _stored(db, shop)
    assert stored is not None
    assert SECRET not in stored
    assert decrypt_token(stored) == TOKEN


@pytest.mark.infra
async def test_setting_a_token_for_an_unknown_shop_fails_and_says_which(
    db: AsyncConnection, key: str
) -> None:
    missing = await _shop(db, "A") + 10_000
    async with bound_session_factory(db)() as session:
        with pytest.raises(LookupError) as unknown:
            await set_shop_bot_token(session, shop_id=missing, token=TOKEN)
    assert str(missing) in str(unknown.value)
    assert SECRET not in str(unknown.value)


@pytest.mark.infra
async def test_postgres_refuses_a_plaintext_token_in_the_column(db: AsyncConnection) -> None:
    """The last line of defence: somebody pasting a token into psql. A Fernet
    token cannot start with digits-and-a-colon, so the CHECK can tell."""
    shop = await _shop(db, "A")
    with pytest.raises(IntegrityError) as refused:
        async with db.begin_nested():
            await db.execute(
                text("UPDATE shops SET bot_token_encrypted = :t WHERE id = :s"),
                {"t": TOKEN, "s": shop},
            )
    assert "ck_shops_bot_token_is_ciphertext" in str(refused.value)


@pytest.mark.infra
async def test_credentials_are_loaded_per_shop(db: AsyncConnection, key: str) -> None:
    own, legacy, bare = (
        await _shop(db, "own"),
        await _shop(db, "legacy", legacy=True),
        await _shop(db, "bare"),
    )
    async with bound_session_factory(db)() as session:
        await set_shop_bot_token(session, shop_id=own, token=TOKEN)
        await session.commit()
        loaded = await load_bot_credentials(session, shop_ids=[own, legacy, bare])
        only_one = await load_bot_credentials(session, shop_ids=[legacy])

    assert set(loaded) == {own, legacy, bare}
    assert loaded[own].token_encrypted == await _stored(db, own)
    assert loaded[own].uses_process_bot_token is False
    assert (loaded[legacy].token_encrypted, loaded[legacy].uses_process_bot_token) == (None, True)
    assert (loaded[bare].token_encrypted, loaded[bare].uses_process_bot_token) == (None, False)
    assert set(only_one) == {legacy}
