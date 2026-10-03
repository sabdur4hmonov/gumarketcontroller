"""C4 of AUDIT_MULTI_TENANT.md: `scripts/verify_group.py` rewires ONE shop.

It used to run `UPDATE shops SET group_chat_id = %s` with no WHERE clause.
Harmless with one shop; against a fleet database, one run would point every
shop's order cards, health alerts and daily summaries at a single group, with
no record of where they used to go.

Now the shop is named on the command line, the run refuses to start without it
-- before Telegram or the database is touched -- and an id that matches no shop
is an error rather than a quiet zero-row update.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import psycopg
import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from gulbot.config import Settings
from gulbot.models.shop import DEFAULT_WORKING_HOURS

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_group.py"


@pytest.fixture(scope="module")
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_group_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TouchedTelegram(Exception):
    """Raised if the script gets as far as building a bot."""


def test_a_run_without_a_shop_id_stops_before_telegram_or_the_database(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The hard failure, at the real entry point. Not a silent no-op, and not a
    failure that happens only after a message was already posted to a group."""

    async def no_bot(shop_id: int) -> None:
        # The first thing after parsing: it reads the shop's token, then builds
        # the shop's bot. Reached at all means the refusal came too late.
        raise TouchedTelegram

    def no_database(*args: object, **kwargs: object) -> None:
        raise AssertionError("the database was opened without a shop id")

    monkeypatch.setattr(script, "shop_bots", no_bot)
    monkeypatch.setattr(script.psycopg, "connect", no_database)
    monkeypatch.setattr("sys.argv", ["verify_group.py", "--chat-id", "-1001234"])

    with pytest.raises(SystemExit) as stopped:
        asyncio.run(script.main())

    assert stopped.value.code == 2
    assert "--shop-id" in capsys.readouterr().err


def test_the_shop_id_is_required_even_for_a_dry_run(script: ModuleType) -> None:
    with pytest.raises(SystemExit) as stopped:
        script.build_parser().parse_args(["--dry-run"])
    assert stopped.value.code == 2


def test_a_named_shop_parses(script: ModuleType) -> None:
    args = script.build_parser().parse_args(["--shop-id", "7", "--chat-id", "-100"])
    assert (args.shop_id, args.chat_id) == (7, -100)


# --- the UPDATE itself, against the real test database ---------------------


@pytest.fixture
def conn(settings: Settings) -> Iterator[psycopg.Connection]:
    """A transaction on the test database that is always rolled back."""
    dsn = (
        f"host={settings.postgres_host} port={settings.postgres_port} "
        f"user={settings.postgres_user} "
        f"password={settings.postgres_password.get_secret_value()} "
        f"dbname={settings.postgres_test_db}"
    )
    with psycopg.connect(dsn) as connection:
        try:
            yield connection
        finally:
            connection.rollback()


def _shop(conn: psycopg.Connection, name: str, group: int) -> int:
    row = conn.execute(
        "INSERT INTO shops (name, working_hours, group_chat_id) "
        "VALUES (%s, CAST(%s AS jsonb), %s) RETURNING id",
        (name, json.dumps(DEFAULT_WORKING_HOURS), group),
    ).fetchone()
    assert row is not None
    return int(row[0])


def _groups(conn: psycopg.Connection, *shops: int) -> dict[int, int]:
    rows = conn.execute(
        "SELECT id, group_chat_id FROM shops WHERE id = ANY(%s)", (list(shops),)
    ).fetchall()
    return {int(shop): int(group) for shop, group in rows}


@pytest.mark.infra
def test_only_the_named_shop_is_rewired(script: ModuleType, conn: psycopg.Connection) -> None:
    a, b = _shop(conn, "A", -1_000_001), _shop(conn, "B", -1_000_002)

    name = script.wire_group(conn, shop_id=a, chat_id=-1_009_999)

    assert name == "A"
    assert _groups(conn, a, b) == {a: -1_009_999, b: -1_000_002}


@pytest.mark.infra
def test_an_unknown_shop_id_fails_loudly_and_writes_nothing(
    script: ModuleType, conn: psycopg.Connection
) -> None:
    a, b = _shop(conn, "A", -1_000_001), _shop(conn, "B", -1_000_002)
    missing = max(a, b) + 1_000

    with pytest.raises(LookupError, match=str(missing)):
        script.wire_group(conn, shop_id=missing, chat_id=-1_009_999)

    assert _groups(conn, a, b) == {a: -1_000_001, b: -1_000_002}


# --- it verifies with the SHOP'S OWN bot -----------------------------------


@pytest.fixture
def on_the_test_db(
    db: AsyncConnection, script: ModuleType, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> AsyncConnection:
    from contextlib import asynccontextmanager

    from cryptography.fernet import Fernet
    from pydantic import SecretStr
    from tests.bot_harness import bound_session_factory

    import gulbot.services.shop_tokens as shop_tokens_module

    moved = settings.model_copy(
        update={"shop_token_encryption_key": SecretStr(Fernet.generate_key().decode())}
    )
    monkeypatch.setattr(shop_tokens_module, "get_settings", lambda: moved)

    @asynccontextmanager
    async def on_the_test_connection():  # type: ignore[no-untyped-def]
        yield bound_session_factory(db)

    monkeypatch.setattr(script, "task_session_factory", on_the_test_connection)
    return db


async def _async_shop(db: AsyncConnection) -> int:
    from sqlalchemy import text

    return int(
        (
            await db.execute(
                text(
                    "INSERT INTO shops (name, working_hours) "
                    "VALUES ('S', CAST(:wh AS jsonb)) RETURNING id"
                ),
                {"wh": json.dumps(DEFAULT_WORKING_HOURS)},
            )
        ).scalar_one()
    )


@pytest.mark.infra
async def test_the_group_is_checked_with_the_shop_s_own_bot(
    script: ModuleType, on_the_test_db: AsyncConnection
) -> None:
    from tests.bot_harness import bound_session_factory

    from gulbot.services.shop_tokens import set_shop_bot_token

    token = "111111:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    shop = await _async_shop(on_the_test_db)
    async with bound_session_factory(on_the_test_db)() as session:
        await set_shop_bot_token(session, shop_id=shop, token=token)
        await session.commit()

    registry = await script.shop_bots(shop)
    try:
        assert registry.bot_for(shop).token == token
    finally:
        await registry.close()


@pytest.mark.infra
async def test_a_shop_without_a_bot_is_not_verified_and_nothing_is_sent(
    script: ModuleType,
    on_the_test_db: AsyncConnection,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    shop = await _async_shop(on_the_test_db)
    monkeypatch.setattr("sys.argv", ["verify_group.py", "--shop-id", str(shop), "--dry-run"])

    assert await script.main() == 3
    out = capsys.readouterr().out
    assert f"NOT VERIFIED: shop {shop} has no usable bot" in out
    assert "POSTED" not in out and "bot: @" not in out
