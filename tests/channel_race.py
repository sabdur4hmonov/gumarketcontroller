"""Feed a slice of one album through a real dispatcher, as a standalone process.

Run as `python tests/channel_race.py <shop_id> <marker> <payload.json>`. Prints
one JSON line:

    {"pid": ..., "marker": ..., "fed": N, "scheduled": [...]}

Deliberately a separate FILE and a separate PROCESS, for the same reason as
tests/worker_race.py: two coroutines in one process share a connection pool and
an event loop, so they cannot contend for a Postgres row the way two workers
do. Only real processes exercise the ON CONFLICT path this checkpoint rests on.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from tests.bot_harness import channel_post_update, make_bot  # noqa: E402

from gulbot.bot.factory import build_dispatcher  # noqa: E402
from gulbot.config import get_settings  # noqa: E402

#: Long enough that the two processes interleave rather than each finishing
#: before the other has opened a connection.
GAP_SECONDS = 0.05


async def main(shop_id: int, marker: str, payload: list[dict]) -> None:

    settings = get_settings()
    engine = create_async_engine(
        settings.database_url(database=settings.postgres_test_db), future=True
    )
    # Real sessions committing to a real database. No savepoint harness here:
    # the whole point is that the other process can see these writes.
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    scheduled: list[str] = []

    async def recorder(*, shop_id: int, media_group_id: str) -> None:
        scheduled.append(media_group_id)

    bot, _ = make_bot()
    dispatcher = build_dispatcher(
        session_factory=sessions, shop_id=shop_id, schedule_finalize=recorder
    )

    try:
        for index, item in enumerate(payload):
            await dispatcher.feed_update(bot, channel_post_update(update_id=index + 1, **item))
            await asyncio.sleep(GAP_SECONDS)
    finally:
        await engine.dispose()

    print(
        json.dumps(
            {"pid": os.getpid(), "marker": marker, "fed": len(payload), "scheduled": scheduled}
        )
    )


if __name__ == "__main__":
    # Argument parsing and the file read happen OUTSIDE the loop: blocking I/O
    # at startup is not the same thing as blocking I/O during the race.
    asyncio.run(
        main(
            int(sys.argv[1]),
            sys.argv[2],
            json.loads(Path(sys.argv[3]).read_text(encoding="utf-8")),
        )
    )
