"""Writing an onboarded shop: all at once, or not at all.

`create_onboarded_shop` is the ONLY write the onboarding conversation makes.
Everything the owner gave -- name, token, channel, group, phone -- is held in
the conversation until the last answer, then written here in one transaction,
so no failure along the way can leave a half-configured shop that the pollers
and the ticks would then pick up.

Also here: the one fact that makes "one bot per shop" enforceable. The bot's
numeric id -- the public half of its token -- is stored in a UNIQUE column, so
two shops cannot claim the same bot even if two onboardings race.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import bound_session_factory

import gulbot.services.shop_tokens as shop_tokens_module
from gulbot.catalog.hashtags import extract_hashtags
from gulbot.catalog.naming import product_name
from gulbot.catalog.prices import PriceConfidence, parse_price
from gulbot.config import Settings
from gulbot.i18n.catalog import CATALOG
from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.services.shop_onboarding import NewShop, bot_is_taken, create_onboarded_shop
from gulbot.services.shop_tokens import bot_id_of, decrypt_token, set_shop_bot_token

TOKEN = "777777:SHOPshopSHOPshopSHOPshopSHOPshopSX"


@pytest.fixture
def key(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> str:
    fresh = Fernet.generate_key().decode()
    moved = settings.model_copy(update={"shop_token_encryption_key": SecretStr(fresh)})
    monkeypatch.setattr(shop_tokens_module, "get_settings", lambda: moved)
    return fresh


def new_shop(**overrides: Any) -> NewShop:
    values: dict[str, Any] = {
        "name": "Lola Gullari",
        "token": TOKEN,
        "channel_id": -1_001_700_000_001,
        "group_chat_id": -1_001_700_000_002,
        "owner_telegram_id": 5_551_001,
        "owner_phone": "+998901112233",
        "owner_phone_verified": True,
    }
    values.update(overrides)
    return NewShop(**values)


async def _rows(db: AsyncConnection) -> list[dict[str, Any]]:
    result = await db.execute(
        text(
            "SELECT name, channel_id, group_chat_id, owner_telegram_ids, owner_phone, "
            " owner_phone_verified, uses_process_bot_token, bot_token_encrypted, "
            " bot_telegram_id, working_hours FROM shops ORDER BY id"
        )
    )
    return [dict(r) for r in result.mappings()]


def test_the_bot_id_is_the_public_half_of_the_token() -> None:
    assert bot_id_of(TOKEN) == 777777


@pytest.mark.infra
async def test_an_onboarded_shop_is_written_whole(db: AsyncConnection, key: str) -> None:
    async with bound_session_factory(db)() as session:
        shop_id = await create_onboarded_shop(session, new_shop())
        await session.commit()

    (row,) = await _rows(db)
    assert isinstance(shop_id, int)
    assert row["name"] == "Lola Gullari"
    assert (row["channel_id"], row["group_chat_id"]) == (-1_001_700_000_001, -1_001_700_000_002)
    assert row["owner_telegram_ids"] == [5_551_001]
    assert (row["owner_phone"], row["owner_phone_verified"]) == ("+998901112233", True)
    assert row["uses_process_bot_token"] is False
    assert row["bot_telegram_id"] == 777777
    assert decrypt_token(row["bot_token_encrypted"]) == TOKEN
    assert row["working_hours"] == DEFAULT_WORKING_HOURS


@pytest.mark.infra
async def test_a_failure_part_way_leaves_no_row(db: AsyncConnection, key: str) -> None:
    """The token is written through its own path after the row exists; if THAT
    fails, the row it was for must not survive."""
    async with bound_session_factory(db)() as session:
        with pytest.raises(ValueError):
            await create_onboarded_shop(session, new_shop(token="not-a-token"))
        await session.rollback()
    assert await _rows(db) == []


@pytest.mark.infra
async def test_two_shops_cannot_hold_the_same_bot(db: AsyncConnection, key: str) -> None:
    """Enforced by Postgres, not by the check the conversation makes first --
    that check and a racing second onboarding can both pass."""
    async with bound_session_factory(db)() as session:
        await create_onboarded_shop(session, new_shop())
        await session.commit()

    async with bound_session_factory(db)() as session:
        with pytest.raises(IntegrityError) as refused:
            await create_onboarded_shop(session, new_shop(name="Second"))
        await session.rollback()
    assert "uq_shops_bot_telegram_id" in str(refused.value)
    assert [r["name"] for r in await _rows(db)] == ["Lola Gullari"]


@pytest.mark.infra
async def test_bot_is_taken_answers_from_the_stored_ids(db: AsyncConnection, key: str) -> None:
    async with bound_session_factory(db)() as session:
        assert await bot_is_taken(session, bot_id=777777) is False
        await create_onboarded_shop(session, new_shop())
        await session.commit()
        assert await bot_is_taken(session, bot_id=777777) is True


@pytest.mark.infra
async def test_storing_a_token_records_its_bot_id(db: AsyncConnection, key: str) -> None:
    shop = (
        await db.execute(
            text(
                "INSERT INTO shops (name, working_hours) "
                "VALUES ('S', CAST(:wh AS jsonb)) RETURNING id"
            ),
            {"wh": json.dumps(DEFAULT_WORKING_HOURS)},
        )
    ).scalar_one()
    async with bound_session_factory(db)() as session:
        await set_shop_bot_token(session, shop_id=shop, token=TOKEN)
        await session.commit()
    (row,) = await _rows(db)
    assert row["bot_telegram_id"] == 777777


# --- the posting guide says what the indexer actually does -----------------


def test_the_posting_guide_example_parses_exactly_as_the_guide_promises() -> None:
    """The guide is prose, and prose drifts from code. So its worked example
    is run through the indexer's own parsers: if the conventions ever change,
    this fails and the guide gets rewritten, instead of quietly teaching shops
    a format the indexer no longer reads."""
    from gulbot.bot.routers.shop_onboarding import POSTING_EXAMPLE

    assert extract_hashtags(POSTING_EXAMPLE) == ["atirgul", "buket"]
    price, confidence = parse_price(POSTING_EXAMPLE)
    assert (price, confidence) == (450_000, PriceConfidence.HIGH)
    assert product_name(POSTING_EXAMPLE) == "Qizil atirgul buketi 51 ta"
    for lang in ("uz", "ru"):
        assert POSTING_EXAMPLE in CATALOG["owner.posting_guide"][lang]


def test_a_post_the_guide_warns_against_really_is_ignored() -> None:
    """The guide's "no hashtag, not a product" and "a number is not a tag"."""
    assert extract_hashtags("Qizil atirgul buketi 51 ta\nNarxi: 450 000 so'm") == []
    assert extract_hashtags("Qizil atirgul #450000") == []
