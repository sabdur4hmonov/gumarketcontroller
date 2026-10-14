"""Production worker wiring: real HTTP in separate task loops."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from aiogram.client.telegram import TelegramAPIServer
from tests.telegram_stub import FakeTelegram

from gulbot.bot import batch_client
from gulbot.bot.registry import BotRegistry
from gulbot.worker import tasks


@pytest.mark.parametrize("kind", ["reminder", "order"])
@pytest.mark.parametrize("failure", [False, True])
def test_worker_reuses_one_http_client_inside_each_real_task_loop(monkeypatch, kind, failure):
    assert hasattr(tasks, "_worker_registry"), (
        "Worker batches still create one HTTP client per token"
    )
    sessions, connections, loops, closures = [], [], [], []

    async def commit():
        pass

    @asynccontextmanager
    async def session():
        yield SimpleNamespace(commit=commit)

    @asynccontextmanager
    async def database():
        yield session

    async def registry(_session):
        return BotRegistry(token_for={1: "600001:" + "T" * 35, 2: "600002:" + "U" * 35}.__getitem__)

    async def tick(_session, *, transport_for, **kwargs):
        first, second = transport_for(1), transport_for(2)
        assert first._bot.id != second._bot.id
        assert first._bot.session is second._bot.session, "Each batch needs ONE shared HTTP session"
        loops.append(asyncio.get_running_loop())
        for transport, chat in ((first, 111), (second, 222)):
            assert (await transport.send_text(chat_id=chat, text="batch loop proof")).ok
        connections.append(first._bot.session._session)
        if failure:
            raise RuntimeError("consumer failed after real sends")
        return SimpleNamespace(
            groups=2,
            claimed=2,
            sent=2,
            expired=0,
            failed=0,
            cancelled=0,
            handed_back=0,
            dead_lettered=0,
            undeliverable=0,
        )

    real_session = batch_client.batch_session
    with FakeTelegram() as api:

        def make_session():
            made = real_session()
            made.api = TelegramAPIServer.from_base(api.base_url)
            real_close = made.close

            async def close():
                # SDK create_session resets its unopened connector by calling
                # close(); count only closes after a real client was opened.
                if made._session is not None:
                    closures.append(made)
                await real_close()

            made.close = close
            sessions.append(made)
            return made

        monkeypatch.setattr(batch_client, "batch_session", make_session)
        monkeypatch.setattr(tasks, "task_session_factory", database)
        monkeypatch.setattr(tasks, "registry_for", registry)
        monkeypatch.setattr(tasks, "run_tick", tick)
        from gulbot.sending import order_pings

        monkeypatch.setattr(order_pings, "run_order_ping_tick", tick)
        work = tasks._send_due_reminders if kind == "reminder" else tasks._send_order_pings
        for _ in range(2):
            if failure:
                with pytest.raises(RuntimeError, match="consumer failed"):
                    asyncio.run(work())
            else:
                asyncio.run(work())
        assert api.calls == ["sendMessage"] * 4, "Both loops must perform real HTTP sends"

    assert len(sessions) == 2 and sessions[0] is not sessions[1]
    assert closures == sessions, "Close each task-owned client exactly once"
    assert len(connections) == 2 and all(c.closed for c in connections)
    assert connections[0] is not connections[1]
    assert loops[0] is not loops[1] and all(loop.is_closed() for loop in loops)


def test_batch_preserves_injected_and_legacy_factory_seams(monkeypatch):
    from gulbot.bot import factory

    def resolver(shop):
        return "600001:" + "T" * 35

    custom = BotRegistry(token_for=resolver, bot_factory=lambda token: SimpleNamespace())
    assert custom.task_batch_tokens() is None
    normal = BotRegistry(token_for=resolver)
    assert normal.task_batch_tokens() is resolver
    monkeypatch.setattr(factory, "build_bot", lambda: SimpleNamespace())
    assert normal.task_batch_tokens() is None, "Keep the legacy zero-argument factory seam"
