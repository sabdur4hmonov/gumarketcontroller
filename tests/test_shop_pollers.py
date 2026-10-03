"""The bot process polls EVERY shop's bot, each through its own dispatcher.

Replaces `resolve_single_shop`, which refused to start with more than one shop
-- so the first completed owner onboarding would have stopped the pilot's bot
from ever restarting. Now each shop with a usable bot (its own stored token, or
the pilot's logged BOT_TOKEN fallback) gets a dispatcher bound to that shop and
a long-poll of its own; a shop created while the process runs is picked up
without a restart; and a shop that cannot be served is reported, not fatal.

Why a dispatcher PER SHOP and not one dispatcher polling many bots: every
customer-facing handler is written against the shop the dispatcher was built
for (`CustomerMiddleware(shop_id)`), and that binding is what the tenancy of
every customer, order and date rests on. One dispatcher per shop keeps it
exactly as it was.
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import GetMe, GetUpdates, SendMessage
from aiogram.types import Chat, Message, User
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import TEST_TOKEN, bound_session_factory, text_update
from tests.telegram_scripted import Reply, ScriptedSession, ok, sent_message

import gulbot.bot.factory as factory_module
import gulbot.services.shop_tokens as shop_tokens_module
from gulbot.bot.run import ShopPollers, poll_forever, require_something_to_serve
from gulbot.config import Settings
from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.services.shop_tokens import set_shop_bot_token

pytestmark = pytest.mark.infra

TOKEN_A = "111111:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
TOKEN_B = "222222:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"


def _me(bot_id: int) -> dict[str, Any]:
    return {"id": bot_id, "is_bot": True, "first_name": "bot", "username": f"bot{bot_id}"}


class Bots:
    """Builds bots that answer getMe, and getUpdates with nothing."""

    def __init__(self) -> None:
        self.built: list[str | None] = []

    def __call__(self, token: str | None) -> Bot:
        self.built.append(token)
        real = token if token is not None else TEST_TOKEN
        bot_id = int(real.split(":")[0])

        def script(method: Any) -> Reply:
            if isinstance(method, GetMe):
                return ok(_me(bot_id))
            if isinstance(method, GetUpdates):
                return ok([])
            if isinstance(method, SendMessage):
                return ok(sent_message(method.chat_id))  # type: ignore[arg-type]
            raise AssertionError(type(method).__name__)

        return Bot(token=real, session=ScriptedSession(script))


class Polls:
    """Stands in for the long poll: records who is polled, runs until cancelled."""

    def __init__(self) -> None:
        self.started: list[tuple[Dispatcher, Bot]] = []

    async def __call__(self, dispatcher: Dispatcher, bot: Bot) -> None:
        self.started.append((dispatcher, bot))
        await asyncio.Event().wait()


@pytest.fixture
def key(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> str:
    fresh = Fernet.generate_key().decode()
    moved = settings.model_copy(update={"shop_token_encryption_key": SecretStr(fresh)})
    monkeypatch.setattr(shop_tokens_module, "get_settings", lambda: moved)
    return fresh


@pytest.fixture
def process_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory_module, "get_settings", lambda: Settings(bot_token=TEST_TOKEN))


async def _shop(
    db: AsyncConnection, name: str, *, token: str | None = None, legacy: bool = False
) -> int:
    shop = int(
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
    if token is not None:
        async with bound_session_factory(db)() as session:
            await set_shop_bot_token(session, shop_id=shop, token=token)
            await session.commit()
    return shop


@pytest_asyncio.fixture
async def pollers(db: AsyncConnection, key: str, process_token: None) -> Any:
    polls, bots = Polls(), Bots()
    subject = ShopPollers(
        bound_session_factory(db), storage=MemoryStorage(), bot_factory=bots, poll=polls
    )
    try:
        yield subject, polls, bots
    finally:
        await subject.stop()


async def test_every_shop_with_a_bot_is_polled_through_its_own_bot(
    db: AsyncConnection, pollers: Any
) -> None:
    subject, polls, bots = pollers
    a, b = await _shop(db, "A", token=TOKEN_A), await _shop(db, "B", token=TOKEN_B)

    started = await subject.sync()
    await asyncio.sleep(0)

    assert sorted(started) == sorted([a, b])
    assert {bot.token for _, bot in polls.started} == {TOKEN_A, TOKEN_B}
    assert subject.running[a].bot.token == TOKEN_A
    assert subject.running[b].bot.token == TOKEN_B


async def test_each_dispatcher_is_bound_to_its_own_shop(db: AsyncConnection, pollers: Any) -> None:
    """A customer who writes to shop B's bot becomes shop B's customer."""
    subject, _, _ = pollers
    a, b = await _shop(db, "A", token=TOKEN_A), await _shop(db, "B", token=TOKEN_B)
    await subject.sync()

    served = subject.running[b]
    await served.dispatcher.feed_update(served.bot, text_update("/start", user_id=880_101))

    shops = (
        (await db.execute(text("SELECT shop_id FROM customers WHERE telegram_user_id = 880101")))
        .scalars()
        .all()
    )
    assert shops == [b]
    assert a != b


async def test_the_pilot_shop_is_still_polled_through_bot_token(
    db: AsyncConnection, pollers: Any
) -> None:
    """What keeps today's deployment running."""
    subject, _, bots = pollers
    pilot = await _shop(db, "Pilot", legacy=True)
    await subject.sync()
    assert subject.running[pilot].bot.token == TEST_TOKEN
    assert bots.built == [None], "built through the process-token path, logged as fallback"


