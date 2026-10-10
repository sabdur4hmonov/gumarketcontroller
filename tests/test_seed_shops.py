"""L3 of AUDIT_MULTI_TENANT.md: the seed CLI can make more than one shop.

THE FINDING. `python -m gulbot.cli.seed` created exactly one shop, found by the
hardcoded name "Gulbot Dev Shop", with no channel, no group and no owner. Fine
for one shop; useless for a second, and -- since H3 -- a seeded shop with no
`channel_id` indexes nothing, so even the one it made could not show a
catalogue without a trip to psql.

THE FIX. `--name` picks the shop (the dev name stays the default), and
`--channel-id`, `--group-chat-id` and `--owner-id` wire it. Still idempotent,
and still never OVERWRITES: a run fills only what is unset, and a value that
disagrees with what is stored is refused, not applied -- the same promise the
seed always made about hand-tuned settings. A shop's bot token is NOT a seed
argument: the platform bot's onboarding is the provisioning path for a real
shop, and a token on a command line ends up in shell history.
"""

from __future__ import annotations

import sys
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import bound_session_factory

import gulbot.cli.seed as seed

# --- the command line --------------------------------------------------------


def test_the_command_line_names_the_shop(monkeypatch: pytest.MonkeyPatch) -> None:
    """DEFECT IF THIS FAILS. The CLI ignored its arguments: every run made or
    found the one dev shop, so a second shop could not be seeded at all."""
    called: dict[str, Any] = {}

    async def recording(**kwargs: Any) -> tuple[int, bool]:
        called.update(kwargs)
        return 2, True

    monkeypatch.setattr(seed, "seed_dev_shop", recording)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "seed",
            "--name",
            "Shop B",
            "--channel-id",
            "-1001",
            "--group-chat-id",
            "-1002",
            "--owner-id",
            "11",
            "--owner-id",
            "12",
        ],
    )
    seed.main()
    assert called.get("name") == "Shop B"
    assert called.get("channel_id") == -1001
    assert called.get("group_chat_id") == -1002
    assert called.get("owner_ids") == [11, 12]


def test_the_default_is_still_the_dev_shop(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, Any] = {}

    async def recording(**kwargs: Any) -> tuple[int, bool]:
        called.update(kwargs)
        return 1, False

    monkeypatch.setattr(seed, "seed_dev_shop", recording)
    monkeypatch.setattr(sys, "argv", ["seed"])
    seed.main()
    assert called.get("name") == seed.dev_shop_name() == "Gulbot Dev Shop"


# --- against the database ------------------------------------------------------


async def _shop(db: AsyncConnection, name: str) -> Any:
    return (
        await db.execute(
            text(
                "SELECT id, channel_id, group_chat_id, owner_telegram_ids FROM shops "
                "WHERE name = :n"
            ),
            {"n": name},
        )
    ).one_or_none()


@pytest.mark.infra
async def test_two_names_make_two_shops_each_wired(db: AsyncConnection) -> None:
    async with bound_session_factory(db)() as session:
        a, created_a = await seed.ensure_shop(session, name="Shop A", channel_id=-1001)
        try:
            b, created_b = await seed.ensure_shop(
                session, name="Shop B", channel_id=-2001, group_chat_id=-2002, owner_ids=[7]
            )
        except seed.SeedConflict as conflict:
            b, created_b = 0, False
            print(f"second shop refused: {conflict}")
        await session.flush()
        # Read back while the session's savepoint is still open.
        assert created_a and created_b and a != b, "a second name did not make a second shop"
        assert tuple((await _shop(db, "Shop A"))[1:]) == (-1001, None, [])
        assert tuple((await _shop(db, "Shop B"))[1:]) == (-2001, -2002, [7])


@pytest.mark.infra
async def test_a_rerun_fills_what_is_unset_and_never_overwrites(db: AsyncConnection) -> None:
    async with bound_session_factory(db)() as session:
        first, _ = await seed.ensure_shop(session, name="Shop A")
        again, created = await seed.ensure_shop(session, name="Shop A", channel_id=-1001)
        await session.flush()
        assert (again, created) == (first, False)
        assert (await _shop(db, "Shop A"))[1] == -1001, "an unset channel was not filled"

        refusal = ""
        try:
            await seed.ensure_shop(session, name="Shop A", channel_id=-9999)
        except seed.SeedConflict as conflict:
            refusal = str(conflict)
        await session.flush()
        assert "channel_id" in refusal, "a conflicting value was not refused"
        assert (await _shop(db, "Shop A"))[1] == -1001, "a stored value was overwritten"


# --- the shop's language (shops.lang, the CP-MT2 follow-up to L2) ---------------


def test_the_command_line_takes_the_shop_language(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, Any] = {}

    async def recording(**kwargs: Any) -> tuple[int, bool]:
        called.update(kwargs)
        return 3, True

    monkeypatch.setattr(seed, "seed_dev_shop", recording)
    monkeypatch.setattr(sys, "argv", ["seed", "--name", "Shop R", "--lang", "ru"])
    seed.main()
    assert called.get("lang") == "ru"


@pytest.mark.infra
async def test_a_seeded_shop_keeps_its_language_and_a_rerun_never_changes_it(
    db: AsyncConnection,
) -> None:
    async with bound_session_factory(db)() as session:
        await seed.ensure_shop(session, name="Shop R", lang="ru")
        await session.flush()
        stored = await db.scalar(text("SELECT lang FROM shops WHERE name = 'Shop R'"))
        assert stored == "ru"
        refusal = ""
        try:
            await seed.ensure_shop(session, name="Shop R", lang="uz")
        except seed.SeedConflict as conflict:
            refusal = str(conflict)
        await session.flush()
        assert "lang" in refusal, "a different language was not refused"
        assert await db.scalar(text("SELECT lang FROM shops WHERE name = 'Shop R'")) == "ru"
