"""The nightly materializer: persistence, idempotency and reconciliation."""

from __future__ import annotations

import json
from datetime import UTC, datetime, time

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker
from tests.bot_harness import bound_session_factory

from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.scheduling.occurrences import TASHKENT
from gulbot.services.materializer import materialize_shop

NOW = datetime(2027, 2, 20, 3, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def sessions(db: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    return bound_session_factory(db)


@pytest_asyncio.fixture
async def world(db: AsyncConnection) -> dict:
    """A shop with one customer, ready for occasions to be added."""
    shop_id = (
        await db.execute(
            text(
                "INSERT INTO shops (name, working_hours) "
                "VALUES ('S', CAST(:wh AS jsonb)) RETURNING id"
            ),
            {"wh": json.dumps(DEFAULT_WORKING_HOURS)},
        )
    ).scalar_one()
    customer_id = (
        await db.execute(
            text(
                "INSERT INTO customers (shop_id, telegram_user_id) VALUES (:s, 5001) RETURNING id"
            ),
            {"s": shop_id},
        )
    ).scalar_one()
    return {"shop_id": shop_id, "customer_id": customer_id}


async def add_recipient(db: AsyncConnection, world: dict, label: str = "Onam") -> int:
    return int(
        (
            await db.execute(
                text(
                    "INSERT INTO recipients (shop_id, customer_id, label, type) "
                    "VALUES (:s, :c, :l, 'mother') RETURNING id"
                ),
                {"s": world["shop_id"], "c": world["customer_id"], "l": label},
            )
        ).scalar_one()
    )


async def add_occasion(
    db: AsyncConnection, world: dict, recipient_id: int, month: int, day: int
) -> int:
    return int(
        (
            await db.execute(
                text(
                    "INSERT INTO occasions "
                    "(shop_id, customer_id, recipient_id, label, type, kind, month, day) "
                    "VALUES (:s, :c, :r, 'Onam', 'mother', 'birthday', :m, :d) RETURNING id"
                ),
                {
                    "s": world["shop_id"],
                    "c": world["customer_id"],
                    "r": recipient_id,
                    "m": month,
                    "d": day,
                },
            )
        ).scalar_one()
    )


async def rows(db: AsyncConnection, world: dict) -> list[dict]:
    result = (
        await db.execute(
            text(
                "SELECT occasion_id, occurrence_year, offset_days, channel, state, "
                "due_at_utc, merge_key FROM scheduled_notifications "
                "WHERE shop_id = :s ORDER BY due_at_utc, occasion_id, offset_days"
            ),
            {"s": world["shop_id"]},
        )
    ).mappings()
    return [dict(r) for r in result]


async def run(sessions: async_sessionmaker[AsyncSession], world: dict, *, now: datetime = NOW):
    async with sessions() as session:
        result = await materialize_shop(session, shop_id=world["shop_id"], now_utc=now)
        await session.commit()
    return result


async def set_count(db: AsyncConnection, world: dict, count: int | None) -> None:
    await db.execute(
        text("UPDATE customers SET reminder_count = :n WHERE id = :c"),
        {"n": count, "c": world["customer_id"]},
    )


# --- the load-bearing constraint -------------------------------------------


@pytest.mark.infra
async def test_the_unique_constraint_is_enforced_by_postgres(
    db: AsyncConnection, world: dict
) -> None:
    """Not an application-level check. This is the whole anti-duplicate design."""
    recipient = await add_recipient(db, world)
    occasion = await add_occasion(db, world, recipient, 3, 8)

    async def insert() -> None:
        await db.execute(
            text(
                "INSERT INTO scheduled_notifications "
                "(shop_id, customer_id, occasion_id, occurrence_year, offset_days, "
                " due_at_utc, channel) "
                "VALUES (:s, :c, :o, 2027, -7, now(), 'telegram')"
            ),
            {"s": world["shop_id"], "c": world["customer_id"], "o": occasion},
        )

    await insert()
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await insert()
    assert "occasion_id_occurrence_year" in str(excinfo.value)


@pytest.mark.infra
async def test_a_notification_cannot_reference_another_shops_occasion(
    db: AsyncConnection, world: dict
) -> None:
    """The composite FK that UNIQUE(occasions.id, shop_id) exists to support."""
    recipient = await add_recipient(db, world)
    occasion = await add_occasion(db, world, recipient, 3, 8)
    other_shop = (
        await db.execute(
            text(
                "INSERT INTO shops (name, working_hours) "
                "VALUES ('Other', CAST(:wh AS jsonb)) RETURNING id"
            ),
            {"wh": json.dumps(DEFAULT_WORKING_HOURS)},
        )
    ).scalar_one()

    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await db.execute(
                text(
                    "INSERT INTO scheduled_notifications "
                    "(shop_id, customer_id, occasion_id, occurrence_year, offset_days, "
                    " due_at_utc, channel) "
                    "VALUES (:s, :c, :o, 2027, 0, now(), 'telegram')"
                ),
                {"s": other_shop, "c": world["customer_id"], "o": occasion},
            )
    assert "fk_scheduled_notifications" in str(excinfo.value)


@pytest.mark.infra
async def test_a_sent_row_must_carry_a_timestamp(db: AsyncConnection, world: dict) -> None:
    recipient = await add_recipient(db, world)
    occasion = await add_occasion(db, world, recipient, 3, 8)
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await db.execute(
                text(
                    "INSERT INTO scheduled_notifications "
                    "(shop_id, customer_id, occasion_id, occurrence_year, offset_days, "
                    " due_at_utc, channel, state) "
                    "VALUES (:s, :c, :o, 2027, 0, now(), 'telegram', 'sent')"
                ),
                {"s": world["shop_id"], "c": world["customer_id"], "o": occasion},
            )
    assert "ck_scheduled_notifications_sent_needs_timestamp" in str(excinfo.value)


# --- idempotency -----------------------------------------------------------


@pytest.mark.infra
async def test_running_three_times_produces_identical_rows(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    recipient = await add_recipient(db, world)
    await add_occasion(db, world, recipient, 3, 8)
    await add_occasion(db, world, recipient, 4, 9)

    first = await run(sessions, world)
    snapshot = await rows(db, world)
    assert snapshot, "the first run produced nothing to compare"

    second = await run(sessions, world)
    third = await run(sessions, world)

    assert await rows(db, world) == snapshot
    assert first.inserted > 0
    assert (second.inserted, third.inserted) == (0, 0), "re-inserted existing rows"
    assert (second.pruned, third.pruned) == (0, 0), "churned rows it had just written"


@pytest.mark.infra
async def test_row_count_is_stable_across_runs(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    recipient = await add_recipient(db, world)
    for month, day in ((3, 8), (3, 20), (4, 2)):
        await add_occasion(db, world, recipient, month, day)

    counts = []
    for _ in range(3):
        await run(sessions, world)
        counts.append(len(await rows(db, world)))
    assert len(set(counts)) == 1, counts


# --- the year boundary, persisted ------------------------------------------


@pytest.mark.infra
async def test_december_to_january_run_produces_no_duplicates(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """The boundary that the unique key exists to survive, with real rows."""
    recipient = await add_recipient(db, world)
    jan = await add_occasion(db, world, recipient, 1, 3)
    dec = await add_occasion(db, world, recipient, 12, 28)

    await run(sessions, world, now=datetime(2026, 12, 20, 3, tzinfo=UTC))
    after_december = await rows(db, world)
    await run(sessions, world, now=datetime(2027, 1, 2, 3, tzinfo=UTC))
    after_january = await rows(db, world)

    keys = [
        (r["occasion_id"], r["occurrence_year"], r["offset_days"], r["channel"])
        for r in after_january
    ]
    assert len(keys) == len(set(keys)), "the boundary run duplicated a row"

    # occurrence_year is the OCCASION's year on both sides of the boundary.
    jan_rows = [r for r in after_january if r["occasion_id"] == jan]
    dec_rows = [r for r in after_january if r["occasion_id"] == dec]
    assert {r["occurrence_year"] for r in jan_rows} == {2027}
    # The December occasion keeps its 2026 rows, written by the December run.
    # Its 2027 occurrence is past the January run's 45-day horizon, so no 2027
    # rows exist yet -- and the old ones are left alone rather than churned.
    assert {r["occurrence_year"] for r in dec_rows} == {2026}

    # The December-side reminder for 3 January was written in the PREVIOUS year.
    early = [r for r in after_december if r["occasion_id"] == jan and r["offset_days"] == -7]
    assert early, "no -7 row for the January occasion"
    assert early[0]["due_at_utc"].astimezone(TASHKENT).year == 2026
    assert early[0]["occurrence_year"] == 2027


@pytest.mark.infra
async def test_rows_written_in_december_are_not_rewritten_in_january(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    recipient = await add_recipient(db, world)
    await add_occasion(db, world, recipient, 1, 3)

    await run(sessions, world, now=datetime(2026, 12, 20, 3, tzinfo=UTC))
    before = {
        (r["occasion_id"], r["occurrence_year"], r["offset_days"]): r["due_at_utc"]
        for r in await rows(db, world)
    }
    second = await run(sessions, world, now=datetime(2027, 1, 1, 3, tzinfo=UTC))
    after = {
        (r["occasion_id"], r["occurrence_year"], r["offset_days"]): r["due_at_utc"]
        for r in await rows(db, world)
    }
    for key, due in before.items():
        assert after[key] == due, f"{key} moved between runs"
    assert second.pruned == 0


# --- reconciliation --------------------------------------------------------


@pytest.mark.infra
async def test_shrinking_the_offset_set_removes_pending_rows(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """3 -> 1: the -7 and -1 pending rows must go, 0 must stay put."""
    recipient = await add_recipient(db, world)
    await add_occasion(db, world, recipient, 3, 8)

    await set_count(db, world, 3)
    await run(sessions, world)
    assert sorted(r["offset_days"] for r in await rows(db, world)) == [-7, -1, 0]
    day_of_before = next(r for r in await rows(db, world) if r["offset_days"] == 0)

    await set_count(db, world, 1)
    result = await run(sessions, world)

    remaining = await rows(db, world)
    assert [r["offset_days"] for r in remaining] == [0]
    assert result.pruned_offsets == 2
    day_of_after = remaining[0]
    assert day_of_after["due_at_utc"] == day_of_before["due_at_utc"]
    assert day_of_after["occurrence_year"] == day_of_before["occurrence_year"]


@pytest.mark.infra
async def test_growing_the_offset_set_adds_rows_without_disturbing_the_rest(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    recipient = await add_recipient(db, world)
    await add_occasion(db, world, recipient, 3, 8)

    await set_count(db, world, 1)
    await run(sessions, world)
    day_of = next(r for r in await rows(db, world) if r["offset_days"] == 0)

    await set_count(db, world, 3)
    await run(sessions, world)

    remaining = await rows(db, world)
    assert sorted(r["offset_days"] for r in remaining) == [-7, -1, 0]
    assert (
        next(r for r in remaining if r["offset_days"] == 0)["due_at_utc"] == (day_of["due_at_utc"])
    )


@pytest.mark.infra
async def test_reconciliation_never_touches_a_sent_row(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """A sent row is history. Deleting it would let the bot remind twice."""
    recipient = await add_recipient(db, world)
    await add_occasion(db, world, recipient, 3, 8)

    await set_count(db, world, 3)
    await run(sessions, world)
    await db.execute(
        text(
            "UPDATE scheduled_notifications SET state = 'sent', sent_at = now() "
            "WHERE offset_days = -7"
        )
    )

    await set_count(db, world, 1)
    await run(sessions, world)

    remaining = await rows(db, world)
    states = {r["offset_days"]: r["state"] for r in remaining}
    assert states == {-7: "sent", 0: "pending"}, states


@pytest.mark.infra
@pytest.mark.parametrize("protected", ["sent", "failed", "expired"])
async def test_only_pending_rows_are_reconcilable(
    db: AsyncConnection,
    world: dict,
    sessions: async_sessionmaker[AsyncSession],
    protected: str,
) -> None:
    recipient = await add_recipient(db, world)
    await add_occasion(db, world, recipient, 3, 8)

    await set_count(db, world, 3)
    await run(sessions, world)
    sent_at = "now()" if protected == "sent" else "NULL"
    await db.execute(
        text(
            f"UPDATE scheduled_notifications SET state = :st, sent_at = {sent_at} "
            "WHERE offset_days = -1"
        ),
        {"st": protected},
    )

    await set_count(db, world, 1)
    await run(sessions, world)

    survivors = {r["offset_days"]: r["state"] for r in await rows(db, world)}
    assert survivors.get(-1) == protected, survivors
    assert -7 not in survivors


# --- deactivation preserves history ----------------------------------------


@pytest.mark.infra
async def test_deactivating_an_occasion_keeps_sent_history_and_drops_pending(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """The easy mistake: cascading history away while cleaning the schedule."""
    recipient = await add_recipient(db, world)
    occasion = await add_occasion(db, world, recipient, 3, 8)

    await set_count(db, world, 3)
    await run(sessions, world)
    await db.execute(
        text(
            "UPDATE scheduled_notifications SET state = 'sent', sent_at = now() "
            "WHERE offset_days = -7"
        )
    )

    await db.execute(text("UPDATE occasions SET active = false WHERE id = :i"), {"i": occasion})
    result = await run(sessions, world)

    survivors = await rows(db, world)
    assert [r["state"] for r in survivors] == ["sent"]
    assert survivors[0]["offset_days"] == -7
    assert result.pruned_inactive == 2


@pytest.mark.infra
async def test_deactivating_a_recipient_stops_scheduling_their_dates(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """A deactivated person takes their dates out, even if the rows look active."""
    keep = await add_recipient(db, world, label="Onam")
    drop = await add_recipient(db, world, label="Otam")
    await add_occasion(db, world, keep, 3, 8)
    await add_occasion(db, world, drop, 4, 9)

    await run(sessions, world)
    assert len({r["occasion_id"] for r in await rows(db, world)}) == 2

    await db.execute(text("UPDATE recipients SET active = false WHERE id = :i"), {"i": drop})
    await run(sessions, world)

    remaining = {r["occasion_id"] for r in await rows(db, world)}
    assert len(remaining) == 1


@pytest.mark.infra
async def test_a_deactivated_occasion_is_not_rematerialized(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    recipient = await add_recipient(db, world)
    occasion = await add_occasion(db, world, recipient, 3, 8)
    await db.execute(text("UPDATE occasions SET active = false WHERE id = :i"), {"i": occasion})

    result = await run(sessions, world)
    assert result.planned == 0
    assert await rows(db, world) == []


# --- what gets persisted ---------------------------------------------------


@pytest.mark.infra
async def test_merge_key_from_the_engine_is_persisted_verbatim(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Clustering is the engine's job; the materializer stores what it returns."""
    recipient = await add_recipient(db, world)
    await add_occasion(db, world, recipient, 3, 8)
    await add_occasion(db, world, recipient, 3, 9)

    await run(sessions, world)
    persisted = await rows(db, world)

    by_key: dict[str, set[int]] = {}
    for row in persisted:
        by_key.setdefault(row["merge_key"], set()).add(row["occasion_id"])
    assert all(key is not None for key in by_key)
    assert any(len(ids) == 2 for ids in by_key.values()), "merged rows lost their key"


@pytest.mark.infra
async def test_customer_send_time_reaches_the_persisted_due_time(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    recipient = await add_recipient(db, world)
    await add_occasion(db, world, recipient, 3, 8)
    await db.execute(
        text("UPDATE customers SET preferred_send_time = :t WHERE id = :c"),
        {"t": time(13, 0), "c": world["customer_id"]},
    )

    await run(sessions, world)
    for row in await rows(db, world):
        assert row["due_at_utc"].astimezone(TASHKENT).hour == 13


@pytest.mark.infra
async def test_shop_default_send_time_is_used_when_the_customer_has_none(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    recipient = await add_recipient(db, world)
    await add_occasion(db, world, recipient, 3, 8)
    await db.execute(
        text("UPDATE shops SET default_send_time = :t WHERE id = :s"),
        {"t": time(13, 0), "s": world["shop_id"]},
    )

    await run(sessions, world)
    for row in await rows(db, world):
        assert row["due_at_utc"].astimezone(TASHKENT).hour == 13


@pytest.mark.infra
async def test_an_0900_preference_is_delivered_at_0900(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """ "Ertalab (09:00)" is a promise to the customer, so it is kept exactly.

    The reminder window used to open at 10:00, which silently moved everyone
    who chose morning. The window now opens at 09:00; this asserts no clamping
    happens at the bound.
    """
    recipient = await add_recipient(db, world)
    await add_occasion(db, world, recipient, 3, 8)
    await db.execute(
        text("UPDATE customers SET preferred_send_time = :t WHERE id = :c"),
        {"t": time(9, 0), "c": world["customer_id"]},
    )

    await run(sessions, world)
    hours = {row["due_at_utc"].astimezone(TASHKENT).hour for row in await rows(db, world)}
    assert hours == {9}, "a 09:00 preference was clamped"


@pytest.mark.infra
async def test_a_2000_preference_is_delivered_at_2000_on_the_right_day(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """ "Kechqurun (20:00)" sits exactly on the CLOSING bound.

    It must be neither clamped inwards nor pushed into the following day.
    """
    recipient = await add_recipient(db, world)
    await add_occasion(db, world, recipient, 3, 8)
    await db.execute(
        text("UPDATE customers SET preferred_send_time = :t WHERE id = :c"),
        {"t": time(20, 0), "c": world["customer_id"]},
    )

    await run(sessions, world)
    persisted = await rows(db, world)
    assert persisted, "the 20:00 preset produced no rows at all"
    assert {r["due_at_utc"].astimezone(TASHKENT).hour for r in persisted} == {20}

    day_of = next(r for r in persisted if r["offset_days"] == 0)
    local_day = day_of["due_at_utc"].astimezone(TASHKENT)
    assert (local_day.month, local_day.day) == (3, 8), "the day-of reminder slid a day"


@pytest.mark.infra
async def test_every_persisted_row_is_inside_the_send_window(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Clamping happens at materialisation, so CP6 only has to assert it."""
    recipient = await add_recipient(db, world)
    for month, day in ((3, 8), (4, 1), (3, 25)):
        await add_occasion(db, world, recipient, month, day)

    await run(sessions, world)
    for row in await rows(db, world):
        local = row["due_at_utc"].astimezone(TASHKENT)
        assert 9 <= local.hour <= 20, local


@pytest.mark.infra
async def test_nothing_is_persisted_in_the_past(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    recipient = await add_recipient(db, world)
    await add_occasion(db, world, recipient, 3, 8)
    await run(sessions, world)
    for row in await rows(db, world):
        assert row["due_at_utc"] >= NOW
