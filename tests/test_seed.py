"""The dev seed must be safe to run twice."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from gulbot.models.shop import DEFAULT_REMINDER_OFFSETS


@pytest.mark.infra
async def test_shop_defaults_come_from_the_database(db: AsyncConnection, shop_id: int) -> None:
    """A row inserted with only name+working_hours still gets full config.

    Defaults live in the schema, not in Python, so a shop created by hand in
    psql is as valid as one created by the seed command.
    """
    row = (
        await db.execute(
            text(
                "SELECT reminder_offsets, reminder_weekly_cap, reminder_merge_window_days, "
                "same_day_cutoff, min_lead_time_minutes, daily_order_cap, "
                "peak_pending_threshold, peak_hourly_threshold, peak_manual_override, "
                "timezone, owner_telegram_ids "
                "FROM shops WHERE id = :i"
            ),
            {"i": shop_id},
        )
    ).one()

    assert list(row.reminder_offsets) == DEFAULT_REMINDER_OFFSETS == [-7, -1, 0]
    assert row.reminder_weekly_cap == 4
    assert row.reminder_merge_window_days == 2
    assert row.same_day_cutoff.strftime("%H:%M") == "18:00"
    assert row.min_lead_time_minutes == 180
    assert row.daily_order_cap is None  # uncapped until the shop sets one
    assert row.peak_pending_threshold == 15
    assert row.peak_hourly_threshold == 40
    assert row.peak_manual_override is False
    assert row.timezone == "Asia/Tashkent"
    assert list(row.owner_telegram_ids) == []
