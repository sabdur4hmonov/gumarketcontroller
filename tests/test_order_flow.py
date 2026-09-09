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
    OrderRecipientCB,
    OrderStartCB,
)
from gulbot.bot.factory import build_dispatcher
from gulbot.i18n.catalog import CATALOG
from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.scheduling.occurrences import TASHKENT

pytestmark = pytest.mark.infra

USER_ID = 970_001
CANCEL = next(iter(CATALOG["btn.nav.cancel"].values()))

#: CP12 asks who takes delivery between the landmark and the phone.
RECIPIENT = "Aziza"


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
    # WITH a phone. CP10c makes the order flow ask for one when it is missing,
    # so a customer created by the middleware (no phone) would route every test
    # in this file through that extra step and stop testing what it was written
    # to test. The missing-phone path has its own fixture below.
    await db.execute(
        text(
            "INSERT INTO customers (shop_id, telegram_user_id, phone, phone_verified) "
            "VALUES (:s, :t, '+998901112233', true)"
        ),
        {"s": shop, "t": USER_ID},
    )
    sessions = bound_session_factory(db)
    bot, recorder = make_bot()
    dispatcher = build_dispatcher(session_factory=sessions, shop_id=shop, storage=MemoryStorage())
    return Driver(dispatcher, bot, recorder, db, shop, product)


@pytest_asyncio.fixture
async def phoneless(db: AsyncConnection) -> Driver:
    """The same world, with a customer who has never given a number."""
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
    bot, recorder = make_bot()
    dispatcher = build_dispatcher(
        session_factory=bound_session_factory(db), shop_id=shop, storage=MemoryStorage()
    )
    return Driver(dispatcher, bot, recorder, db, shop, product)


# --- the happy paths -------------------------------------------------------


async def test_a_written_address_order_reaches_the_database(driver: Driver) -> None:
    await driver.through_to_landmark()
    await driver.say("Ko'k eshik")
    await driver.say(RECIPIENT)
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
    await driver.say(RECIPIENT)
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
    await driver.say(RECIPIENT)
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
    await driver.say(RECIPIENT)
    assert any("narx operator tomonidan tasdiqlanadi" in m for m in driver.sent)


async def test_a_priced_bouquet_shows_its_price(driver: Driver) -> None:
    await driver.through_to_landmark()
    await driver.say("Ko'k eshik")
    await driver.say(RECIPIENT)
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
    await driver.say(RECIPIENT)

    assert await driver.orders() == [], "an order was written before the customer confirmed"


async def test_declining_the_confirmation_writes_nothing(driver: Driver) -> None:
    await driver.through_to_landmark()
    await driver.say("Ko'k eshik")
    await driver.say(RECIPIENT)
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
    await driver.say(RECIPIENT)
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
    await driver.say(RECIPIENT)
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
    await driver.say(RECIPIENT)
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
    # CP10b added ping 0: the "new order" announcement to the shop, due now.
    # 1 and 2 are the delivery reminders and index shops.order_ping_offset_hours.
    assert [p.ping_number for p in pings] == [0, 1, 2]
    assert {p.state for p in pings[1:]} == {"pending"}, "the delivery pings wait their turn"

    delivery = datetime.combine(order.delivery_date, order.delivery_hour, tzinfo=TASHKENT)
    assert pings[1].due_at_utc == delivery - timedelta(hours=3)
    assert pings[2].due_at_utc == delivery - timedelta(hours=1)


async def test_the_shop_is_told_at_once_and_the_order_survives_if_it_cannot_be(
    driver: Driver,
) -> None:
    """The announcement is queued, then flushed by the handler immediately.

    This fixture's shop has neither `group_chat_id` nor `owner_telegram_ids`, so
    the flush finds nowhere to send, logs loudly and leaves the row FAILED for
    the beat to retry. That is the case worth pinning: the customer was told
    their order was accepted, and it is -- the order is written and committed
    whatever happens to the notification. The reverse, losing the order because
    nobody could be told about it, would be far worse.
    """
    await driver.through_to_landmark()
    await driver.say("Ko'k eshik")
    await driver.say(RECIPIENT)
    await driver.tap(OrderConfirmCB(action="submit").pack())

    order = (await driver.orders())[0]
    announcement = (
        await driver.db.execute(
            text(
                "SELECT state, attempts FROM order_reminders "
                "WHERE order_id = :o AND ping_number = 0"
            ),
            {"o": order.id},
        )
    ).one()
    assert announcement.state == "failed", "the handler tried, and there was nowhere to send"
    assert announcement.attempts == 1, "it tried exactly once, and the beat has the rest"
    assert order.status == "placed", "the order is unaffected by the notification failing"


