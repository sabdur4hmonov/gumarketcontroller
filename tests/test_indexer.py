"""CP8: channel posts become catalogue rows.

Everything here goes through `Dispatcher.feed_update` against the REAL
dispatcher built by `build_dispatcher`, not through hand-called service
functions. The thing under test is the wiring -- allowed updates, the router,
the filters, the middlewares -- as much as the merge logic, and calling the
service directly would prove none of it.

The debounce SCHEDULER is a recorder rather than Celery. That is not a
shortcut: the scheduler's only job is "ask for this album to be settled
shortly", and the tests settle it explicitly at the point the debounce would.
The scheduler's own collapsing behaviour is tested in test_album_debounce.py.
"""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from aiogram import Bot, Dispatcher
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker
from tests.bot_harness import (
    CHANNEL_ID,
    bound_session_factory,
    channel_post_update,
    edited_channel_post_update,
    feed,
    make_bot,
)

from gulbot.bot.factory import build_dispatcher
from gulbot.services.indexer import Finalize, finalize_product

pytestmark = pytest.mark.infra

ALBUM = "media-group-77"


class World:
    """One shop, one dispatcher, one recording scheduler."""

    def __init__(
        self,
        dispatcher: Dispatcher,
        bot: Bot,
        sessions: async_sessionmaker[AsyncSession],
        db: AsyncConnection,
        shop_id: int,
    ) -> None:
        self.dispatcher = dispatcher
        self.bot = bot
        self.sessions = sessions
        self.db = db
        self.shop_id = shop_id
        self.scheduled: list[str] = []

    async def post(self, **kwargs: Any) -> None:
        await feed(self.dispatcher, self.bot, channel_post_update(**kwargs))

    async def edit(self, **kwargs: Any) -> None:
        await feed(self.dispatcher, self.bot, edited_channel_post_update(**kwargs))

    async def settle(self, media_group_id: str | None = None, **kwargs: Any) -> Any:
        """Run what the debounced task would run, at the moment it would run."""
        async with self.sessions() as session:
            result = await finalize_product(
                session, shop_id=self.shop_id, media_group_id=media_group_id, **kwargs
            )
            await session.commit()
        return result

    async def products(self) -> list[Any]:
        return (
            await self.db.execute(
                text(
                    "SELECT id, name, price_uzs, price_confidence, telegram_file_id, "
                    "channel_message_id, channel_chat_id, media_group_id, caption_raw, "
                    "finalized_at, indexed_at, active "
                    "FROM products WHERE shop_id = :s ORDER BY id"
                ),
                {"s": self.shop_id},
            )
        ).all()

    async def only_product(self) -> Any:
        rows = await self.products()
        assert len(rows) == 1, f"expected exactly one product, got {len(rows)}"
        return rows[0]

    async def product_id_sequence(self) -> int:
        """A deleted row still burned its id. This is how "never written" is
        told apart from "written and then cleaned up"."""
        return int(
            (await self.db.execute(text("SELECT last_value FROM products_id_seq"))).scalar_one()
        )

    async def tags(self, product_id: int) -> list[str]:
        return [
            row[0]
            for row in (
                await self.db.execute(
                    text(
                        "SELECT hashtag_normalized FROM product_hashtags "
                        "WHERE product_id = :p ORDER BY hashtag_normalized"
                    ),
                    {"p": product_id},
                )
            ).all()
        ]


@pytest_asyncio.fixture
async def world(db: AsyncConnection, shop_id: int) -> World:
    # The shop's catalogue is CHANNEL_ID, where every post here comes from.
    # Since H3 a shop indexes only its own channel_id; see
    # test_indexer_channel_scope.py for the posts that must be refused.
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


# --- 1. the simple case ----------------------------------------------------


async def test_a_single_photo_with_a_hashtag_is_indexed(world: World) -> None:
    await world.post(
        message_id=101,
        file_id="AgACphoto101",
        caption="Qizil atirgul buketi\nNarxi: 450 000 so'm\n#atirgul",
    )

    row = await world.only_product()
    assert row.name == "Qizil atirgul buketi"
    assert row.price_uzs == 450_000
    assert row.price_confidence == "high"
    assert row.telegram_file_id == "AgACphoto101", "the LARGEST photo size must be kept"
    assert row.channel_message_id == 101
    assert row.channel_chat_id == CHANNEL_ID
    assert row.finalized_at is not None
    assert await world.tags(row.id) == ["atirgul"]
    assert world.scheduled == [], "a single post does not need the album debounce"


