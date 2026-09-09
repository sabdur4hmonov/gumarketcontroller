"""One tick, run as a standalone process. Used by the concurrency test.

Run as `python tests/worker_race.py <shop_id> <marker>`. Prints one JSON line:

    {"pid": ..., "sent": ..., "skipped_claimed": ..., "calls": [...]}

Deliberately a separate FILE and a separate PROCESS. Two threads in one process
share a connection pool and a GIL; a solo-pool worker in ONE process cannot race
with itself at all. Only real processes exercise real Postgres locking, which is
what this is meant to prove.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from gulbot.config import get_settings  # noqa: E402
from gulbot.sending.dispatcher import run_tick  # noqa: E402
from gulbot.sending.render import render_reminder  # noqa: E402
from gulbot.sending.transport import SendResult  # noqa: E402


class RecordingTransport:
    """Records what this process actually sent."""

    def __init__(self, marker: str) -> None:
        self.marker = marker
        self.calls: list[int] = []

    async def send_text(
        self, *, chat_id: int, text: str, reply_markup: object = None
    ) -> SendResult:
        self.calls.append(chat_id)
        # A real network call takes time; without this both processes would
        # finish before either could observe the other.
        await asyncio.sleep(0.4)
        return SendResult.sent(len(self.calls))


async def main() -> None:
    # argv[1] is the shop id. The tick is global by design -- it picks up every
    # due row -- so the worker does not filter by it; the test isolates by
    # cleaning the table instead.
    marker = sys.argv[2]
    now = datetime.fromisoformat(sys.argv[3])

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    settings = get_settings()
    engine = create_async_engine(
        settings.database_url(database=settings.postgres_test_db), future=True
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)

    transport = RecordingTransport(marker)
    try:
        async with factory() as session:
            result = await run_tick(
                session,
                transport=transport,
                render=render_reminder,
                now_utc=now,
            )
            await session.commit()
    finally:
        await engine.dispose()

    print(
        json.dumps(
            {
                "pid": os.getpid(),
                "marker": marker,
                "sent": result.sent,
                "skipped_claimed": result.skipped_claimed,
                "groups": result.groups,
                "calls": transport.calls,
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