# --- CP10c: the number the courier will dial -------------------------------


async def test_a_customer_with_a_number_is_not_asked_again(driver: Driver) -> None:
    """The step exists only when it is needed. Asking a customer who already
    gave a number is friction with nothing behind it."""
    await driver.through_to_landmark()
    await driver.say("Ko'k eshik")
    await driver.say(RECIPIENT)
    assert CATALOG["phone.ask_order"]["uz"] not in driver.sent
    # And the flow really is at the confirmation, not merely past the ask:
    # submitting writes the order.
    await driver.tap(OrderConfirmCB(action="submit").pack())
    assert len(await driver.orders()) == 1


async def test_a_customer_without_one_is_asked_before_the_confirmation(phoneless: Driver) -> None:
    """BEFORE, not after the confirm tap. Two reasons, and the second is the
    load-bearing one: the number is on the screen the customer approves, and
    nothing is interposed between that tap and the insert."""
    await phoneless.through_to_landmark()
    await phoneless.say("Ko'k eshik")
    await phoneless.say(RECIPIENT)
    assert CATALOG["phone.ask_order"]["uz"] in phoneless.sent
    assert await phoneless.orders() == [], "still nothing written"


async def test_giving_the_number_reaches_the_confirmation_and_then_the_order(
    phoneless: Driver,
) -> None:
    await phoneless.through_to_landmark()
    await phoneless.say("Ko'k eshik")
    await phoneless.say(RECIPIENT)
    await phoneless.say("90 123 45 67")
    await phoneless.tap(OrderConfirmCB(action="submit").pack())

    rows = await phoneless.orders()
    assert len(rows) == 1
    stored = (
        await phoneless.db.execute(
            text("SELECT phone, phone_verified FROM customers WHERE telegram_user_id = :t"),
            {"t": USER_ID},
        )
    ).one()
    assert stored.phone == "+998901234567"
    assert stored.phone_verified is False


async def test_the_order_cannot_be_submitted_from_the_phone_step(phoneless: Driver) -> None:
    """The confirm button belongs to `confirming`. Tapping a stale one while the
    phone is still outstanding must not write an order -- this is the guard that
    makes requiring the number actually mean something."""
    await phoneless.through_to_landmark()
    await phoneless.say("Ko'k eshik")
    await phoneless.say(RECIPIENT)
    await phoneless.tap(OrderConfirmCB(action="submit").pack())
    assert await phoneless.orders() == []


async def test_an_unreadable_number_keeps_the_flow_where_it_is(phoneless: Driver) -> None:
    await phoneless.through_to_landmark()
    await phoneless.say("Ko'k eshik")
    await phoneless.say(RECIPIENT)
    await phoneless.say("salom")
    assert CATALOG["phone.invalid"]["uz"] in phoneless.sent
    await phoneless.tap(OrderConfirmCB(action="submit").pack())
    assert await phoneless.orders() == [], "a bad number must not fall through to submit"


async def test_cancel_wins_from_the_order_phone_step(phoneless: Driver) -> None:
    """Every text-waiting state has to prove this, and this file is where the
    behavioural half lives."""
    await phoneless.through_to_landmark()
    await phoneless.say("Ko'k eshik")
    await phoneless.say(RECIPIENT)
    await phoneless.say(CANCEL)
    assert CATALOG["nav.cancelled"]["uz"] in phoneless.sent
    assert await phoneless.orders() == []


async def test_the_number_reaches_the_shops_card(phoneless: Driver) -> None:
    """The whole point of the change, end to end: a number the customer gave
    during the order comes back out on the message the shop reads."""
    from gulbot.sending.order_card import ANNOUNCEMENT, render_card
    from gulbot.sending.order_pings import load_card

    await phoneless.through_to_landmark()
    await phoneless.say("Ko'k eshik")
    await phoneless.say(RECIPIENT)
    await phoneless.say("90 123 45 67")
    await phoneless.tap(OrderConfirmCB(action="submit").pack())

    order = (await phoneless.orders())[0]
    async with bound_session_factory(phoneless.db)() as session:
        card = await load_card(session, order_id=order.id)
    assert card is not None
    rendered = render_card(card, ping_number=ANNOUNCEMENT)
    assert "+998901234567" in rendered
    assert CATALOG["group.no_phone"]["uz"] not in rendered
    # Typed by hand, so it is shown AND marked -- never withheld. The courier
    # still needs something to dial.
    assert "tasdiqlanmagan" in rendered


# --- CP12: who takes delivery ----------------------------------------------