async def test_a_channel_post_creates_no_customer(world: World) -> None:
    """A channel has no `from_user`. CP2's middleware must not invent one."""
    await world.post(message_id=102, file_id="f102", caption="#atirgul")

    count = (
        await world.db.execute(
            text("SELECT count(*) FROM customers WHERE shop_id = :s"), {"s": world.shop_id}
        )
    ).scalar_one()
    assert count == 0


# --- 2 and 3. the album, in order and shuffled -----------------------------

#: Five photos, caption on message 201 -- the first POSTED. Message ids are the
#: order Telegram assigned; the delivery order is what each test varies.
ALBUM_CAPTION = "Oq atirgul 101 ta\nNarxi 1 200 000 so'm\n#atirgul #katta"
ALBUM_IDS = (201, 202, 203, 204, 205)


async def deliver(world: World, order: tuple[int, ...]) -> None:
    for update_id, message_id in enumerate(order, start=1):
        await world.post(
            update_id=update_id,
            message_id=message_id,
            file_id=f"file{message_id}",
            media_group_id=ALBUM,
            caption=ALBUM_CAPTION if message_id == 201 else None,
        )


async def assert_album_landed_correctly(world: World) -> None:
    row = await world.only_product()
    assert row.caption_raw == ALBUM_CAPTION
    assert row.channel_message_id == 201, "the anchor must be the earliest message"
    assert row.telegram_file_id == "file201", "the anchor photo must follow the anchor message"
    assert row.name == "Oq atirgul 101 ta"
    assert row.price_uzs == 1_200_000
    assert row.finalized_at is not None
    assert await world.tags(row.id) == ["atirgul", "katta"]


async def test_an_album_delivered_in_order_becomes_one_product(world: World) -> None:
    await deliver(world, ALBUM_IDS)
    assert len(await world.products()) == 1, "five updates must not make five products"

    await world.settle(ALBUM)
    await assert_album_landed_correctly(world)


async def test_an_album_delivered_shuffled_becomes_the_same_one_product(world: World) -> None:
    """The caption-bearing post arrives LAST.

    This is the case that tests the race rather than the grouping rule: four
    captionless photos have already created and merged onto a row by the time
    the only caption in the album shows up.
    """
    await deliver(world, (204, 202, 205, 203, 201))
    assert len(await world.products()) == 1

    await world.settle(ALBUM)
    await assert_album_landed_correctly(world)


async def test_an_album_with_the_caption_in_the_middle_lands_the_same_way(world: World) -> None:
    """Neither first nor last, and the strictest of the three orderings.

    Mutation-checked: "caption arrives last" cannot catch a merge that takes the
    LATEST caption, and it cannot catch an anchor that takes the LATEST message,
    because in that ordering the latest is also the right one. Two captionless
    photos arriving after the caption is what makes both mutations visible.
    """
    await deliver(world, (204, 202, 201, 205, 203))
    assert len(await world.products()) == 1

    await world.settle(ALBUM)
    await assert_album_landed_correctly(world)


async def test_the_album_row_is_provisional_until_it_settles(world: World) -> None:
    """Until finalize runs there is a row, and it is honestly marked unfinished."""
    await world.post(message_id=202, file_id="file202", media_group_id=ALBUM)

    row = await world.only_product()
    assert row.finalized_at is None
    assert await world.tags(row.id) == []
    assert world.scheduled == [ALBUM]


async def test_five_arrivals_ask_for_the_debounce_five_times(world: World) -> None:
    """The handler always asks; COLLAPSING those asks is the debouncer's job,
    and testing it here would test the recorder instead."""
    await deliver(world, ALBUM_IDS)
    assert world.scheduled == [ALBUM] * 5


# --- 5 and 6. the gate -----------------------------------------------------


async def test_a_photo_with_no_hashtag_is_ignored(world: World) -> None:
    await world.post(message_id=301, file_id="f301", caption="Bugun dam olamiz, xayrli kun!")
    assert await world.products() == []


async def test_an_untagged_photo_is_never_written_at_all(world: World) -> None:
    """ "Do not create a row" -- not "create one and tidy it up afterwards".

    MUTATION-CHECKED, and this is why the test exists in this shape: deleting
    the arrival gate leaves the end state identical, because finalize would drop
    the untagged row anyway. Only the id sequence, which a deleted row has
    already consumed, can tell the two apart.
    """
    before = await world.product_id_sequence()

    await world.post(message_id=305, file_id="f305", caption="Bugun dam olamiz!")

    assert await world.products() == []
    assert await world.product_id_sequence() == before, "a row was inserted and then deleted"