async def test_a_shop_that_cannot_be_served_is_reported_and_the_rest_are_polled(
    db: AsyncConnection, pollers: Any, caplog: pytest.LogCaptureFixture
) -> None:
    subject, _, _ = pollers
    good = await _shop(db, "Good", token=TOKEN_A)
    bare = await _shop(db, "Bare")

    assert await subject.sync() == [good]

    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1 and f"shop {bare}" in errors[0]
    assert bare not in subject.running


async def test_a_shop_created_while_running_is_picked_up_without_a_restart(
    db: AsyncConnection, pollers: Any
) -> None:
    subject, _, _ = pollers
    a = await _shop(db, "A", token=TOKEN_A)
    await subject.sync()
    first = subject.running[a]

    b = await _shop(db, "B", token=TOKEN_B)
    assert await subject.sync() == [b]

    assert subject.running[a] is first, "the running shop was not restarted"
    assert set(subject.running) == {a, b}


async def test_a_poller_that_died_is_restarted_on_the_next_sync(
    db: AsyncConnection, pollers: Any
) -> None:
    subject, _, _ = pollers
    a = await _shop(db, "A", token=TOKEN_A)
    await subject.sync()
    dead = subject.running[a]
    dead.task.cancel()
    await asyncio.sleep(0)

    assert await subject.sync() == [a]
    assert subject.running[a] is not dead


