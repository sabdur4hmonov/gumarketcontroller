"""Persisted state reaches admin health/alerts and does not replace other checks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.models.runtime import ShopRuntimeState
from gulbot.models.shop import DEFAULT_WORKING_HOURS, Shop
from gulbot.services import admin_panel
from gulbot.services.runtime_state import store_states


async def test_runtime_store_is_shop_scoped_and_admin_reports_backoff(db) -> None:
    session = AsyncSession(bind=db, expire_on_commit=False)
    try:
        a = Shop(name="Runtime A", working_hours=DEFAULT_WORKING_HOURS)
        b = Shop(name="Runtime B", working_hours=DEFAULT_WORKING_HOURS)
        session.add_all([a, b])
        await session.flush()
        await store_states(
            session,
            {
                a.id: {"status": "backoff", "errors": 3, "p95_ms": 125},
                b.id: {"status": "running", "errors": 0},
            },
        )
        states = {
            r.shop_id: r.state for r in (await session.scalars(select(ShopRuntimeState))).all()
        }
        assert {a.id, b.id} <= states.keys(), "Both tenant runtime states must be persisted"
        assert states[a.id]["errors"] == 3 and states[b.id]["errors"] == 0
        rows = {r.id: r for r in await admin_panel.shops_overview(session, now=datetime.now(UTC))}
        assert rows[a.id].health == "bad" and rows[a.id].runtime["p95_ms"] == 125
        assert rows[b.id].health != "bad"
        alerts = await admin_panel.alerts(session)
        assert any(r.shop_id == a.id and r.kind == "bot" for r in alerts)
        await store_states(session, {a.id: {"status": "running", "errors": 3}})
        assert (await session.get(ShopRuntimeState, b.id)).state["errors"] == 0
        now = datetime.now(UTC)
        await session.execute(
            update(ShopRuntimeState)
            .where(ShopRuntimeState.shop_id == a.id)
            .values(updated_at=now - timedelta(seconds=121))
        )
        rows = {r.id: r for r in await admin_panel.shops_overview(session, now=now)}
        assert rows[a.id].health_reason == "poller snapshot stale"
        assert rows[b.id].health != "bad", "Fresh other tenant must retain its own health"
        assert any(
            r.shop_id == a.id and r.detail == "poller snapshot stale"
            for r in await admin_panel.alerts(session, now=now)
        )
    finally:
        await session.close()