async def test_a_photo_with_no_caption_at_all_is_ignored(world: World) -> None:
    await world.post(message_id=302, file_id="f302")
    assert await world.products() == []


async def test_a_hashtag_with_no_photo_is_ignored(world: World) -> None:
    """Refused by the router's filter, before a session is even used."""
    await world.post(message_id=303, text="Yangi kelgan gullar #atirgul")
    assert await world.products() == []


async def test_a_digit_only_hashtag_does_not_count_as_a_hashtag(world: World) -> None:
    """`#150000` is a price, and CP7's normaliser returns "" for it."""
    await world.post(message_id=304, file_id="f304", caption="#150000")
    assert await world.products() == []


async def test_an_album_with_no_hashtag_anywhere_leaves_nothing_behind(world: World) -> None:
    """The gate cannot be applied on arrival for an album, so it is applied at
    finalize -- and the provisional row is deleted rather than left orphaned."""
    for message_id in (401, 402):
        await world.post(
            message_id=message_id,
            file_id=f"f{message_id}",
            media_group_id="untagged-album",
            caption="Rahmat!" if message_id == 401 else None,
        )
    assert len(await world.products()) == 1

    result = await world.settle("untagged-album")
    assert result.outcome is Finalize.DROPPED
    assert await world.products() == []


async def test_a_caption_arriving_after_its_album_was_dropped_still_indexes(world: World) -> None:
    """Self-healing, and the reason DROPPED deletes rather than deactivates.

    A member arriving late re-inserts the group from scratch; nothing has to
    remember that it was previously discarded.
    """
    await world.post(message_id=402, file_id="f402", media_group_id="late-album")
    assert (await world.settle("late-album")).outcome is Finalize.DROPPED

    await world.post(message_id=401, file_id="f401", media_group_id="late-album", caption="#lola")
    assert (await world.settle("late-album")).outcome is Finalize.FINALIZED

    row = await world.only_product()
    assert row.channel_message_id == 401
    assert await world.tags(row.id) == ["lola"]


# --- 7. several hashtags ---------------------------------------------------


async def test_one_post_with_several_hashtags_gets_several_tag_rows(world: World) -> None:
    await world.post(
        message_id=501,
        file_id="f501",
        caption="Sevimli buket\n#atirgul #lola #tugilgankun #sovga",
    )
    row = await world.only_product()
    assert await world.tags(row.id) == ["atirgul", "lola", "sovga", "tugilgankun"]


async def test_the_display_name_does_not_repeat_the_hashtags(world: World) -> None:
    await world.post(message_id=502, file_id="f502", caption="Bahor buketi #atirgul #lola")
    row = await world.only_product()
    assert row.name == "Bahor buketi"


async def test_a_caption_that_is_only_hashtags_falls_back_to_the_first_tag(world: World) -> None:
    """`name` is NOT NULL and a hashtag-only caption is a real post shape."""
    await world.post(message_id=503, file_id="f503", caption="#atirgul #lola")
    row = await world.only_product()
    assert row.name == "atirgul"


# --- 8. edits --------------------------------------------------------------


async def test_an_edit_changing_the_price_updates_the_same_row(world: World) -> None:
    await world.post(message_id=601, file_id="f601", caption="Buket\nNarxi 300 000 so'm\n#atirgul")
    before = await world.only_product()
    assert before.price_uzs == 300_000
    assert before.price_confidence == "high"

    await world.edit(message_id=601, file_id="f601", caption="Buket\nNarxi 350 000 so'm\n#atirgul")

    after = await world.only_product()
    assert after.id == before.id, "an edit must never create a second product"
    assert after.price_uzs == 350_000
    assert after.price_confidence == "high"


async def test_an_edit_that_removes_the_price_lowers_the_confidence(world: World) -> None:
    await world.post(message_id=602, file_id="f602", caption="Buket 300 000 so'm #atirgul")
    assert (await world.only_product()).price_confidence == "high"

    await world.edit(message_id=602, file_id="f602", caption="Buket, narxi kelishiladi #atirgul")

    row = await world.only_product()
    assert row.price_uzs is None
    assert row.price_confidence == "none"


