"""CP21, found by the staging rehearsal: a fresh server's pilot shop had no bot.

THE FINDING. The process BOT_TOKEN serves only the shop flagged
`uses_process_bot_token`, and only the per-shop-tokens migration sets that
flag -- on a database that already held exactly one shop. On the fresh
database DEPLOY starts from, that migration finds no shop, so the seeded pilot
was "not the legacy shop allowed to use BOT_TOKEN": the bot process refused to
start (systemd restarted it every ten seconds) and every reminder failed with
"no usable bot". The runbook's step 11 ("the pilot may keep using BOT_TOKEN")
was true only of the dev database.

THE FIX. `python -m gulbot.cli.seed --store-bot-token` makes the process
BOT_TOKEN the shop's OWN token, encrypted exactly as onboarding stores one.
The token comes from the environment the seed already runs in -- never from
the command line, which would put it in shell history. Like the rest of the
seed: idempotent, and never overwrites.
"""

from __future__ import annotations

import sys
from typing import Any

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import bound_session_factory

import gulbot.cli.seed as seed
import gulbot.services.shop_tokens as shop_tokens_module
from gulbot.bot.registry import stored_tokens
from gulbot.config import Settings
from gulbot.sending.transport import ShopBotUnavailable
from gulbot.services.shop_tokens import load_bot_credentials

TOKEN = "123456789:PILOTpilotPILOTpilotPILOTpilotPILOTpi"
SECRET = TOKEN.split(":", 1)[1]
OTHER = "987654321:OTHERotherOTHERotherOTHERotherOTHERot"


