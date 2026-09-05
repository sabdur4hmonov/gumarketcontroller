"""The order FSM, driven through the REAL dispatcher.

Everything goes through `Dispatcher.feed_update`, so middlewares, router order
and filters run exactly as in production. Calling the service directly would
prove the service works and nothing about whether a customer can reach it.

TWO THINGS THIS FILE EXISTS TO PROVE that a happy-path test would not:

* NOTHING is written to `orders` until the confirmation is tapped. The flow can
  be abandoned at any step and the database is untouched.
* Cancel and /start still win from the two text-waiting states. That is the
  behavioural half of the nav proof; the exhaustive half lives in
  test_nav_precedence.py and covers these states automatically, because it
  enumerates `declared_states()`.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

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
    location_update,
    make_bot,
    text_update,
)

from gulbot.bot.callbacks import (
    OrderConfirmCB,
    OrderDateCB,
    OrderHourCB,
    OrderLocationCB,
    OrderStartCB,
)
from gulbot.bot.factory import build_dispatcher
from gulbot.i18n.catalog import CATALOG
from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.scheduling.occurrences import TASHKENT

pytestmark = pytest.mark.infra

USER_ID = 970_001
CANCEL = next(iter(CATALOG["btn.nav.cancel"].values()))


class Driver:
    """One customer, one product, one dispatcher."""

    def __init__(self, dispatcher, bot, recorder: RecordingSession, db, shop, product) -> None:  # type: ignore[no-untyped-def]
        self.dispatcher, self.bot, self.recorder = dispatcher, bot, recorder
        self.db, self.shop, self.product = db, shop, product
        self._update = 0

    def _next(self) -> int:
        self._update += 1
        return self._update

    async def tap(self, data: str) -> None:
        await feed(
            self.dispatcher,
            self.bot,
            callback_update(data, user_id=USER_ID, update_id=self._next()),
        )

    async def say(self, message: str) -> None:
        await feed(
            self.dispatcher, self.bot, text_update(message, user_id=USER_ID, update_id=self._next())
        )

    async def pin(self, lat: float, lon: float) -> None:
        await feed(
            self.dispatcher,
            self.bot,
            location_update(user_id=USER_ID, latitude=lat, longitude=lon, update_id=self._next()),
        )

    @property
    def sent(self) -> list[str]:
        return self.recorder.sent_texts

    async def orders(self) -> list:
        return (
            await self.db.execute(
                text(
                    "SELECT id, delivery_date, delivery_hour, delivery_location_text, "
                    " delivery_location_lat, delivery_location_lon, landmark, status, "
                    " product_name_snapshot, price_uzs_snapshot, product_id, recipient_id "
                    "FROM orders WHERE shop_id = :s"
                ),
                {"s": self.shop},
            )
        ).all()

    async def start(self) -> None:
        await self.tap(OrderStartCB(product_id=self.product).pack())

    async def through_to_landmark(self, *, pin: bool = False) -> None:
        """Date -> hour -> location -> (address | pin). Stops before landmark."""
        await self.start()
        # Tomorrow, so the lead time can never make the picker empty.
        await self.tap(OrderDateCB(offset=1).pack())
        await self.tap(OrderHourCB(hour=14).pack())
        await self.tap(OrderLocationCB(mode="pin" if pin else "text").pack())
        if pin:
            await self.pin(41.31, 69.24)
        else:
            await self.say("Chilonzor 5, 12-uy")


@pytest_asyncio.fixture
async def driver(db: AsyncConnection) -> Driver:
    shop = (
        await db.execute(
            text(
                "INSERT INTO shops (name, working_hours) "
                "VALUES ('S', CAST(:wh AS jsonb)) RETURNING id"
            ),
            {"wh": json.dumps(DEFAULT_WORKING_HOURS)},
        )
    ).scalar_one()
    product = (
        await db.execute(
            text(
                "INSERT INTO products (shop_id, name, telegram_file_id, source, "
                " channel_message_id, price_uzs, price_confidence, finalized_at) "
                "VALUES (:s, 'Oq atirgul', 'file-1', 'channel', 1, 450000, 'high', now()) "
                "RETURNING id"
            ),
            {"s": shop},
        )
    ).scalar_one()
    sessions = bound_session_factory(db)
    bot, recorder = make_bot()
    dispatcher = build_dispatcher(session_factory=sessions, shop_id=shop, storage=MemoryStorage())
    return Driver(dispatcher, bot, recorder, db, shop, product)


# --- the happy paths -------------------------------------------------------


async def test_a_written_address_order_reaches_the_database(driver: Driver) -> None:
    await driver.through_to_landmark()
    await driver.say("Ko'k eshik")
    await driver.tap(OrderConfirmCB(action="submit").pack())

    rows = await driver.orders()
    assert len(rows) == 1
    order = rows[0]
    assert order.delivery_date == date.today() + timedelta(days=1)
    assert order.delivery_hour.hour == 14
    assert order.delivery_location_text == "Chilonzor 5, 12-uy"
    assert order.delivery_location_lat is None
    assert order.landmark == "Ko'k eshik"
    assert order.status == "placed"
    # Frozen from the product, not carried from the button.
    assert order.product_name_snapshot == "Oq atirgul"
    assert order.price_uzs_snapshot == 450_000


async def test_a_dropped_pin_order_reaches_the_database(driver: Driver) -> None:
    await driver.through_to_landmark(pin=True)
    await driver.say("Do'kon yonida")
    await driver.tap(OrderConfirmCB(action="submit").pack())

    rows = await driver.orders()
    assert len(rows) == 1
    assert rows[0].delivery_location_text is None
    assert rows[0].delivery_location_lat == pytest.approx(41.31)
    assert rows[0].delivery_location_lon == pytest.approx(69.24)


async def test_the_landmark_is_asked_after_a_pin_too(driver: Driver) -> None:
    """Deliberate: a dropped pin still benefits from "the blue gate" in
    Uzbekistan's addressing reality. Not asking would be the easy shortcut."""
    await driver.through_to_landmark(pin=True)
    assert CATALOG["order.enter_landmark"]["uz"] in driver.sent


