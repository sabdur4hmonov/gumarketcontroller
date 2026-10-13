"""Batch runtime snapshots; no socket/client cached across loops or tasks."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.models.runtime import ShopRuntimeState


async def store_states(session: AsyncSession, states: dict[int, dict[str, Any]]) -> None:
    if not states:
        return
    now = datetime.now(UTC)
    statement = insert(ShopRuntimeState).values(
        [{"shop_id": shop, "updated_at": now, "state": state} for shop, state in states.items()]
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[ShopRuntimeState.shop_id],
            set_={"updated_at": statement.excluded.updated_at, "state": statement.excluded.state},
        )
    )
