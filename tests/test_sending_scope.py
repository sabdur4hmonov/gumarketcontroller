"""Where the catalogue may and may not appear in the send path.

REPLACED AT CP9, deliberately, and worth explaining rather than quietly
deleting. Until CP9 this file failed the build if the send path so much as
mentioned a product, a catalogue, a hashtag or a bouquet. CP9 is the checkpoint
that makes some of that legal -- so the fence moves rather than disappears.

The rule now:

  * `dispatcher.py` and `render.py` still know NOTHING about the catalogue.
    Dispatch owns claiming, retrying, 403/429 and marking, and none of that
    changes because a message carries a photo. The renderer produces words.
  * `attach.py` is the ONE module allowed to know. It reads the catalogue and
    hands dispatch an `Attachment` -- a file id and a caption -- so no catalogue
    type crosses into dispatch.
  * Nothing in the send path may reach the INDEXER, or write to the catalogue.
    CP9 is a reader. CP8 owns the writes.

Also here: a customer who blocked the bot must stop generating rows at all,
otherwise the outbox refills nightly with sends that can only ever come back 403.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tokenize
from datetime import UTC, datetime
from pathlib import Path
from textwrap import dedent

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker
from tests.bot_harness import bound_session_factory

from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.services.materializer import materialize_shop

REPO_ROOT = Path(__file__).resolve().parents[1]

#: These must stay catalogue-free for as long as the project exists.
CATALOGUE_FREE = (
    REPO_ROOT / "src/gulbot/sending/dispatcher.py",
    REPO_ROOT / "src/gulbot/sending/render.py",
)

#: The one module that may read the catalogue, plus the query service it uses.
CATALOGUE_AWARE = (
    REPO_ROOT / "src/gulbot/sending/attach.py",
    REPO_ROOT / "src/gulbot/services/bouquets.py",
)

FORBIDDEN = ("product", "catalog", "catalogue", "hashtag", "bouquet")

#: CP9 reads. Writing to the catalogue from the send path would mean a reminder
#: could mutate the shop's inventory, which is CP8's job and CP10's decision.
WRITE_TOKENS = ("insert", "update(", "delete(", "commit", "flush")


def code_only(path: Path) -> str:
    """Source with comments and string literals stripped.

    These modules explain in prose exactly what they do NOT do, which a naive
    substring scan would read as evidence that they do it.
    """
    kept: list[str] = []
    with path.open("rb") as handle:
        for token in tokenize.tokenize(io.BytesIO(handle.read()).readline):
            if token.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            kept.append(token.string)
    return " ".join(kept)


@pytest.mark.parametrize("path", CATALOGUE_FREE, ids=lambda p: p.name)
def test_dispatch_and_wording_never_learn_what_a_product_is(path: Path) -> None:
    source = code_only(path).lower()
    for token in FORBIDDEN:
        assert token not in source, f"{path.name} should not know about {token}"


@pytest.mark.parametrize("path", CATALOGUE_AWARE, ids=lambda p: p.name)
def test_the_catalogue_aware_modules_only_read(path: Path) -> None:
    source = code_only(path).lower()
    for token in WRITE_TOKENS:
        assert token not in source, f"{path.name} writes to the catalogue: {token}"


def test_the_send_path_does_not_reach_the_indexer() -> None:
    """CP8 writes the catalogue; CP9 reads it. They must not meet.

    Fresh interpreter, so a transitive import counts. In-process this would
    pass trivially -- pytest has imported the whole package by the time any
    test runs.
    """
    program = dedent(
        """
        import sys
        import gulbot.sending.attach, gulbot.sending.dispatcher
        watched = ('gulbot.services.indexer', 'gulbot.catalog.indexer',
                   'gulbot.bot.channel', 'gulbot.bot.routers')
        bad = sorted(m for m in sys.modules if m.startswith(watched))
        print(','.join(bad))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, cwd=REPO_ROOT, check=True
    )
    assert result.stdout.strip() == "", f"the send path reached the indexer: {result.stdout}"


def test_dispatch_alone_still_pulls_in_no_catalogue_service() -> None:
    """The narrower claim, unchanged in spirit from CP7.

    `attach.py` may import the query service. Dispatch, imported on its own,
    must still not -- which is what makes the seam real rather than nominal.
    """
    program = dedent(
        """
        import sys
        import gulbot.sending.dispatcher, gulbot.sending.render
        watched = ('gulbot.services.products', 'gulbot.services.bouquets',
                   'gulbot.services.catalog', 'gulbot.services.hashtag_aliases',
                   'gulbot.services.indexer', 'gulbot.sending.attach')
        bad = sorted(m for m in sys.modules if m.startswith(watched))
        print(','.join(bad))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, cwd=REPO_ROOT, check=True
    )
    assert result.stdout.strip() == "", f"dispatch pulled in: {result.stdout}"


def test_the_attacher_is_optional_so_cp6_dispatch_is_unchanged() -> None:
    """The reason every CP6 dispatcher test passes unmodified.

    `run_tick` grew a parameter rather than changing one. A tick built without
    an attacher behaves exactly as it did at CP6, down to calling `send_text`.
    """
    import inspect

    from gulbot.sending import dispatcher

    parameters = inspect.signature(dispatcher.run_tick).parameters
    assert parameters["attach"].default is None
    assert hasattr(dispatcher, "Attacher")
    source = code_only(REPO_ROOT / "src/gulbot/sending/dispatcher.py")
    assert "send_text" in source, "the text path must survive; it is the fallback"
    assert "send_photo" in source


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
            "(shop_id, customer_id, recipient_id, label, type, kind, month, day) "
            "VALUES (:s, :c, :r, 'Onam', 'mother', 'birthday', 3, 8)"
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