async def test_the_customer_is_told_the_order_was_accepted(driver: Driver) -> None:
    await driver.through_to_landmark()
    await driver.say("Ko'k eshik")
    await driver.tap(OrderConfirmCB(action="submit").pack())
    assert any("qabul qilindi" in message for message in driver.sent)


async def test_an_unpriced_bouquet_uses_the_operator_wording(driver: Driver) -> None:
    """The exact existing string, not a second copy of it."""
    await driver.db.execute(
        text("UPDATE products SET price_uzs = NULL, price_confidence = 'none' WHERE id = :p"),
        {"p": driver.product},
    )
    await driver.through_to_landmark()
    await driver.say("Ko'k eshik")
    assert any("narx operator tomonidan tasdiqlanadi" in m for m in driver.sent)


async def test_a_priced_bouquet_shows_its_price(driver: Driver) -> None:
    await driver.through_to_landmark()
    await driver.say("Ko'k eshik")
    assert any("450 000" in m for m in driver.sent)


# --- nothing is written before the tap -------------------------------------


@pytest.mark.parametrize("stop_after", ["start", "date", "hour", "location", "landmark"])
async def test_no_order_exists_before_the_confirmation(driver: Driver, stop_after: str) -> None:
    await driver.start()
    if stop_after != "start":
        await driver.tap(OrderDateCB(offset=1).pack())
    if stop_after in {"hour", "location", "landmark"}:
        await driver.tap(OrderHourCB(hour=14).pack())
    if stop_after in {"location", "landmark"}:
        await driver.tap(OrderLocationCB(mode="text").pack())
        await driver.say("Chilonzor 5")
    if stop_after == "landmark":
        await driver.say("Ko'k eshik")

    assert await driver.orders() == [], "an order was written before the customer confirmed"


async def test_declining_the_confirmation_writes_nothing(driver: Driver) -> None:
    await driver.through_to_landmark()
    await driver.say("Ko'k eshik")
    await driver.tap(OrderConfirmCB(action="discard").pack())
    assert await driver.orders() == []


