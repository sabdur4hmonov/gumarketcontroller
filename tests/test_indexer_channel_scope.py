"""H3 of AUDIT_MULTI_TENANT.md: only the shop's OWN channel is its catalogue.

THE DEFECT. `shops.channel_id` was written at onboarding and read by nothing.
The indexer took `shop_id` from the dispatcher and the post's chat id from the
post, and never compared the two with the shop. The rule it actually enforced
was "any channel this bot can see is this shop's catalogue": add a shop's bot to
a second channel -- by mistake, by a reseller, on purpose -- and that channel's
posts became the shop's products, with prices, orderable.

Worse than a stray row: products are keyed on `(shop_id, channel_message_id)`,
and message ids are per channel. An EDIT in a foreign channel whose message id
matched a real product rewrote that product's caption and price.

The composite FKs cannot see any of it: every row carries a valid shop_id. It is
a correct-looking row with the wrong provenance.

THE FIX. A post is indexed only when its chat IS `shops.channel_id`. A shop with
no channel recorded indexes nothing -- an unconnected catalogue, logged with the
chat id the operator needs, rather than whichever channel spoke first.

Everything goes through the real dispatcher, as in `test_indexer.py`.
"""

from __future__ import annotations

import logging

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import CHANNEL_ID, bound_session_factory, make_bot
from tests.test_indexer import World

from gulbot.bot.factory import build_dispatcher

pytestmark = pytest.mark.infra

#: Some other channel the shop's bot was added to.
FOREIGN_CHANNEL = -1009999999999


@pytest_asyncio.fixture
async def world(db: AsyncConnection, shop_id: int) -> World:
    """`test_indexer`'s world, with the shop connected to CHANNEL_ID."""
    await db.execute(
        text("UPDATE shops SET channel_id = :c WHERE id = :s"), {"c": CHANNEL_ID, "s": shop_id}
    )
    sessions = bound_session_factory(db)
    bot, _ = make_bot()
    built = World(None, bot, sessions, db, shop_id)  # type: ignore[arg-type]

    async def recorder(*, shop_id: int, media_group_id: str) -> None:
        built.scheduled.append(media_group_id)

    built.dispatcher = build_dispatcher(
        session_factory=sessions, shop_id=shop_id, schedule_finalize=recorder
    )
    return built


async def test_a_post_in_the_shops_own_channel_is_indexed(world: World) -> None:
    """GUARDS THE FIX. A check that refused every channel would pass the rest."""
    await world.post(message_id=101, file_id="own-101", caption="Atirgul 450 000 so'm #atirgul")
    row = await world.only_product()
    assert (row.channel_chat_id, row.price_uzs) == (CHANNEL_ID, 450_000)


async def test_a_post_in_another_channel_is_not_this_shops_product(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    """DEFECT IF THIS FAILS."""
    with caplog.at_level(logging.WARNING, logger="gulbot.indexer"):
        await world.post(
            message_id=101,
            file_id="foreign-101",
            caption="Arzon gul 1 000 so'm #atirgul",
            chat_id=FOREIGN_CHANNEL,
        )
    assert await world.products() == []
    assert str(FOREIGN_CHANNEL) in caplog.text, "the refusal must name the channel"


async def test_an_album_in_another_channel_is_not_ingested_either(world: World) -> None:
    """DEFECT IF THIS FAILS. Albums take a different path -- an upsert, then a
    debounce -- and the check must sit in front of that one too."""
    for message_id in (201, 202):
        await world.post(
            message_id=message_id,
            file_id=f"foreign-{message_id}",
            caption="#atirgul" if message_id == 201 else None,
            media_group_id="foreign-album",
            chat_id=FOREIGN_CHANNEL,
        )
    assert await world.products() == []
    assert world.scheduled == [], "a foreign album was queued for finalizing"


async def test_an_edit_in_another_channel_cannot_rewrite_a_real_product(world: World) -> None:
    """DEFECT IF THIS FAILS. Same message id, different channel: the lookup
    keyed on (shop_id, channel_message_id) found the real product and re-priced
    it from a channel the shop does not own."""
    await world.post(message_id=101, file_id="own-101", caption="Atirgul 450 000 so'm #atirgul")
    await world.edit(
        message_id=101,
        file_id="foreign-101",
        caption="Atirgul 1 000 so'm #atirgul",
        chat_id=FOREIGN_CHANNEL,
    )
    row = await world.only_product()
    assert (row.price_uzs, row.telegram_file_id) == (450_000, "own-101")


async def test_a_shop_with_no_channel_recorded_indexes_nothing(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    """DEFECT IF THIS FAILS. NULL is "not connected yet", not "any channel":
    the first channel to post would otherwise become the catalogue."""
    await world.db.execute(
        text("UPDATE shops SET channel_id = NULL WHERE id = :s"), {"s": world.shop_id}
    )
    with caplog.at_level(logging.WARNING, logger="gulbot.indexer"):
        await world.post(message_id=101, file_id="own-101", caption="#atirgul")
    assert await world.products() == []
    assert "channel_id" in caplog.text, "the refusal must say what to set"