@pytest.fixture
def key(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    moved = settings.model_copy(
        update={"shop_token_encryption_key": SecretStr(Fernet.generate_key().decode())}
    )
    monkeypatch.setattr(shop_tokens_module, "get_settings", lambda: moved)


def process_token(monkeypatch: pytest.MonkeyPatch, settings: Settings, token: str) -> None:
    moved = settings.model_copy(update={"bot_token": SecretStr(token)})
    monkeypatch.setattr(seed, "get_settings", lambda: moved)


# --- the command line --------------------------------------------------------


def test_the_flag_stores_the_token_for_the_shop_it_seeded(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    stored_for: list[int] = []

    async def seeding(**kwargs: Any) -> tuple[int, bool]:
        return 5, True

    async def storing(*, shop_id: int) -> tuple[int, bool]:
        stored_for.append(shop_id)
        return 123456789, True

    monkeypatch.setattr(seed, "seed_dev_shop", seeding)
    monkeypatch.setattr(seed, "seed_bot_token", storing)
    monkeypatch.setattr(sys, "argv", ["seed", "--name", "Pilot", "--store-bot-token"])
    seed.main()
    assert stored_for == [5]
    assert "123456789" in capsys.readouterr().out


def test_without_the_flag_no_token_is_touched(monkeypatch: pytest.MonkeyPatch) -> None:
    stored_for: list[int] = []

    async def seeding(**kwargs: Any) -> tuple[int, bool]:
        return 5, True

    async def storing(*, shop_id: int) -> tuple[int, bool]:
        stored_for.append(shop_id)
        return 0, True

    monkeypatch.setattr(seed, "seed_dev_shop", seeding)
    monkeypatch.setattr(seed, "seed_bot_token", storing)
    monkeypatch.setattr(sys, "argv", ["seed", "--name", "Pilot"])
    seed.main()
    assert stored_for == []


def test_the_token_is_never_a_command_line_argument() -> None:
    actions = {action.dest: action for action in seed.build_parser()._actions}
    assert actions["store_bot_token"].nargs == 0, "the flag must not take a value"


def test_the_process_token_comes_from_the_settings(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    process_token(monkeypatch, settings, TOKEN)
    assert seed.process_bot_token() == TOKEN


# --- against the database ------------------------------------------------------


async def _row(db: AsyncConnection, shop_id: int) -> Any:
    return (
        await db.execute(
            text("SELECT bot_token_encrypted, bot_telegram_id FROM shops WHERE id = :i"),
            {"i": shop_id},
        )
    ).one()


async def _attempt(session: Any, shop_id: int, token: str) -> bool | Exception:
    """The outcome, refusal included, so every check below is an assertion."""
    try:
        return await seed.store_process_bot_token(session, shop_id=shop_id, token=token)
    except Exception as outcome:
        return outcome


@pytest.mark.infra
async def test_the_seeded_pilot_gets_a_usable_bot_on_a_fresh_database(
    db: AsyncConnection, key: None
) -> None:
    """DEFECT IF THIS FAILS. The rehearsal's finding: seeded, but no bot."""
    async with bound_session_factory(db)() as session:
        shop_id, _ = await seed.ensure_shop(session, name="Pilot")
        before = stored_tokens(await load_bot_credentials(session, shop_ids=[shop_id]))
        with pytest.raises(ShopBotUnavailable, match="not the legacy shop"):
            before(shop_id)

        assert await seed.store_process_bot_token(session, shop_id=shop_id, token=TOKEN) is True
        await session.flush()
        after = stored_tokens(await load_bot_credentials(session, shop_ids=[shop_id]))
        assert after(shop_id) == TOKEN, "the stored token is not the one the registry serves"
        ciphertext, bot_id = await _row(db, shop_id)
        assert bot_id == 123456789
        assert SECRET not in ciphertext, "the token was stored in the clear"


@pytest.mark.infra
async def test_a_rerun_with_the_same_token_changes_nothing(db: AsyncConnection, key: None) -> None:
    async with bound_session_factory(db)() as session:
        shop_id, _ = await seed.ensure_shop(session, name="Pilot")
        await seed.store_process_bot_token(session, shop_id=shop_id, token=TOKEN)
        await session.flush()
        first = await _row(db, shop_id)
        outcome = await _attempt(session, shop_id, TOKEN)
        assert outcome is False, f"a rerun was not a quiet no-op: {outcome!r}"
        await session.flush()
        assert await _row(db, shop_id) == first


@pytest.mark.infra
async def test_a_shop_with_another_bot_is_never_overwritten(db: AsyncConnection, key: None) -> None:
    async with bound_session_factory(db)() as session:
        shop_id, _ = await seed.ensure_shop(session, name="Pilot")
        await seed.store_process_bot_token(session, shop_id=shop_id, token=OTHER)
        await session.flush()
        first = await _row(db, shop_id)
        with pytest.raises(seed.SeedConflict) as refused:
            await seed.store_process_bot_token(session, shop_id=shop_id, token=TOKEN)
        await session.flush()
        assert await _row(db, shop_id) == first
        assert SECRET not in str(refused.value)


@pytest.mark.infra
async def test_a_bot_another_shop_holds_is_refused(db: AsyncConnection, key: None) -> None:
    async with bound_session_factory(db)() as session:
        holder, _ = await seed.ensure_shop(session, name="Holder")
        await seed.store_process_bot_token(session, shop_id=holder, token=TOKEN)
        pilot, _ = await seed.ensure_shop(session, name="Pilot")
        await session.flush()
        outcome = await _attempt(session, pilot, TOKEN)
        assert isinstance(outcome, seed.SeedConflict), f"not a clear refusal: {type(outcome)}"
        assert f"shop {holder}" in str(outcome)
        await session.flush()
        assert await _row(db, pilot) == (None, None)


@pytest.mark.infra
@pytest.mark.parametrize("token", ["", "not-a-token", "123:short"])
async def test_no_usable_process_token_is_refused_and_never_echoed(
    db: AsyncConnection, key: None, token: str
) -> None:
    async with bound_session_factory(db)() as session:
        shop_id, _ = await seed.ensure_shop(session, name="Pilot")
        outcome = await _attempt(session, shop_id, token)
        assert isinstance(outcome, seed.SeedConflict), f"not a clear refusal: {type(outcome)}"
        assert "BOT_TOKEN" in str(outcome)
        await session.flush()
        assert await _row(db, shop_id) == (None, None)
        if token:
            assert token not in str(outcome)
