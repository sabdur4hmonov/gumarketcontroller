"""One album, two real worker PROCESSES, shuffled delivery.

This is the case the whole design exists for. Five photos of one album arrive
split across two workers, out of order, at the same moment; the caption is on a
message neither worker sees first. The requirement is unchanged by any of that:
ONE product, the right caption, the right anchor photo.

Two real PROCESSES, not two tasks and not two threads -- the same standard as
CP6's send race, and for the same reason. Two coroutines in one process share a
connection pool and an event loop, so they take turns instead of contending;
such a test passes without proving anything. The PID assertion is there so it
cannot silently degrade into that.

Committed data only: the child processes have their own connections and cannot
see the test transaction, so the fixture writes and commits, then cleans up.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from tests.bot_harness import CHANNEL_ID

from gulbot.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKER = REPO_ROOT / "tests" / "channel_race.py"

SHOP_NAME = "channel-race-probe"
ALBUM = "race-media-group"
CAPTION = "Oq atirgul 101 ta\nNarxi 1 200 000 so'm\n#atirgul #katta"

#: Message 201 carries the caption and is the anchor. Neither worker is given
#: it first, and the worker that has it is given it LAST.
WORKER_A = [204, 202, 205]
WORKER_B = [203, 201]

_PURGE_ORDER = ("product_hashtags", "products")


def _purge(conn: psycopg.Connection) -> None:
    shops = [
        row[0]
        for row in conn.execute("SELECT id FROM shops WHERE name = %s", (SHOP_NAME,)).fetchall()
    ]
    if not shops:
        return
    for table in _PURGE_ORDER:
        conn.execute(f"DELETE FROM {table} WHERE shop_id = ANY(%s)", (shops,))
    conn.execute("DELETE FROM shops WHERE id = ANY(%s)", (shops,))


@pytest.fixture
def committed_shop(settings: Settings, tmp_path: Path) -> Iterator[dict]:
    dsn = (
        f"host={settings.postgres_host} port={settings.postgres_port} "
        f"user={settings.postgres_user} password={settings.postgres_password.get_secret_value()} "
        f"dbname={settings.postgres_test_db}"
    )
    with psycopg.connect(dsn, autocommit=True) as conn:
        _purge(conn)
        # Connected to the channel the posts come from: since H3 a shop
        # indexes only its own channel_id.
        shop = conn.execute(
            "INSERT INTO shops (name, working_hours, channel_id) "
            "VALUES (%s, '{}'::jsonb, %s) RETURNING id",
            (SHOP_NAME, CHANNEL_ID),
        ).fetchone()[0]
        try:
            yield {"conn": conn, "shop": shop, "tmp": tmp_path}
        finally:
            _purge(conn)


def payload_for(message_ids: list[int]) -> list[dict]:
    return [
        {
            "message_id": message_id,
            "file_id": f"file{message_id}",
            "media_group_id": ALBUM,
            "caption": CAPTION if message_id == 201 else None,
        }
        for message_id in message_ids
    ]


async def run_two_workers(world: dict) -> list[dict]:
    """Start both processes at the same moment."""

    async def one(marker: str, message_ids: list[int]) -> dict:
        payload_path = world["tmp"] / f"payload-{marker}.json"
        payload_path.write_text(json.dumps(payload_for(message_ids)), encoding="utf-8")
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(WORKER),
            str(world["shop"]),
            marker,
            str(payload_path),
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        out, err = await process.communicate()
        if process.returncode != 0:
            raise AssertionError(f"worker {marker} failed: {err.decode(errors='replace')}")
        return json.loads(out.decode().strip().splitlines()[-1])

    return list(await asyncio.gather(one("A", WORKER_A), one("B", WORKER_B)))


def products(world: dict) -> list[tuple]:
    return (
        world["conn"]
        .execute(
            "SELECT id, caption_raw, channel_message_id, telegram_file_id, finalized_at "
            "FROM products WHERE shop_id = %s ORDER BY id",
            (world["shop"],),
        )
        .fetchall()
    )


@pytest.mark.infra
async def test_a_shuffled_album_across_two_processes_makes_one_product(
    committed_shop: dict,
) -> None:
    results = await run_two_workers(committed_shop)

    pids = {r["pid"] for r in results}
    assert len(pids) == 2, f"the race ran in one process, proving nothing: {pids}"
    assert sum(r["fed"] for r in results) == 5

    rows = products(committed_shop)
    assert len(rows) == 1, f"five concurrent arrivals made {len(rows)} products"

    _, caption, anchor_message, anchor_file, finalized_at = rows[0]
    assert caption == CAPTION, "the caption was lost in the race"
    assert anchor_message == 201, "the anchor is not the earliest message"
    assert anchor_file == "file201", "the anchor photo does not match the anchor message"
    assert finalized_at is None, "nothing has run finalize yet; the row is provisional"


@pytest.mark.infra
async def test_the_racing_album_finalizes_to_one_correct_product(committed_shop: dict) -> None:
    """And then settles exactly once, whichever worker's arrival triggered it."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from gulbot.config import get_settings
    from gulbot.services.indexer import Finalize, finalize_product

    await run_two_workers(committed_shop)

    settings = get_settings()
    engine = create_async_engine(
        settings.database_url(database=settings.postgres_test_db), future=True
    )
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            first = await finalize_product(
                session, shop_id=committed_shop["shop"], media_group_id=ALBUM
            )
            await session.commit()
        async with sessions() as session:
            second = await finalize_product(
                session, shop_id=committed_shop["shop"], media_group_id=ALBUM
            )
            await session.commit()
    finally:
        await engine.dispose()

    assert first.outcome is Finalize.FINALIZED
    assert first.hashtags == ("atirgul", "katta")
    assert first.price_uzs == 1_200_000
    assert second.outcome is Finalize.NOOP

    tags = (
        committed_shop["conn"]
        .execute(
            "SELECT count(*) FROM product_hashtags WHERE shop_id = %s", (committed_shop["shop"],)
        )
        .fetchone()[0]
    )
    assert tags == 2, "finalize ran twice and duplicated the tags"
