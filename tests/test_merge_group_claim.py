"""A merge group is claimed as ONE unit, or not at all.

Found by the CP16 F4 gate: two workers split one `merge_key` group under SKIP
LOCKED. Worker A locked row 1, worker B skipped it and took rows 2 and 3; each
built a "group" out of what it held, one won the ledger claim and sent a
reminder covering only its own rows, and the other rows stayed pending behind
a key that was already claimed. CP6 promised that a partially-sent group is not
a state the database can hold.

The random two-worker race in test_concurrency.py only lands in that window by
luck. These tests put it there on purpose, with real processes and real row
locks:

* another process holds the group's ANCHOR (the row a worker locks first):
  the tick must send nothing of that group -- not two thirds of it;
* another process holds a NON-anchor row: the tick must wait for it and then
  send the whole group, never the rows it could get;
* and in one process, the batch LIMIT must never cut a group in two -- the
  same split, without any concurrency at all.

Each of them fails against the old row-at-a-time selection.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import bound_session_factory
from tests.test_concurrency import NOW, REPO_ROOT, WORKER, add_row, committed_world, snapshot

from gulbot.sending.dispatcher import run_tick
from gulbot.sending.render import render_reminder
from gulbot.sending.transport import SendResult

__all__ = ["committed_world"]  # the fixture, re-used

pytestmark = pytest.mark.infra

HOLDER = REPO_ROOT / "tests" / "lock_holder.py"


def plant_group(world: dict) -> list[int]:
    """Three rows of one merge group. Returns their ids, lowest (the anchor) first."""
    for day, offset in ((8, 0), (9, -1), (10, -2)):
        add_row(world, day=day, offset=offset, merge_key="race-cluster")
    rows = (
        world["conn"]
        .execute(
            "SELECT id FROM scheduled_notifications WHERE shop_id = %s ORDER BY id",
            (world["shop"],),
        )
        .fetchall()
    )
    assert len(rows) == 3, f"the fixture did not plant 3 rows{snapshot(world)}"
    return [row[0] for row in rows]


def states(world: dict) -> list[tuple[str, int]]:
    return [
        (row[0], row[1])
        for row in world["conn"]
        .execute(
            "SELECT state, attempts FROM scheduled_notifications WHERE shop_id = %s ORDER BY id",
            (world["shop"],),
        )
        .fetchall()
    ]


async def hold(row_id: int) -> asyncio.subprocess.Process:
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(HOLDER),
        str(row_id),
        cwd=str(REPO_ROOT),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert proc.stdout is not None
    line = await asyncio.wait_for(proc.stdout.readline(), timeout=60)
    assert line.strip() == b"locked", f"the holder never took the lock: {line!r}"
    return proc


async def release(proc: asyncio.subprocess.Process) -> None:
    assert proc.stdin is not None
    proc.stdin.write(b"go\n")
    await proc.stdin.drain()
    await asyncio.wait_for(proc.wait(), timeout=60)


async def blocked_on_a_row_lock(world: dict, tick: asyncio.Task[dict]) -> bool:
    """True once some backend waits on a lock; False if the tick ends first."""
    for _ in range(600):
        if tick.done():
            return False
        waiting = (
            world["conn"]
            .execute(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE wait_event_type = 'Lock' AND datname = current_database()"
            )
            .fetchone()[0]
        )
        if waiting:
            return True
        await asyncio.sleep(0.1)
    raise AssertionError("the tick neither finished nor blocked within 60 s")


async def tick_process(shop: int) -> dict:
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(WORKER),
        str(shop),
        "T",
        NOW.isoformat(),
        cwd=str(REPO_ROOT),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise AssertionError(f"the tick process failed: {err.decode(errors='replace')}")
    return json.loads(out.decode().strip().splitlines()[-1])


async def test_a_tick_sends_nothing_of_a_group_whose_anchor_another_worker_holds(
    committed_world: dict,
) -> None:
    anchor, *_ = plant_group(committed_world)
    holder = await hold(anchor)
    tick = asyncio.create_task(tick_process(committed_world["shop"]))
    try:
        waited = await blocked_on_a_row_lock(committed_world, tick)
        assert not waited, (
            "the tick blocked on the row another worker holds; a worker without the "
            f"anchor must pass the group by, not queue behind it{snapshot(committed_world)}"
        )
        result = await tick
        assert result["calls"] == [], (
            f"a partial group was sent while another worker held its anchor"
            f"{snapshot(committed_world)}"
        )
        assert states(committed_world) == [("pending", 0)] * 3, snapshot(committed_world)
    finally:
        await release(holder)
        if not tick.done():
            await asyncio.wait_for(tick, timeout=60)

    # The holder is gone: now a tick takes the group whole.
    result = await tick_process(committed_world["shop"])
    assert len(result["calls"]) == 1
    assert [s for s, _ in states(committed_world)] == ["sent"] * 3, snapshot(committed_world)


async def test_a_tick_waits_for_a_held_member_and_sends_the_group_whole(
    committed_world: dict,
) -> None:
    _, middle, _ = plant_group(committed_world)
    holder = await hold(middle)
    tick = asyncio.create_task(tick_process(committed_world["shop"]))
    try:
        # Not a fixed sleep: process start-up on Windows can outlast one, and
        # then the tick would simply arrive after the lock is gone. Wait until
        # the tick is provably blocked on the row lock -- or has finished
        # without waiting, which is the bug.
        waited = await blocked_on_a_row_lock(committed_world, tick)
        assert waited, (
            "the tick finished while a member of its group was held elsewhere -- it can "
            f"only have done that by sending part of the group{snapshot(committed_world)}"
        )
    finally:
        await release(holder)
    result = await asyncio.wait_for(tick, timeout=60)
    assert len(result["calls"]) == 1, snapshot(committed_world)
    rows = (
        committed_world["conn"]
        .execute(
            "SELECT state, sent_at FROM scheduled_notifications WHERE shop_id = %s",
            (committed_world["shop"],),
        )
        .fetchall()
    )
    assert {r[0] for r in rows} == {"sent"}, snapshot(committed_world)
    assert len({r[1] for r in rows}) == 1, "the group was marked by more than one send"


class Recorder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def send_text(
        self, *, chat_id: int, text: str, reply_markup: object = None
    ) -> SendResult:
        self.calls.append(text)
        return SendResult.sent(len(self.calls))


async def test_the_batch_limit_never_cuts_a_group_in_two(db: AsyncConnection, shop_id: int) -> None:
    """No concurrency at all: a batch of 1 must still take a 3-row group whole."""
    customer = await db.scalar(
        text("INSERT INTO customers (shop_id, telegram_user_id) VALUES (:s, 880990) RETURNING id"),
        {"s": shop_id},
    )
    recipient = await db.scalar(
        text(
            "INSERT INTO recipients (shop_id, customer_id, label, type) "
            "VALUES (:s, :c, 'Onam', 'mother') RETURNING id"
        ),
        {"s": shop_id, "c": customer},
    )
    due = datetime.now(UTC) - timedelta(minutes=1)
    for day, offset in ((8, 0), (9, -1), (10, -2)):
        occasion = await db.scalar(
            text(
                "INSERT INTO occasions (shop_id, customer_id, recipient_id, label, type, kind, "
                " month, day) VALUES (:s, :c, :r, 'Onam', 'mother', 'birthday', 3, :d) RETURNING id"
            ),
            {"s": shop_id, "c": customer, "r": recipient, "d": day},
        )
        await db.execute(
            text(
                "INSERT INTO scheduled_notifications (shop_id, customer_id, occasion_id, "
                " occurrence_year, offset_days, due_at_utc, channel, merge_key) "
                "VALUES (:s, :c, :o, 2027, :off, :due, 'telegram', 'limit-cluster')"
            ),
            {"s": shop_id, "c": customer, "o": occasion, "off": offset, "due": due},
        )
    transport = Recorder()
    async with bound_session_factory(db)() as session:
        await run_tick(
            session,
            transport=transport,
            render=render_reminder,
            now_utc=datetime.now(UTC),
            limit=1,
        )
        await session.commit()
    rows = (
        await db.execute(
            text("SELECT state FROM scheduled_notifications WHERE customer_id = :c"),
            {"c": customer},
        )
    ).all()
    assert len(transport.calls) == 1
    assert [r[0] for r in rows] == ["sent"] * 3, f"the batch limit split the group: {rows}"