async def test_the_recipient_is_asked_between_the_landmark_and_the_confirmation(
    driver: Driver,
) -> None:
    """A NEW question, not a rename of an old one. The person placing the order
    is often not the person the courier hands the flowers to."""
    await driver.through_to_landmark()
    await driver.say("Ko'k eshik")
    assert CATALOG["order.ask_recipient"]["uz"] in driver.sent
    assert await driver.orders() == [], "still nothing written"


async def test_the_recipient_name_reaches_the_order(driver: Driver) -> None:
    await driver.through_to_landmark()
    await driver.say("Ko'k eshik")
    await driver.say("Aziza opa")
    await driver.tap(OrderConfirmCB(action="submit").pack())

    stored = (
        await driver.db.execute(text("SELECT recipient_name FROM orders ORDER BY id DESC LIMIT 1"))
    ).scalar_one()
    assert stored == "Aziza opa"


async def test_an_empty_recipient_name_asks_again(driver: Driver) -> None:
    await driver.through_to_landmark()
    await driver.say("Ko'k eshik")
    await driver.say("   ")
    assert CATALOG["order.recipient_empty"]["uz"] in driver.sent
    await driver.tap(OrderConfirmCB(action="submit").pack())
    assert await driver.orders() == [], "a blank name must not fall through to submit"


async def test_the_recipient_name_is_sanitised_like_every_other_label(driver: Driver) -> None:
    """CP3's sanitiser, not a second implementation -- so a tab does not fuse
    two words here either."""
    await driver.through_to_landmark()
    await driver.say("Ko'k eshik")
    await driver.say("Aziza\topa​   Karimova")
    await driver.tap(OrderConfirmCB(action="submit").pack())
    stored = (
        await driver.db.execute(text("SELECT recipient_name FROM orders ORDER BY id DESC LIMIT 1"))
    ).scalar_one()
    assert stored == "Aziza opa Karimova"


async def test_the_recipient_shows_on_the_confirmation_screen(driver: Driver) -> None:
    """The customer approves the name, so a typo is caught before the courier
    reads it out at a door."""
    await driver.through_to_landmark()
    await driver.say("Ko'k eshik")
    await driver.say("Aziza opa")
    assert any("Aziza opa" in m for m in driver.sent)


async def test_the_recipient_reaches_the_shops_card(driver: Driver) -> None:
    from gulbot.sending.order_card import ANNOUNCEMENT, render_card
    from gulbot.sending.order_pings import load_card

    await driver.through_to_landmark()
    await driver.say("Ko'k eshik")
    await driver.say("Aziza opa")
    await driver.tap(OrderConfirmCB(action="submit").pack())

    order = (await driver.orders())[0]
    async with bound_session_factory(driver.db)() as session:
        card = await load_card(session, order_id=order.id)
    assert card is not None
    rendered = render_card(card, ping_number=ANNOUNCEMENT)
    assert "Aziza opa" in rendered
    assert CATALOG["group.no_recipient"]["uz"] not in rendered


async def test_an_order_with_no_recipient_says_so_rather_than_inventing_one(
    driver: Driver,
) -> None:
    """Orders placed before CP12 have no answer. A name read out at the wrong
    door is worse than none."""
    from gulbot.sending.order_card import ANNOUNCEMENT, render_card
    from gulbot.sending.order_pings import load_card

    await driver.through_to_landmark()
    await driver.say("Ko'k eshik")
    await driver.say("Aziza opa")
    await driver.tap(OrderConfirmCB(action="submit").pack())
    order = (await driver.orders())[0]
    await driver.db.execute(
        text("UPDATE orders SET recipient_name = NULL WHERE id = :o"), {"o": order.id}
    )

    async with bound_session_factory(driver.db)() as session:
        card = await load_card(session, order_id=order.id)
    assert card is not None
    assert CATALOG["group.no_recipient"]["uz"] in render_card(card, ping_number=ANNOUNCEMENT)


async def test_cancel_wins_from_the_recipient_step(driver: Driver) -> None:
    await driver.through_to_landmark()
    await driver.say("Ko'k eshik")
    await driver.say(CANCEL)
    assert CATALOG["nav.cancelled"]["uz"] in driver.sent
    assert await driver.orders() == []


# --- CP12: the one-tap pre-fill, on the reminder path ----------------------


@pytest_asyncio.fixture
async def with_recipient(db: AsyncConnection, driver: Driver) -> int:
    """A saved person, as a reminder-path order would carry."""
    customer = (
        await db.execute(
            text("SELECT id FROM customers WHERE telegram_user_id = :t"), {"t": USER_ID}
        )
    ).scalar_one()
    return int(
        (
            await db.execute(
                text(
                    "INSERT INTO recipients (shop_id, customer_id, label, type) "
                    "VALUES (:s, :c, 'Onam', 'mother') RETURNING id"
                ),
                {"s": driver.shop, "c": customer},
            )
        ).scalar_one()
    )