async def test_an_edit_resyncs_the_hashtags_in_both_directions(world: World) -> None:
    await world.post(message_id=603, file_id="f603", caption="Buket #atirgul #lola")
    product_id = (await world.only_product()).id
    assert await world.tags(product_id) == ["atirgul", "lola"]

    await world.edit(message_id=603, file_id="f603", caption="Buket #atirgul #chinnigul")

    assert await world.tags(product_id) == ["atirgul", "chinnigul"]


async def test_an_edit_on_an_album_finds_it_by_media_group_not_message_id(world: World) -> None:
    """Telegram sends the edit for the message that changed, which need not be
    the anchor. Looking it up by message id would create a second product."""
    await deliver(world, ALBUM_IDS)
    await world.settle(ALBUM)
    before = await world.only_product()

    await world.edit(
        message_id=203,
        file_id="file203",
        media_group_id=ALBUM,
        caption="Oq atirgul 101 ta\nNarxi 1 500 000 so'm\n#atirgul #katta",
    )

    after = await world.only_product()
    assert after.id == before.id
    assert after.price_uzs == 1_500_000


async def test_an_edit_that_first_adds_a_hashtag_indexes_the_post(world: World) -> None:
    """It was correctly ignored when posted; the edit is when it first qualifies."""
    await world.post(message_id=604, file_id="f604", caption="Yangi buket")
    assert await world.products() == []

    await world.edit(message_id=604, file_id="f604", caption="Yangi buket #atirgul")

    row = await world.only_product()
    assert await world.tags(row.id) == ["atirgul"]


async def test_an_edit_stripping_every_hashtag_deactivates_rather_than_deletes(
    world: World,
) -> None:
    """It was a live product once. Hiding it is proportionate; deleting is not."""
    await world.post(message_id=605, file_id="f605", caption="Buket #atirgul")
    product_id = (await world.only_product()).id

    await world.edit(message_id=605, file_id="f605", caption="Buket")

    row = await world.only_product()
    assert row.id == product_id
    assert row.active is False


# --- 9. the unpriced post --------------------------------------------------


async def test_an_unpriced_post_is_indexed_anyway(world: World) -> None:
    """A named requirement, and the easiest thing in this checkpoint to get
    wrong by accident: gating on a price would silently hide half a catalogue.
    """
    await world.post(
        message_id=701, file_id="f701", caption="Katta buket, narxi kelishiladi\n#atirgul"
    )

    row = await world.only_product()
    assert row.price_uzs is None
    assert row.price_confidence == "none"
    assert row.finalized_at is not None, "unpriced is indexed, not deferred"
    assert await world.tags(row.id) == ["atirgul"]


async def test_a_phone_number_is_not_mistaken_for_a_price(world: World) -> None:
    """CP7's masking, reached through the real handler this time."""
    await world.post(
        message_id=702, file_id="f702", caption="Buyurtma: +998 90 123 45 67\n#atirgul"
    )
    row = await world.only_product()
    assert row.price_uzs is None


# --- 10. finalize is idempotent -------------------------------------------


async def test_finalizing_twice_is_a_verified_no_op_the_second_time(world: World) -> None:
    """The real safety net. Debounce collapsing is not airtight against every
    race, so finalize has to be safe to run again on its own."""
    await deliver(world, ALBUM_IDS)

    first = await world.settle(ALBUM)
    assert first.outcome is Finalize.FINALIZED
    before = await world.only_product()
    tags_before = await world.tags(before.id)

    second = await world.settle(ALBUM)

    assert second.outcome is Finalize.NOOP
    after = await world.only_product()
    assert after.id == before.id
    assert after.finalized_at == before.finalized_at, "the stamp moved on a no-op"
    assert after.indexed_at == before.indexed_at
    assert await world.tags(after.id) == tags_before
    assert len(tags_before) == 2, "guards the guard: a tagless product proves nothing"


async def test_finalizing_a_group_that_does_not_exist_says_so(world: World) -> None:
    assert (await world.settle("no-such-album")).outcome is Finalize.MISSING


async def test_a_redelivered_single_post_does_not_create_a_twin(world: World) -> None:
    """Telegram may deliver the same channel_post twice."""
    for update_id in (1, 2):
        await world.post(
            update_id=update_id, message_id=801, file_id="f801", caption="Buket #atirgul"
        )

    row = await world.only_product()
    assert await world.tags(row.id) == ["atirgul"]
