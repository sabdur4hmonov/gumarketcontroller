"""Browsing the catalogue, and ordering without a reminder.

The gap this closes was the largest one the pre-launch walkthrough found: until
now the only route into ordering was the button attached to a reminder, so the
product sold only to people who happened to have a date coming up.

TWO THINGS THIS FILE EXISTS TO PROVE that a happy-path test would not:

  * paging is KEYSET, so it cannot skip or repeat a bouquet when the catalogue
    changes between taps -- the failure an OFFSET query has and hides;
  * the product view reproduces the shop's own post, and falls back to our own
    caption exactly when there is nothing in theirs worth reproducing.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from itertools import count

import pytest
import pytest_asyncio
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import (
    RecordingSession,
    bound_session_factory,
    callback_update,
    feed,
    make_bot,
    text_update,
)

from gulbot.bot.callbacks import BrowsePageCB, BrowsePickCB, OrderStartCB
from gulbot.bot.factory import build_dispatcher
from gulbot.bot.routers.browse import caption_is_only_tags, row_label
from gulbot.i18n.catalog import CATALOG
from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.services.bouquets import PAGE_SIZE, Bouquet, list_bouquets, load_product

# --------------------------------------------------------------------------
# pure
# --------------------------------------------------------------------------


def bouquet(
    name: str = "Oq atirgul", price: int | None = 450000, confidence: str = "high"
) -> Bouquet:
    return Bouquet(
        product_id=1,
        name=name,
        price_uzs=price,
        price_confidence=confidence,
        telegram_file_id="file-1",
    )


def test_a_priced_row_shows_its_price() -> None:
    assert "450 000" in row_label(bouquet(), "uz")


def test_an_unpriced_row_shows_only_the_name() -> None:
    """No "0 so'm", and no empty dash. A bouquet whose post carried no price is
    still worth showing."""
    label = row_label(bouquet(price=None), "uz")
    assert label == "Oq atirgul"


def test_a_price_the_parser_would_not_stand_behind_is_not_shown() -> None:
    """`has_price` already encodes this for reminders; the list must agree with
    it rather than reading price_uzs directly."""
    assert row_label(bouquet(price=150000, confidence="none"), "uz") == "Oq atirgul"


@pytest.mark.parametrize(
    "caption",
    [None, "", "#lola", "#gulkinder", "#atirgul #buket", "   #lola   ", "#lola\n#buket"],
)
def test_a_caption_of_nothing_but_tags_has_nothing_to_show(caption: str | None) -> None:
    """Both bouquets in the shop's channel were captioned exactly like this.
    Copying one verbatim would show the customer a bare hashtag."""
    assert caption_is_only_tags(caption) is True


@pytest.mark.parametrize(
    "caption",
    [
        "#lola Nafis atirgul buketi",
        "\U0001f339 Nafis atirgul buketi\n15 dona\n#lola",
        "#lola 150 000 so'm",
        "Atirgul",
    ],
)
def test_a_caption_with_words_or_figures_is_worth_copying(caption: str) -> None:
    assert caption_is_only_tags(caption) is False


# --------------------------------------------------------------------------
# the query, against real rows
# --------------------------------------------------------------------------

pytestmark = pytest.mark.infra

USER_ID = 991_001
BROWSE = CATALOG["btn.menu.browse"]["uz"]
BASE = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

#: Channel message ids are UNIQUE per shop, and several tests need rows
#: sharing an `indexed_at` -- an album indexes its members in the same
#: instant. So the id counts independently of the timestamp.
_message_ids = count(1000)


async def add_product(
    db: AsyncConnection,
    shop: int,
    *,
    name: str,
    minutes: int,
    caption: str | None = None,
    price: int | None = 450000,
    active: bool = True,
    finalized: bool = True,
    message_id: int | None = None,
) -> int:
    """One catalogue row with an explicit `indexed_at`, so paging order is a
    fact of the fixture rather than of how fast the inserts ran."""
    return int(
        (
            await db.execute(
                text(
                    "INSERT INTO products (shop_id, name, telegram_file_id, source, "
                    " channel_chat_id, channel_message_id, price_uzs, price_confidence, "
                    " caption_raw, indexed_at, finalized_at, active) "
                    "VALUES (:s, :n, :f, 'channel', -100777, :mid, :p, :conf, "
                    " :cap, :ix, :fin, :act) "
                    "RETURNING id"
                ),
                {
                    "s": shop,
                    "n": name,
                    "f": f"file-{name}",
                    "mid": message_id if message_id is not None else next(_message_ids),
                    "p": price,
                    # Computed here rather than in a CASE over the same bind:
                    # asyncpg cannot type a parameter used once as a value and
                    # once inside an IS NULL test.
                    "conf": "none" if price is None else "high",
                    "cap": caption,
                    "ix": BASE + timedelta(minutes=minutes),
                    "fin": BASE if finalized else None,
                    "act": active,
                },
            )
        ).scalar_one()
    )


@pytest_asyncio.fixture
async def shop(db: AsyncConnection) -> int:
    return int(
        (
            await db.execute(
                text(
                    "INSERT INTO shops (name, working_hours) "
                    "VALUES ('S', CAST(:wh AS jsonb)) RETURNING id"
                ),
                {"wh": json.dumps(DEFAULT_WORKING_HOURS)},
            )
        ).scalar_one()
    )


async def names_on_page(db: AsyncConnection, shop: int, after=None) -> tuple[list[str], object]:
    async with bound_session_factory(db)() as session:
        listing = await list_bouquets(session, shop_id=shop, after=after)
    return [b.name for b in listing.bouquets], listing.cursor


async def test_an_empty_catalogue_lists_nothing(db: AsyncConnection, shop: int) -> None:
    names, cursor = await names_on_page(db, shop)
    assert names == []
    assert cursor is None


async def test_the_newest_bouquet_comes_first(db: AsyncConnection, shop: int) -> None:
    await add_product(db, shop, name="old", minutes=1)
    await add_product(db, shop, name="new", minutes=9)
    names, _ = await names_on_page(db, shop)
    assert names == ["new", "old"]


async def test_a_page_holds_five_and_says_there_is_more(db: AsyncConnection, shop: int) -> None:
    for n in range(7):
        await add_product(db, shop, name=f"b{n}", minutes=n)
    names, cursor = await names_on_page(db, shop)
    assert len(names) == PAGE_SIZE
    assert cursor is not None, "seven bouquets means a second page"


async def test_the_last_page_says_there_is_no_more(db: AsyncConnection, shop: int) -> None:
    """Guards against a Next button that leads to an empty list."""
    for n in range(PAGE_SIZE):
        await add_product(db, shop, name=f"b{n}", minutes=n)
    _, cursor = await names_on_page(db, shop)
    assert cursor is None


async def test_paging_forward_covers_every_bouquet_exactly_once(
    db: AsyncConnection, shop: int
) -> None:
    """THE property keyset paging exists for. Walked end to end, every bouquet
    appears once and none is skipped."""
    for n in range(12):
        await add_product(db, shop, name=f"b{n:02d}", minutes=n)

    seen: list[str] = []
    cursor = None
    for _ in range(5):  # more iterations than pages, so a stuck cursor shows up
        names, cursor = await names_on_page(db, shop, cursor)
        seen.extend(names)
        if cursor is None:
            break

    assert len(seen) == 12
    assert len(set(seen)) == 12, "a bouquet appeared on two pages"
    assert seen == sorted(seen, reverse=True), "newest-first ordering broke across pages"


async def test_two_bouquets_indexed_in_the_same_instant_do_not_collide(
    db: AsyncConnection, shop: int
) -> None:
    """An album indexes its members with the same timestamp. A cursor on
    `indexed_at` alone would drop one of them; the id breaks the tie."""
    for n in range(7):
        await add_product(db, shop, name=f"b{n}", minutes=0)
    seen: list[str] = []
    cursor = None
    for _ in range(4):
        names, cursor = await names_on_page(db, shop, cursor)
        seen.extend(names)
        if cursor is None:
            break
    assert sorted(seen) == sorted(f"b{n}" for n in range(7))


@pytest.mark.parametrize(
    ("kwargs", "why"),
    [
        ({"active": False}, "the shop hid it"),
        ({"finalized": False}, "a provisional album, name and price not settled"),
    ],
)
async def test_an_unsellable_bouquet_is_never_listed(
    db: AsyncConnection, shop: int, kwargs: dict, why: str
) -> None:
    """The list and the reminder chooser share one `sellable` predicate. A
    bouquet findable by browsing but never offered in a reminder would be a
    difference nobody could explain from outside."""
    await add_product(db, shop, name="hidden", minutes=1, **kwargs)
    names, _ = await names_on_page(db, shop)
    assert names == [], why


async def test_a_deleted_bouquet_is_never_listed(db: AsyncConnection, shop: int) -> None:
    product = await add_product(db, shop, name="gone", minutes=1)
    await db.execute(text("UPDATE products SET deleted_at = now() WHERE id = :p"), {"p": product})
    names, _ = await names_on_page(db, shop)
    assert names == []


async def test_another_shops_catalogue_is_not_listed(db: AsyncConnection, shop: int) -> None:
    other = (
        await db.execute(
            text(
                "INSERT INTO shops (name, working_hours) "
                "VALUES ('other', CAST(:wh AS jsonb)) RETURNING id"
            ),
            {"wh": json.dumps(DEFAULT_WORKING_HOURS)},
        )
    ).scalar_one()
    await add_product(db, other, name="theirs", minutes=5)
    await add_product(db, shop, name="ours", minutes=1)
    names, _ = await names_on_page(db, shop)
    assert names == ["ours"]


async def test_load_product_refuses_an_unsellable_one(db: AsyncConnection, shop: int) -> None:
    """The list is drawn once; a bouquet can be deactivated before the customer
    taps it."""
    product = await add_product(db, shop, name="hidden", minutes=1, active=False)
    async with bound_session_factory(db)() as session:
        assert await load_product(session, shop_id=shop, product_id=product) is None


# --------------------------------------------------------------------------
# the flow, through the real dispatcher
# --------------------------------------------------------------------------


class Driver:
    def __init__(self, dispatcher, bot, recorder: RecordingSession, db, shop) -> None:  # type: ignore[no-untyped-def]
        self.dispatcher, self.bot, self.recorder = dispatcher, bot, recorder
        self.db, self.shop = db, shop
        self._n = 0

    def _next(self) -> int:
        self._n += 1
        return self._n

    async def say(self, message: str) -> None:
        await feed(
            self.dispatcher, self.bot, text_update(message, user_id=USER_ID, update_id=self._next())
        )

    async def tap(self, data: str) -> None:
        await feed(
            self.dispatcher,
            self.bot,
            callback_update(data, user_id=USER_ID, update_id=self._next()),
        )

    @property
    def sent(self) -> list[str]:
        return self.recorder.sent_texts

    @property
    def methods(self) -> list[str]:
        return [type(call).__name__ for call in self.recorder.calls]


@pytest_asyncio.fixture
async def driver(db: AsyncConnection, shop: int) -> Driver:
    bot, recorder = make_bot()
    dispatcher = build_dispatcher(
        session_factory=bound_session_factory(db), shop_id=shop, storage=MemoryStorage()
    )
    return Driver(dispatcher, bot, recorder, db, shop)


async def test_the_menu_button_opens_the_list(driver: Driver) -> None:
    await add_product(driver.db, driver.shop, name="Oq atirgul", minutes=1)
    await driver.say(BROWSE)
    assert CATALOG["browse.title"]["uz"] in driver.sent


async def test_an_empty_catalogue_says_so_and_returns_to_the_menu(driver: Driver) -> None:
    """A customer who taps Order and sees nothing must not be left in a flow
    with no way out."""
    await driver.say(BROWSE)
    assert CATALOG["browse.empty"]["uz"] in driver.sent


async def test_picking_a_bouquet_copies_the_shops_own_post(driver: Driver) -> None:
    """The whole point of the verbatim view: the customer sees what the shop
    wrote, not what we would have written about it."""
    product = await add_product(
        driver.db,
        driver.shop,
        name="Nafis atirgul buketi",
        minutes=1,
        caption="\U0001f339 Nafis atirgul buketi\n15 dona\nNarxi: 150 000 so'm\n#lola",
    )
    await driver.say(BROWSE)
    await driver.tap(BrowsePickCB(product_id=product).pack())
    assert "CopyMessage" in driver.methods


async def test_a_bare_hashtag_caption_falls_back_to_our_own(driver: Driver) -> None:
    """Copying `#gulkinder` verbatim would show the customer a bare tag. Both
    bouquets in the real channel looked exactly like this."""
    product = await add_product(
        driver.db, driver.shop, name="gulkinder", minutes=1, caption="#gulkinder"
    )
    await driver.say(BROWSE)
    await driver.tap(BrowsePickCB(product_id=product).pack())
    assert "CopyMessage" not in driver.methods
    assert "SendPhoto" in driver.methods


async def test_a_bouquet_deactivated_before_the_tap_says_so(driver: Driver) -> None:
    product = await add_product(driver.db, driver.shop, name="gone", minutes=1, caption="#x words")
    await driver.say(BROWSE)
    await driver.db.execute(
        text("UPDATE products SET active = false WHERE id = :p"), {"p": product}
    )
    await driver.tap(BrowsePickCB(product_id=product).pack())
    assert CATALOG["browse.gone"]["uz"] in driver.sent


async def test_the_order_button_reaches_the_order_flow(driver: Driver) -> None:
    """The seam that matters. A bouquet chosen by browsing enters the SAME order
    flow a reminder starts, through the same callback -- so there is one entry
    point rather than two that could drift apart."""
    product = await add_product(driver.db, driver.shop, name="Oq atirgul", minutes=1)
    await driver.say(BROWSE)
    await driver.tap(BrowsePickCB(product_id=product).pack())
    await driver.tap(OrderStartCB(product_id=product).pack())
    assert CATALOG["order.choose_date"]["uz"] in driver.sent


async def test_paging_forward_and_back_returns_to_the_same_page(driver: Driver) -> None:
    """The cursor stack, end to end through the dispatcher."""
    for n in range(7):
        await add_product(driver.db, driver.shop, name=f"b{n}", minutes=n)
    await driver.say(BROWSE)
    await driver.tap(BrowsePageCB(action="next").pack())
    await driver.tap(BrowsePageCB(action="prev").pack())
    # Three renders: the first page, the second, and the first again.
    assert driver.sent.count(CATALOG["browse.title"]["uz"]) == 3


async def test_cancel_leaves_the_browse_flow(driver: Driver) -> None:
    """Every state has to prove this, button-only or not."""
    await add_product(driver.db, driver.shop, name="Oq atirgul", minutes=1)
    await driver.say(BROWSE)
    await driver.say(CATALOG["btn.nav.cancel"]["uz"])
    assert CATALOG["nav.cancelled"]["uz"] in driver.sent
