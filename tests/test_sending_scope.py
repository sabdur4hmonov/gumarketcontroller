"""CP6 sends bare reminder text, and the materializer respects a blocked customer.

Two fences and one wiring test:

* the send path must not reach into the catalogue -- that is CP9;
* a customer who blocked the bot must stop generating rows at all, otherwise
  the outbox refills nightly with sends that can only ever come back 403.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tokenize
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

SEND_PATH = (
    REPO_ROOT / "src/gulbot/sending/dispatcher.py",
    REPO_ROOT / "src/gulbot/sending/render.py",
    REPO_ROOT / "src/gulbot/sending/transport.py",
    REPO_ROOT / "src/gulbot/sending/telegram.py",
)

#: CP9 attaches bouquet suggestions by widening the transport and the renderer.
#: Until then, none of these may appear in the send path.
FORBIDDEN = ("product", "catalog", "catalogue", "hashtag", "bouquet", "copyMessage")


def code_only(path: Path) -> str:
    """Source with comments and string literals stripped.

    The modules explain in prose that they do NOT touch the catalogue, which a
    naive substring scan would read as evidence that they do.
    """
    kept: list[str] = []
    with path.open("rb") as handle:
        for token in tokenize.tokenize(io.BytesIO(handle.read()).readline):
            if token.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            kept.append(token.string)
    return " ".join(kept)


@pytest.mark.parametrize("path", SEND_PATH, ids=lambda p: p.name)
def test_the_send_path_does_not_touch_the_catalogue(path: Path) -> None:
    source = code_only(path).lower()
    for token in FORBIDDEN:
        assert token.lower() not in source, f"{path.name} reaches into CP9: {token}"


def test_the_send_path_imports_no_catalogue_module() -> None:
    """Fresh interpreter, so transitive imports count too."""
    program = (
        "import sys\n"
        "import gulbot.sending.dispatcher, gulbot.sending.render\n"
        # Scoped to gulbot's own future catalogue modules. "catalog" is an
        # overloaded word here: gulbot.i18n.catalog is the STRING catalogue and
        # is entirely legitimate, as is sqlalchemy's pg_catalog. Matching the
        # bare word would fail on things unrelated to products.
        "watched = ('gulbot.catalog', 'gulbot.products', 'gulbot.services.products',"
        " 'gulbot.services.catalog', 'gulbot.models.product')\n"
        "bad = sorted(m for m in sys.modules if m.startswith(watched))\n"
        "print(','.join(bad))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=True,
    )
    assert result.stdout.strip() == ""


def test_the_renderer_is_the_seam_cp9_will_widen() -> None:
    """Dispatch depends on a Renderer alias, not on message wording.

    CP9 changes what a reminder contains by changing the renderer and the
    transport; it should not need to touch dispatch at all.
    """
    from gulbot.sending import dispatcher

    assert hasattr(dispatcher, "Renderer")
    source = code_only(REPO_ROOT / "src/gulbot/sending/dispatcher.py")
    assert "render (" in source or "render(" in source


# --- a blocked customer stops being materialized ---------------------------


@pytest_asyncio.fixture
async def sessions(db: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    return bound_session_factory(db)


@pytest_asyncio.fixture
async def world(db: AsyncConnection) -> dict:
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
                "INSERT INTO customers (shop_id, telegram_user_id) VALUES (:s, 6801) RETURNING id"
            ),
            {"s": shop_id},
        )
    ).scalar_one()
    recipient_id = (
        await db.execute(
            text(
                "INSERT INTO recipients (shop_id, customer_id, label, type) "
                "VALUES (:s, :c, 'Onam', 'mother') RETURNING id"
            ),
            {"s": shop_id, "c": customer_id},
        )
    ).scalar_one()
    await db.execute(
        text(
            "INSERT INTO occasions "
            "(shop_id, customer_id, recipient_id, label, type, month, day) "
            "VALUES (:s, :c, :r, 'Onam', 'mother', 3, 8)"
        ),
        {"s": shop_id, "c": customer_id, "r": recipient_id},
    )
    return {"shop_id": shop_id, "customer_id": customer_id}


async def materialize(sessions: async_sessionmaker[AsyncSession], world: dict):
    async with sessions() as session:
        result = await materialize_shop(
            session,
            shop_id=world["shop_id"],
            now_utc=datetime(2027, 2, 20, 3, tzinfo=UTC),
        )
        await session.commit()
    return result


async def pending_count(db: AsyncConnection, world: dict) -> int:
    return int(
        (
            await db.execute(
                text(
                    "SELECT count(*) FROM scheduled_notifications "
                    "WHERE customer_id = :c AND state = 'pending'"
                ),
                {"c": world["customer_id"]},
            )
        ).scalar_one()
    )


@pytest.mark.infra
async def test_an_active_customer_is_materialized(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    result = await materialize(sessions, world)
    assert result.inserted > 0
    assert await pending_count(db, world) > 0


@pytest.mark.infra
async def test_a_blocked_customer_generates_no_new_rows(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """CP6 sets this status on a 403; the materializer has to honour it."""
    await db.execute(
        text("UPDATE customers SET status = 'blocked' WHERE id = :c"),
        {"c": world["customer_id"]},
    )
    result = await materialize(sessions, world)

    assert result.planned == 0
    assert await pending_count(db, world) == 0


@pytest.mark.infra
async def test_blocking_a_customer_prunes_their_pending_rows(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await materialize(sessions, world)
    assert await pending_count(db, world) > 0

    await db.execute(
        text("UPDATE customers SET status = 'blocked' WHERE id = :c"),
        {"c": world["customer_id"]},
    )
    await materialize(sessions, world)

    assert await pending_count(db, world) == 0


@pytest.mark.infra
async def test_blocking_a_customer_does_not_erase_what_was_already_sent(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """History survives. They really did receive those reminders."""
    await materialize(sessions, world)
    await db.execute(
        text(
            "UPDATE scheduled_notifications SET state = 'sent', sent_at = now() "
            "WHERE customer_id = :c AND offset_days = -7"
        ),
        {"c": world["customer_id"]},
    )
    await db.execute(
        text("UPDATE customers SET status = 'blocked' WHERE id = :c"),
        {"c": world["customer_id"]},
    )
    await materialize(sessions, world)

    surviving = (
        await db.execute(
            text(
                "SELECT state, count(*) FROM scheduled_notifications "
                "WHERE customer_id = :c GROUP BY state"
            ),
            {"c": world["customer_id"]},
        )
    ).all()
    assert surviving == [("sent", 1)]


@pytest.mark.infra
async def test_a_stopped_customer_is_also_skipped(
    db: AsyncConnection, world: dict, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """`stopped` is the opt-out status; it must behave like blocked here."""
    await db.execute(
        text("UPDATE customers SET status = 'stopped' WHERE id = :c"),
        {"c": world["customer_id"]},
    )
    result = await materialize(sessions, world)
    assert result.planned == 0
