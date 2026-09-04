"""Materializer scale and scope.

The performance budget is a concrete number, recorded here rather than left
implicit. It is deliberately generous against the measured figure: this test
exists to catch an accidental N+1 or a per-row round trip, not to police a few
hundred milliseconds of noise on a laptop.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time as clock
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker
from tests.bot_harness import bound_session_factory

from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.services.materializer import materialize_shop

REPO_ROOT = Path(__file__).resolve().parents[1]

OCCASION_COUNT = 10_000
CUSTOMER_COUNT = 500

#: Budget for a 10k-occasion run against local Postgres, in seconds.
#: MEASURED at 15.4s on the dev box (500 customers x 20 dates, 45-day horizon).
#: 60s leaves room for slower hardware while still failing loudly if the run
#: degrades into per-row work -- an accidental N+1 here would blow well past it.
MATERIALIZE_BUDGET_SECONDS = 60.0


@pytest_asyncio.fixture
async def sessions(db: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    return bound_session_factory(db)


@pytest_asyncio.fixture
async def big_shop(db: AsyncConnection) -> int:
    """One shop, 500 customers, 10k occasions spread across the whole year."""
    shop_id = (
        await db.execute(
            text(
                "INSERT INTO shops (name, working_hours) "
                "VALUES ('Scale', CAST(:wh AS jsonb)) RETURNING id"
            ),
            {"wh": json.dumps(DEFAULT_WORKING_HOURS)},
        )
    ).scalar_one()

    await db.execute(
        text(
            "INSERT INTO customers (shop_id, telegram_user_id) "
            "SELECT :s, 700000 + g FROM generate_series(1, :n) AS g"
        ),
        {"s": shop_id, "n": CUSTOMER_COUNT},
    )
    await db.execute(
        text(
            "INSERT INTO recipients (shop_id, customer_id, label, type) "
            "SELECT :s, c.id, 'R', 'older_sister' FROM customers c WHERE c.shop_id = :s"
        ),
        {"s": shop_id},
    )
    # Dates spread over the full year so only a slice falls inside the horizon,
    # which is what a real shop looks like.
    await db.execute(
        text(
            "INSERT INTO occasions "
            "(shop_id, customer_id, recipient_id, label, type, kind, month, day) "
            "SELECT :s, r.customer_id, r.id, 'R', 'older_sister', 'birthday', "
            # mod(), never %: the driver treats % as parameter escaping and a
            # doubled literal reaches Postgres as invalid SQL.
            "       1 + mod(g, 12), 1 + mod(g, 28) "
            "FROM recipients r "
            "CROSS JOIN generate_series(1, :per) AS g "
            "WHERE r.shop_id = :s"
        ),
        {"s": shop_id, "per": OCCASION_COUNT // CUSTOMER_COUNT},
    )
    return int(shop_id)


@pytest.mark.infra
async def test_ten_thousand_occasions_materialize_within_budget(
    db: AsyncConnection, big_shop: int, sessions: async_sessionmaker[AsyncSession]
) -> None:
    seeded = (
        await db.execute(text("SELECT count(*) FROM occasions WHERE shop_id = :s"), {"s": big_shop})
    ).scalar_one()
    assert seeded == OCCASION_COUNT, seeded

    started = clock.perf_counter()
    async with sessions() as session:
        result = await materialize_shop(
            session, shop_id=big_shop, now_utc=datetime(2027, 2, 20, 3, tzinfo=UTC)
        )
        await session.commit()
    elapsed = clock.perf_counter() - started

    assert result.occasions == OCCASION_COUNT
    assert result.inserted > 0
    assert elapsed < MATERIALIZE_BUDGET_SECONDS, (
        f"10k occasions took {elapsed:.1f}s, budget {MATERIALIZE_BUDGET_SECONDS}s"
    )
    print(f"\n  materialized {OCCASION_COUNT} occasions in {elapsed:.1f}s")


@pytest.mark.infra
async def test_a_second_run_at_scale_inserts_nothing(
    db: AsyncConnection, big_shop: int, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Idempotency has to hold at scale too, not just on three rows."""
    now = datetime(2027, 2, 20, 3, tzinfo=UTC)
    async with sessions() as session:
        await materialize_shop(session, shop_id=big_shop, now_utc=now)
        await session.commit()

    before = (
        await db.execute(
            text("SELECT count(*) FROM scheduled_notifications WHERE shop_id = :s"),
            {"s": big_shop},
        )
    ).scalar_one()

    async with sessions() as session:
        second = await materialize_shop(session, shop_id=big_shop, now_utc=now)
        await session.commit()

    after = (
        await db.execute(
            text("SELECT count(*) FROM scheduled_notifications WHERE shop_id = :s"),
            {"s": big_shop},
        )
    ).scalar_one()

    assert (second.inserted, second.pruned) == (0, 0)
    assert before == after


# --- scope fence -----------------------------------------------------------

MATERIALIZER = REPO_ROOT / "src/gulbot/services/materializer.py"

#: Case-sensitive. CHANNEL_TELEGRAM and NotificationChannel.TELEGRAM are the
#: legitimate way to name the channel; a lowercase `telegram` would mean an
#: actual client crept in.
FORBIDDEN_TOKENS = (
    "aiogram",
    "Bot(",
    "send_message",
    "answer(",
    "celery",
    "beat",
    "message_log",
)


def code_only(path: Path) -> str:
    """Source with comments and string literals removed.

    The module's own docstring says it does not send anything, which a naive
    substring scan would read as evidence that it does.
    """
    import io
    import tokenize

    kept = []
    with path.open("rb") as handle:
        for token in tokenize.tokenize(io.BytesIO(handle.read()).readline):
            if token.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            kept.append(token.string)
    return " ".join(kept)


def test_materializer_does_not_send_anything() -> None:
    """CP5 persists and reconciles. Sending is CP6.

    Keeping the outbox writer free of a Telegram client is what makes it safe
    to run repeatedly, and what keeps the two checkpoints revertable apart.
    """
    source = code_only(MATERIALIZER)
    for token in FORBIDDEN_TOKENS:
        assert token not in source, f"materializer already reaches into CP6: {token}"


def test_materializer_imports_no_telegram_or_worker_machinery() -> None:
    """Checked in a FRESH interpreter, so transitive imports count too."""
    program = (
        "import sys\n"
        "import gulbot.services.materializer\n"
        "leaked = sorted(m for m in ('aiogram', 'celery') if m in sys.modules)\n"
        "print(','.join(leaked))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=True,
    )
    assert result.stdout.strip() == "", f"materializer pulled in: {result.stdout.strip()}"


def test_materializer_never_writes_a_sent_state() -> None:
    """Only CP6 may mark a row sent; CP5 only ever creates pending rows."""
    source = code_only(MATERIALIZER)
    assert "sent_at" not in source
