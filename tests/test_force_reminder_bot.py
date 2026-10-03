"""`force_reminder` sends as the customer's shop's own bot.

An operator tool, but it sends a REAL reminder to a real customer -- and it
used to build the one global bot, the C1 defect in miniature. It now resolves
the bot the way the workers do.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from aiogram import Bot
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import TEST_TOKEN, RecordingSession, bound_session_factory

import gulbot.bot.factory as factory_module
import gulbot.cli.force_reminder as force_reminder
import gulbot.services.shop_tokens as shop_tokens_module
from gulbot.config import Settings
from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.services.shop_tokens import set_shop_bot_token

pytestmark = pytest.mark.infra

TOKEN = "111111:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


@pytest.fixture
def wired(
    db: AsyncConnection, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    """The CLI pointed at the test's rolled-back connection, with every Bot it
    builds recording instead of calling Telegram."""
    key = Fernet.generate_key().decode()
    moved = settings.model_copy(update={"shop_token_encryption_key": SecretStr(key)})
    monkeypatch.setattr(shop_tokens_module, "get_settings", lambda: moved)

    @asynccontextmanager
    async def on_the_test_connection() -> AsyncIterator[Any]:
        yield bound_session_factory(db)

    sessions: dict[str, RecordingSession] = {}

    def build_bot(token: str | None = None) -> Bot:
        real = token if token is not None else TEST_TOKEN
        return Bot(token=real, session=sessions.setdefault(real, RecordingSession()))

    monkeypatch.setattr(force_reminder, "task_session_factory", on_the_test_connection)
    monkeypatch.setattr(factory_module, "build_bot", build_bot)
    return {"db": db, "sessions": sessions}


async def _shop(db: AsyncConnection) -> int:
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


async def test_the_reminder_is_sent_by_the_shop_s_own_bot(wired: dict[str, Any]) -> None:
    shop = await _shop(wired["db"])
    async with bound_session_factory(wired["db"])() as session:
        await set_shop_bot_token(session, shop_id=shop, token=TOKEN)
        await session.commit()

    await force_reminder._deliver(shop, 8_001, "salom", None)

    assert set(wired["sessions"]) == {TOKEN}, "no bot but the shop's own was built"
    assert [c.chat_id for c in wired["sessions"][TOKEN].calls] == [8_001]


async def test_a_shop_without_a_bot_is_refused_clearly(
    wired: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    shop = await _shop(wired["db"])

    with pytest.raises(SystemExit) as stopped:
        await force_reminder._deliver(shop, 8_001, "salom", None)

    assert stopped.value.code == 1
    out = capsys.readouterr().out
    assert f"NOT sent: shop {shop} has no usable bot" in out
    assert wired["sessions"] == {}, "nothing was sent, and no bot was built"