# --- the escape hatches, behaviourally -------------------------------------


@pytest.mark.parametrize("state_name", ["address", "landmark"])
async def test_cancel_wins_from_both_text_waiting_states(driver: Driver, state_name: str) -> None:
    """The two states where a careless catch-all would swallow Cancel."""
    await driver.start()
    await driver.tap(OrderDateCB(offset=1).pack())
    await driver.tap(OrderHourCB(hour=14).pack())
    await driver.tap(OrderLocationCB(mode="text").pack())
    if state_name == "landmark":
        await driver.say("Chilonzor 5")

    await driver.say(CANCEL)

    assert CATALOG["nav.cancelled"]["uz"] in driver.sent
    assert await driver.orders() == []


@pytest.mark.parametrize("state_name", ["address", "landmark"])
async def test_start_wins_from_both_text_waiting_states(driver: Driver, state_name: str) -> None:
    await driver.start()
    await driver.tap(OrderDateCB(offset=1).pack())
    await driver.tap(OrderHourCB(hour=14).pack())
    await driver.tap(OrderLocationCB(mode="text").pack())
    if state_name == "landmark":
        await driver.say("Chilonzor 5")

    await driver.say("/start")

    assert await driver.orders() == []
    assert driver.sent[-1] != CATALOG["order.enter_landmark"]["uz"]


async def test_an_empty_landmark_is_refused_rather_than_stored(driver: Driver) -> None:
    await driver.through_to_landmark()
    await driver.say("   ")
    assert CATALOG["order.landmark_empty"]["uz"] in driver.sent
    assert await driver.orders() == []


async def test_a_landmark_is_sanitised_with_cp3s_sanitiser(driver: Driver) -> None:
    """Reused verbatim, not reimplemented: control characters go, whitespace
    collapses, and a tab does not fuse two words."""
    await driver.through_to_landmark()
    await driver.say("Ko'k\teshik​   yonida")
    await driver.tap(OrderConfirmCB(action="submit").pack())
    assert (await driver.orders())[0].landmark == "Ko'k eshik yonida"


# --- back, per state -------------------------------------------------------


async def test_back_from_the_hour_step_returns_to_the_dates(driver: Driver) -> None:
    await driver.start()
    await driver.tap(OrderDateCB(offset=1).pack())
    driver.recorder.calls.clear()
    await driver.tap("ordback:back")
    assert CATALOG["order.choose_date"]["uz"] in driver.sent


async def test_back_from_the_confirmation_returns_to_the_location_choice(
    driver: Driver,
) -> None:
    await driver.through_to_landmark()
    await driver.say("Ko'k eshik")
    driver.recorder.calls.clear()
    await driver.tap("ordback:back")
    assert CATALOG["order.choose_location"]["uz"] in driver.sent
    assert await driver.orders() == []


async def test_an_unknown_product_ends_the_flow_politely(driver: Driver) -> None:
    """A bouquet deleted between the reminder and the tap."""
    await driver.db.execute(text("DELETE FROM products WHERE id = :p"), {"p": driver.product})
    await driver.start()
    assert CATALOG["order.gone"]["uz"] in driver.sent
    assert await driver.orders() == []


# --- pings are scheduled with the order ------------------------------------


async def test_submitting_schedules_the_admin_pings(driver: Driver) -> None:
    await driver.through_to_landmark()
    await driver.say("Ko'k eshik")
    await driver.tap(OrderConfirmCB(action="submit").pack())

    order = (await driver.orders())[0]
    pings = (
        await driver.db.execute(
            text(
                "SELECT ping_number, due_at_utc, state FROM order_reminders "
                "WHERE order_id = :o ORDER BY ping_number"
            ),
            {"o": order.id},
        )
    ).all()
    assert [p.ping_number for p in pings] == [1, 2]
    assert {p.state for p in pings} == {"pending"}

    delivery = datetime.combine(order.delivery_date, order.delivery_hour, tzinfo=TASHKENT)
    assert pings[0].due_at_utc == delivery - timedelta(hours=3)
    assert pings[1].due_at_utc == delivery - timedelta(hours=1)
