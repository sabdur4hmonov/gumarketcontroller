"""Two real worker PROCESSES racing the same due rows.

Not two threads, and not one process. A solo-pool worker in a single process
cannot race by construction, so a test built that way would pass without
proving anything -- which is exactly what the CP0 README warns about. These
tests assert the two PIDs differ, so the test cannot silently degrade into the
vacuous version.

Committed data only: these processes have their own connections and cannot see
the test transaction, so the fixture writes and commits to the test database,
then cleans up afterwards.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest

from gulbot.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKER = REPO_ROOT / "tests" / "worker_race.py"

NOW = datetime(2027, 3, 8, 6, 0, tzinfo=UTC)
SHOP_NAME = "race-probe"

#: Child-first. customers -> shops is ON DELETE RESTRICT by design (CP1), so a
#: bare DELETE FROM shops is refused rather than cascading.
_PURGE_ORDER = (
    "message_log",
    "scheduled_notifications",
    "consent_events",
    "occasions",
    "recipients",
    "customers",
)


def _purge(conn: psycopg.Connection) -> None:
    """Remove everything this test owns, committed, in dependency order."""
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
def committed_world(settings: Settings) -> Iterator[dict]:
    """A shop with due rows, COMMITTED so other processes can see it."""
    dsn = (
        f"host={settings.postgres_host} port={settings.postgres_port} "
        f"user={settings.postgres_user} password={settings.postgres_password} "
        f"dbname={settings.postgres_test_db}"
    )
    with psycopg.connect(dsn, autocommit=True) as conn:
        _purge(conn)
        shop = conn.execute(
            "INSERT INTO shops (name, working_hours) VALUES (%s, '{}'::jsonb) RETURNING id",
            (SHOP_NAME,),
        ).fetchone()[0]
        customer = conn.execute(
            "INSERT INTO customers (shop_id, telegram_user_id) VALUES (%s, %s) RETURNING id",
            (shop, 770001),
        ).fetchone()[0]
        recipient = conn.execute(
            "INSERT INTO recipients (shop_id, customer_id, label, type) "
            "VALUES (%s, %s, 'Onam', 'mother') RETURNING id",
            (shop, customer),
        ).fetchone()[0]
        try:
            yield {
                "dsn": dsn,
                "shop": shop,
                "customer": customer,
                "recipient": recipient,
                "conn": conn,
            }
        finally:
            _purge(conn)


def add_row(world: dict, *, day: int, offset: int, merge_key: str | None) -> int:
    conn = world["conn"]
    occasion = conn.execute(
        "INSERT INTO occasions "
        "(shop_id, customer_id, recipient_id, label, type, kind, month, day) "
        "VALUES (%s, %s, %s, 'Onam', 'mother', 'birthday', 3, %s) RETURNING id",
        (world["shop"], world["customer"], world["recipient"], day),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO scheduled_notifications "
        "(shop_id, customer_id, occasion_id, occurrence_year, offset_days, due_at_utc, "
        " channel, merge_key) "
        "VALUES (%s, %s, %s, 2027, %s, %s, 'telegram', %s)",
        (
            world["shop"],
            world["customer"],
            occasion,
            offset,
            NOW - timedelta(minutes=1),
            merge_key,
        ),
    )
    return occasion


def snapshot(world: dict) -> str:
    """Everything a failure here needs, and nothing it does not.

    Added at CP10b, after `assert len(rows) == 3` failed once in a full-suite
    run and left no way to tell a row that was never inserted from one that was
    deleted afterwards. Those have completely different causes, and the bare
    count distinguishes neither.

    Deliberately GLOBAL, not scoped to this shop: `worker_race.py` runs the real
    tick, which is global by design and picks up every due row in the database.
    A row belonging to some other test is therefore part of this test's world
    whether it wants to be or not.
    """
    conn = world["conn"]
    mine = conn.execute(
        "SELECT id, occasion_id, offset_days, merge_key, state, attempts, due_at_utc, sent_at "
        "FROM scheduled_notifications WHERE shop_id = %s ORDER BY id",
        (world["shop"],),
    ).fetchall()
    others = conn.execute(
        "SELECT s.name, n.shop_id, n.state, count(*) FROM scheduled_notifications n "
        "JOIN shops s ON s.id = n.shop_id WHERE n.shop_id <> %s GROUP BY 1, 2, 3",
        (world["shop"],),
    ).fetchall()
    log = conn.execute(
        "SELECT transition_key, status, attempts, error_code FROM message_log "
        "WHERE shop_id = %s ORDER BY id",
        (world["shop"],),
    ).fetchall()
    lines = [f"\n  shop {world['shop']} rows ({len(mine)}):"]
    lines += [f"    {row}" for row in mine]
    lines.append(f"  message_log ({len(log)}):")
    lines += [f"    {row}" for row in log]
    lines.append(f"  rows belonging to OTHER shops ({len(others)}):")
    lines += [f"    {row}" for row in others]
    return "\n".join(lines)


async def run_two_workers(shop: int) -> list[dict]:
    """Start two separate OS processes at the same moment."""

    async def one(marker: str) -> dict:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(WORKER),
            str(shop),
            marker,
            NOW.isoformat(),
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise AssertionError(f"worker {marker} failed: {err.decode(errors='replace')}")
        return json.loads(out.decode().strip().splitlines()[-1])

    return list(await asyncio.gather(one("A"), one("B")))


@pytest.mark.infra
async def test_two_processes_racing_one_row_send_exactly_once(
    committed_world: dict,
) -> None:
    add_row(committed_world, day=8, offset=0, merge_key=None)

    results = await run_two_workers(committed_world["shop"])

    pids = {r["pid"] for r in results}
    assert len(pids) == 2, f"the race ran in one process, proving nothing: {pids}"

    total_calls = sum(len(r["calls"]) for r in results)
    assert total_calls == 1, f"the message was sent {total_calls} times"
    assert sum(r["sent"] for r in results) == 1

    state, sent_at = (
        committed_world["conn"]
        .execute(
            "SELECT state, sent_at FROM scheduled_notifications WHERE shop_id = %s",
            (committed_world["shop"],),
        )
        .fetchone()
    )
    assert state == "sent"
    assert sent_at is not None


@pytest.mark.infra
async def test_two_processes_racing_a_merged_group_send_it_once_and_whole(
    committed_world: dict,
) -> None:
    for day, offset in ((8, 0), (9, -1), (10, -2)):
        add_row(committed_world, day=day, offset=offset, merge_key="race-cluster")

    # BEFORE the workers run. This is the line that separates "a row was never
    # inserted" from "a row was deleted while the tick ran" -- the two causes
    # the post-hoc count below cannot tell apart.
    planted = (
        committed_world["conn"]
        .execute(
            "SELECT count(*) FROM scheduled_notifications WHERE shop_id = %s",
            (committed_world["shop"],),
        )
        .fetchone()[0]
    )
    assert planted == 3, f"the fixture did not plant 3 rows{snapshot(committed_world)}"

    results = await run_two_workers(committed_world["shop"])

    assert len({r["pid"] for r in results}) == 2
    assert sum(len(r["calls"]) for r in results) == 1, "a merged group was sent twice"

    rows = (
        committed_world["conn"]
        .execute(
            "SELECT state, sent_at FROM scheduled_notifications WHERE shop_id = %s",
            (committed_world["shop"],),
        )
        .fetchall()
    )
    assert len(rows) == 3, f"a row vanished AFTER being planted{snapshot(committed_world)}"
    assert {r[0] for r in rows} == {"sent"}, (
        f"the group was not marked whole{snapshot(committed_world)}"
    )
    assert len({r[1] for r in rows}) == 1, (
        f"the group was marked by two different sends{snapshot(committed_world)}"
    )


@pytest.mark.infra
async def test_the_loser_records_why_it_did_nothing(committed_world: dict) -> None:
    """It skipped on the claim or on the lock -- either way, not an error."""
    add_row(committed_world, day=8, offset=0, merge_key=None)

    results = await run_two_workers(committed_world["shop"])
    winners = [r for r in results if r["sent"] == 1]
    losers = [r for r in results if r["sent"] == 0]

    assert len(winners) == 1
    assert len(losers) == 1
    loser = losers[0]
    # Either it never saw the row (SKIP LOCKED) or it saw it and lost the claim.
    assert loser["groups"] == 0 or loser["skipped_claimed"] == 1


@pytest.mark.infra
async def test_two_processes_split_disjoint_work_rather_than_blocking(
    committed_world: dict,
) -> None:
    """SKIP LOCKED means the second worker proceeds, it does not wait."""
    for day in range(1, 7):
        add_row(committed_world, day=day, offset=0, merge_key=f"solo-{day}")

    results = await run_two_workers(committed_world["shop"])

    assert len({r["pid"] for r in results}) == 2
    total = sum(len(r["calls"]) for r in results)
    assert total == 6, f"expected each message exactly once, got {total}"

    states = (
        committed_world["conn"]
        .execute(
            "SELECT state, count(*) FROM scheduled_notifications WHERE shop_id = %s GROUP BY state",
            (committed_world["shop"],),
        )
        .fetchall()
    )
    assert states == [("sent", 6)]
