"""CP18: what the admin panel knows about each shop's bot, and about the jobs.

- Snapshots: every 10 minutes the worker asks, through each shop's OWN bot,
  whether its token works and whether it is an admin of the shop's channel
  and group -- and never posts to find out. The panel reads the latest.
- Heartbeats: every periodic task records its start, finish and outcome;
  /healthz/jobs answers 503 when the send ticks stop, from the web process,
  for an external dead-man's-switch monitor.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from aiogram.methods import GetChat, GetChatMember, GetMe, SendMessage, TelegramMethod
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import bound_session_factory
from tests.telegram_scripted import UNAUTHORIZED, Reply, chat, member, ok, scripted_bot

from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.sending.transport import ShopBotUnavailable
from gulbot.services import shop_health
from gulbot.web.app import build_app

BOT_ID = 640_001
CHANNEL, GROUP = -100_640_001, -100_640_002


def script(*, me: Reply | None = None, group_status: str = "administrator") -> Any:
    def answer(method: TelegramMethod[Any]) -> Reply:
        if isinstance(method, GetMe):
            return me or ok(
                {"id": BOT_ID, "is_bot": True, "first_name": "Lola", "username": "lola_shop_bot"}
            )
        if isinstance(method, GetChat):
            kind = "channel" if method.chat_id == CHANNEL else "supergroup"
            return ok(chat(int(method.chat_id), kind))
        if isinstance(method, GetChatMember):
            status = "administrator" if method.chat_id == CHANNEL else group_status
            return ok(member(BOT_ID, status))
        return ok(True)

    return answer


async def test_a_healthy_shops_bot_is_checked_without_a_single_post() -> None:
    bot, session = scripted_bot(f"{BOT_ID}:{'A' * 35}", script())
    snap = await shop_health.check_shop(bot, shop_id=1, channel_id=CHANNEL, group_chat_id=GROUP)
    assert (snap.token_valid, snap.channel_ok, snap.group_ok) == (True, True, True)
    assert snap.bot_username == "lola_shop_bot"
    assert not any(isinstance(call, SendMessage) for call in session.calls), session.names()


async def test_a_rejected_token_is_reported_and_nothing_else_is_asked() -> None:
    bot, session = scripted_bot(f"{BOT_ID}:{'A' * 35}", script(me=UNAUTHORIZED))
    snap = await shop_health.check_shop(bot, shop_id=1, channel_id=CHANNEL, group_chat_id=GROUP)
    assert snap.token_valid is False
    assert (snap.channel_ok, snap.group_ok) == (None, None)
    assert session.names() == ["GetMe"]


async def test_a_bot_that_lost_its_group_admin_rights_is_reported() -> None:
    bot, _ = scripted_bot(f"{BOT_ID}:{'A' * 35}", script(group_status="member"))
    snap = await shop_health.check_shop(bot, shop_id=1, channel_id=CHANNEL, group_chat_id=GROUP)
    assert (snap.token_valid, snap.channel_ok, snap.group_ok) == (True, True, False)
    assert snap.detail == {"group": "not_admin"}


@pytest.mark.infra
async def test_every_shop_gets_a_snapshot_and_a_week_old_one_is_pruned(
    db: AsyncConnection,
) -> None:
    ids = []
    for name, channel in (("Healthy", CHANNEL), ("No bot", None)):
        ids.append(
            (
                await db.execute(
                    text(
                        "INSERT INTO shops (name, working_hours, channel_id, group_chat_id) "
                        "VALUES (:n, CAST(:wh AS jsonb), :c, :g) RETURNING id"
                    ),
                    {"n": name, "wh": json.dumps(DEFAULT_WORKING_HOURS), "c": channel, "g": GROUP},
                )
            ).scalar_one()
        )
    healthy, botless = ids
    await db.execute(
        text(
            "INSERT INTO shop_health_snapshots (shop_id, checked_at, token_valid) "
            "VALUES (:s, now() - interval '8 days', true)"
        ),
        {"s": healthy},
    )
    bot, _ = scripted_bot(f"{BOT_ID}:{'A' * 35}", script())

    def bot_for(shop_id: int) -> Any:
        if shop_id == healthy:
            return bot
        raise ShopBotUnavailable(shop_id, "no bot is registered for it")

    async with bound_session_factory(db)() as session:
        await shop_health.snapshot_all_shops(session, bot_for)
        await session.commit()
    rows = {
        r.shop_id: (r.token_valid, r.channel_ok, r.group_ok)
        for r in (
            await db.execute(
                text(
                    "SELECT shop_id, token_valid, channel_ok, group_ok FROM shop_health_snapshots "
                    "WHERE shop_id IN (:a, :b)"
                ),
                {"a": healthy, "b": botless},
            )
        ).all()
    }
    assert rows == {healthy: (True, True, True), botless: (None, None, None)}
    kept = await db.scalar(
        text("SELECT count(*) FROM shop_health_snapshots WHERE shop_id = :s"), {"s": healthy}
    )
    assert kept == 1, "the week-old snapshot was not pruned"


# --- heartbeats ----------------------------------------------------------------------


def test_a_task_records_its_start_finish_and_outcome(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[dict[str, Any]] = []

    async def record(**values: Any) -> None:
        recorded.append(values)

    monkeypatch.setattr(shop_health, "_record_with_own_engine", record)

    @shop_health.heartbeat("demo")
    def works() -> int:
        return 7

    @shop_health.heartbeat("demo")
    def breaks() -> int:
        raise RuntimeError("boom")

    assert works() == 7
    assert [(r["ok"], r["finished_at"] is not None) for r in recorded] == [
        (None, False),
        (True, True),
    ]
    recorded.clear()
    with pytest.raises(RuntimeError):
        breaks()
    assert [(r["ok"], r.get("error")) for r in recorded] == [(None, None), (False, "RuntimeError")]


def test_a_heartbeat_that_cannot_be_written_never_breaks_the_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def unreachable(**values: Any) -> None:
        raise OSError("database down")

    monkeypatch.setattr(shop_health, "_record_with_own_engine", unreachable)

    @shop_health.heartbeat("demo")
    def works() -> str:
        return "sent"

    try:
        outcome: object = works()
    except Exception as error:  # noqa: BLE001 - an escaping error is the failure
        outcome = error
    assert outcome == "sent", repr(outcome)


def test_every_periodic_task_beats() -> None:
    """Structural: a beat-scheduled task without a heartbeat would be a job
    whose death nothing notices -- the gap the dead-man's switch is for."""
    import gulbot.worker.tasks  # noqa: F401 - registers the tasks
    from gulbot.worker.app import app

    scheduled = {entry["task"] for entry in app.conf.beat_schedule.values()}
    unbeaten = sorted(name for name in scheduled if not hasattr(app.tasks[name].run, "__wrapped__"))
    assert scheduled and not unbeaten, unbeaten


@pytest.mark.infra
async def test_healthz_jobs_answers_503_naming_the_stopped_jobs(db: AsyncConnection) -> None:
    now = datetime.now(UTC)
    for name in shop_health.LIVENESS_JOBS:
        finished = now - timedelta(hours=1) if name == "send_order_pings" else now
        await db.execute(
            text(
                "INSERT INTO job_runs (name, last_finished_at, last_ok) VALUES (:n, :f, true) "
                "ON CONFLICT (name) DO UPDATE SET last_finished_at = EXCLUDED.last_finished_at"
            ),
            {"n": name, "f": finished},
        )
    app = build_app(
        session_factory=bound_session_factory(db),
        notify=lambda page_id, delay: None,
        public_base_url="http://pages.test",
    )
    async with TestClient(TestServer(app)) as client:
        stale = await client.get("/healthz/jobs")
        assert (stale.status, await stale.text()) == (503, "stale: send_order_pings")
        await db.execute(
            text("UPDATE job_runs SET last_finished_at = now() WHERE name = 'send_order_pings'")
        )
        fresh = await client.get("/healthz/jobs")
        assert (fresh.status, await fresh.text()) == (200, "ok")