async def test_a_reminder_order_offers_the_known_name_as_one_tap(
    driver: Driver, with_recipient: int
) -> None:
    """The bot already knows who the reminder was about. Making the customer
    type a name it could have offered is friction with nothing behind it."""
    await driver.tap(OrderStartCB(product_id=driver.product, recipient_id=with_recipient).pack())
    await driver.tap(OrderDateCB(offset=1).pack())
    await driver.tap(OrderHourCB(hour=14).pack())
    await driver.tap(OrderLocationCB(mode="text").pack())
    await driver.say("Chilonzor 5")
    await driver.say("Ko'k eshik")

    assert CATALOG["order.ask_recipient_known"]["uz"] in driver.sent
    assert CATALOG["order.ask_recipient"]["uz"] not in driver.sent


async def test_tapping_the_known_name_uses_it(driver: Driver, with_recipient: int) -> None:
    await driver.tap(OrderStartCB(product_id=driver.product, recipient_id=with_recipient).pack())
    await driver.tap(OrderDateCB(offset=1).pack())
    await driver.tap(OrderHourCB(hour=14).pack())
    await driver.tap(OrderLocationCB(mode="text").pack())
    await driver.say("Chilonzor 5")
    await driver.say("Ko'k eshik")
    await driver.tap(OrderRecipientCB(action="known").pack())
    await driver.tap(OrderConfirmCB(action="submit").pack())

    row = (
        await driver.db.execute(
            text("SELECT recipient_name, recipient_id FROM orders ORDER BY id DESC LIMIT 1")
        )
    ).one()
    assert row.recipient_name == "Onam"
    assert row.recipient_id == with_recipient, (
        "the order must also record WHICH saved person it came from -- the column "
        "existed since CP10a and nothing ever wrote it"
    )


async def test_choosing_someone_else_falls_through_to_typing(
    driver: Driver, with_recipient: int
) -> None:
    """The known name is a suggestion, not an assumption. Flowers for a mother's
    birthday are often handed to a neighbour."""
    await driver.tap(OrderStartCB(product_id=driver.product, recipient_id=with_recipient).pack())
    await driver.tap(OrderDateCB(offset=1).pack())
    await driver.tap(OrderHourCB(hour=14).pack())
    await driver.tap(OrderLocationCB(mode="text").pack())
    await driver.say("Chilonzor 5")
    await driver.say("Ko'k eshik")
    await driver.tap(OrderRecipientCB(action="other").pack())
    assert CATALOG["order.ask_recipient"]["uz"] in driver.sent
    await driver.say("Qo'shni Dilnoza")
    await driver.tap(OrderConfirmCB(action="submit").pack())

    stored = (
        await driver.db.execute(text("SELECT recipient_name FROM orders ORDER BY id DESC LIMIT 1"))
    ).scalar_one()
    assert stored == "Qo'shni Dilnoza"


async def test_the_browse_path_has_no_name_to_offer(driver: Driver) -> None:
    """recipient_id 0 -- no occasion behind the choice, so straight to typing."""
    await driver.through_to_landmark()
    await driver.say("Ko'k eshik")
    assert CATALOG["order.ask_recipient"]["uz"] in driver.sent
    assert CATALOG["order.ask_recipient_known"]["uz"] not in driver.sent


async def test_another_customers_recipient_is_never_offered(
    driver: Driver, db: AsyncConnection
) -> None:
    """The id arrives in callback data, which a customer can edit. Scoping the
    lookup to this customer AND this shop is what stops a tampered tap naming
    somebody else's saved person."""
    other_customer = (
        await db.execute(
            text(
                "INSERT INTO customers (shop_id, telegram_user_id) VALUES (:s, 970999) RETURNING id"
            ),
            {"s": driver.shop},
        )
    ).scalar_one()
    theirs = (
        await db.execute(
            text(
                "INSERT INTO recipients (shop_id, customer_id, label, type) "
                "VALUES (:s, :c, 'Ularning onasi', 'mother') RETURNING id"
            ),
            {"s": driver.shop, "c": other_customer},
        )
    ).scalar_one()

    await driver.tap(OrderStartCB(product_id=driver.product, recipient_id=theirs).pack())
    await driver.tap(OrderDateCB(offset=1).pack())
    await driver.tap(OrderHourCB(hour=14).pack())
    await driver.tap(OrderLocationCB(mode="text").pack())
    await driver.say("Chilonzor 5")
    await driver.say("Ko'k eshik")

    assert CATALOG["order.ask_recipient"]["uz"] in driver.sent, "must fall back to typing"
    assert not any("Ularning onasi" in m for m in driver.sent)
