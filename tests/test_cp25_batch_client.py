"""Candidate only: no worker wiring before actual25-shop attribution."""

import asyncio
from types import SimpleNamespace


def test_batch_has_one_client_different_tokens_and_separate_task_loops():
    from gulbot.bot import batch_client

    sessions, bots, loops = [], [], []

    class Session:
        def __init__(self):
            self.loop = asyncio.get_running_loop()
            self.closed = 0
            sessions.append(self)

        async def close(self):
            assert self.loop is asyncio.get_running_loop()
            self.closed += 1

    def bot(token, session):
        made = SimpleNamespace(token=token, session=session)
        bots.append(made)
        return made

    async def task():
        loops.append(asyncio.get_running_loop())
        async with batch_client.task_bot_batch(
            token_for={1: "one", 2: "two", 3: "one"}.__getitem__,
            session_factory=Session,
            bot_factory=bot,
        ) as batch:
            first, second = batch.bot_for(1), batch.bot_for(2)
            assert first.token == "one" and second.token == "two"
            assert first.session is second.session
            assert batch.bot_for(3) is first
        rejected = False
        try:
            batch.bot_for(1)
        except RuntimeError:
            rejected = True
        assert rejected, "Closed task clients may never be reused"
        await batch.close()

    asyncio.run(task())
    asyncio.run(task())
    assert len(sessions) == 2 and sessions[0] is not sessions[1]
    assert len(bots) == 4 and bots[0] is not bots[2]
    assert all(session.closed == 1 for session in sessions)
    assert loops[0] is not loops[1] and all(loop.is_closed() for loop in loops)


async def test_batch_closes_client_on_exception_and_keeps_request_policy(monkeypatch):
    from gulbot.bot import batch_client

    closed, registered, configured = [], [], []
    session = SimpleNamespace(timeout=15, middleware=SimpleNamespace(register=registered.append))

    async def close():
        closed.append(True)

    session.close = close

    def make_session(**kwargs):
        configured.append(kwargs)
        return session

    monkeypatch.setattr(batch_client, "AiohttpSession", make_session)
    caught = False
    try:
        async with batch_client.task_bot_batch(
            token_for=lambda shop: f"{shop}:" + "T" * 35
        ) as batch:
            one, two = batch.bot_for(1), batch.bot_for(2)
            assert one.session is two.session
            assert one.default.parse_mode == "HTML" and one.id != two.id
            raise ValueError("consumer failed")
    except ValueError:
        caught = True
    assert caught and closed == [True]
    assert len(registered) == 1 and registered[0].__class__.__name__ == "ReplyPolicy"
    assert configured == [{"timeout": 15}]


async def test_open_batch_rejects_another_loop():
    from gulbot.bot.batch_client import task_bot_batch

    class Session:
        async def close(self):
            pass

    async with task_bot_batch(
        token_for=lambda shop: "one",
        session_factory=Session,
        bot_factory=lambda token, session: SimpleNamespace(token=token, session=session),
    ) as batch:
        batch.bot_for(1)

        async def other_loop():
            rejected = False
            try:
                batch.bot_for(1)
            except RuntimeError:
                rejected = True
            assert rejected, "Even an open batch must reject another event loop"
            close_rejected = False
            try:
                await batch.close()
            except RuntimeError:
                close_rejected = True
            assert close_rejected, "The owner loop alone may close an open batch"

        await asyncio.to_thread(lambda: asyncio.run(other_loop()))