async def test_two_shops_on_one_bot_are_never_both_polled(
    db: AsyncConnection, pollers: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """Two long-polls of one bot make Telegram answer 409 to both. Reachable
    only through the pilot: its BOT_TOKEN bot is not in the unique column."""
    subject, _, _ = pollers
    pilot = await _shop(db, "Pilot", legacy=True)
    copy = await _shop(db, "Copy", token=TEST_TOKEN)

    await subject.sync()

    assert list(subject.running) == [pilot]
    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1 and f"shop {copy}" in errors[0]


def test_nothing_to_serve_refuses_to_start_cleanly() -> None:
    with pytest.raises(SystemExit) as stopped:
        require_something_to_serve(shops=0, platform=False)
    assert str(stopped.value.code).startswith("REFUSING TO START: ")
    assert stopped.value.__cause__ is None


def test_either_a_shop_or_the_platform_is_enough_to_start() -> None:
    require_something_to_serve(shops=1, platform=False)
    require_something_to_serve(shops=0, platform=True)


async def test_the_real_long_poll_delivers_to_the_right_shop(
    db: AsyncConnection, key: str, process_token: None
) -> None:
    """Once, end to end through aiogram's own start_polling: an update arriving
    on shop B's bot is handled by shop B's dispatcher."""
    b = await _shop(db, "B", token=TOKEN_B)
    delivered = asyncio.Event()
    handed_out = False

    def factory(token: str | None) -> Bot:
        def script(method: Any) -> Reply:
            nonlocal handed_out
            if isinstance(method, GetMe):
                return ok(_me(222222))
            if isinstance(method, GetUpdates):
                if handed_out:
                    delivered.set()
                    return ok([])
                handed_out = True
                update = text_update("/start", user_id=880_202, update_id=1)
                return ok([json.loads(update.model_dump_json(exclude_none=True))])
            if not isinstance(method, SendMessage):
                return ok(True)
            return ok(
                json.loads(
                    Message(
                        message_id=1,
                        date=datetime.now(tz=UTC),
                        chat=Chat(id=880_202, type="private"),
                        from_user=User(id=222222, is_bot=True, first_name="b"),
                        text="ok",
                    ).model_dump_json(exclude_none=True)
                )
            )

        return Bot(token=token or TEST_TOKEN, session=ScriptedSession(script))

    # Updates handled inline rather than as tasks, so that the SECOND getUpdates
    # proves the first update was handled completely, commit included.
    subject = ShopPollers(
        bound_session_factory(db),
        storage=MemoryStorage(),
        bot_factory=factory,
        poll=functools.partial(poll_forever, handle_as_tasks=False),
    )
    try:
        await subject.sync()
        await asyncio.wait_for(delivered.wait(), timeout=10)
    finally:
        await subject.stop()

    shops = (
        (await db.execute(text("SELECT shop_id FROM customers WHERE telegram_user_id = 880202")))
        .scalars()
        .all()
    )
    assert shops == [b]


# --- the platform bot's own start --------------------------------------------

PLATFORM_TOKEN = "999999:PPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPPP"


def _with_platform(monkeypatch: pytest.MonkeyPatch, settings: Settings, token: str) -> None:
    import gulbot.bot.run as run_module

    moved = settings.model_copy(update={"platform_bot_token": SecretStr(token)})
    monkeypatch.setattr(run_module, "get_settings", lambda: moved)


async def test_the_platform_is_off_without_its_token(
    db: AsyncConnection, settings: Settings, monkeypatch: pytest.MonkeyPatch, pollers: Any
) -> None:
    from gulbot.bot.run import start_platform

    subject, polls, bots = pollers
    _with_platform(monkeypatch, settings, "")
    assert (
        await start_platform(
            bound_session_factory(db), storage=MemoryStorage(), pollers=subject, poll=polls
        )
        is None
    )


async def test_the_platform_refuses_to_start_without_the_encryption_key(
    db: AsyncConnection, settings: Settings, monkeypatch: pytest.MonkeyPatch, pollers: Any
) -> None:
    from gulbot.bot.run import start_platform

    subject, polls, bots = pollers
    _with_platform(monkeypatch, settings, PLATFORM_TOKEN)
    no_key = settings.model_copy(update={"shop_token_encryption_key": SecretStr("")})
    monkeypatch.setattr(shop_tokens_module, "get_settings", lambda: no_key)

    with pytest.raises(SystemExit) as stopped:
        await start_platform(
            bound_session_factory(db), storage=MemoryStorage(), pollers=subject, poll=polls
        )
    message = str(stopped.value.code)
    assert message.startswith("REFUSING TO START: ") and "SHOP_TOKEN_ENCRYPTION_KEY" in message
    assert PLATFORM_TOKEN.split(":")[1] not in message


async def test_the_platform_refuses_a_bot_that_already_serves_a_shop(
    db: AsyncConnection, settings: Settings, monkeypatch: pytest.MonkeyPatch, pollers: Any
) -> None:
    from gulbot.bot.run import start_platform

    subject, polls, bots = pollers
    shop = await _shop(db, "A", token=TOKEN_A)
    await subject.sync()
    _with_platform(monkeypatch, settings, TOKEN_A)

    with pytest.raises(SystemExit, match=f"shop {shop}'s bot"):
        await start_platform(
            bound_session_factory(db),
            storage=MemoryStorage(),
            pollers=subject,
            bot_factory=bots,
            poll=polls,
        )


async def test_the_platform_polls_its_own_bot(
    db: AsyncConnection, settings: Settings, monkeypatch: pytest.MonkeyPatch, pollers: Any
) -> None:
    from gulbot.bot.run import start_platform

    subject, polls, bots = pollers
    _with_platform(monkeypatch, settings, PLATFORM_TOKEN)
    platform = await start_platform(
        bound_session_factory(db),
        storage=MemoryStorage(),
        pollers=subject,
        bot_factory=bots,
        poll=polls,
    )
    assert platform is not None
    try:
        await asyncio.sleep(0)
        assert [bot.token for _, bot in polls.started] == [PLATFORM_TOKEN]
    finally:
        await platform.stop()


def test_settings_never_render_the_platform_token() -> None:
    settings = Settings(platform_bot_token=PLATFORM_TOKEN)
    secret = PLATFORM_TOKEN.split(":")[1]
    for rendered in (repr(settings), str(settings), str(settings.model_dump())):
        assert secret not in rendered
