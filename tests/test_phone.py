"""Collecting the customer's phone number.

Added because the live CP10b run showed every order card reading
"telefon raqami yo'q": the column had existed since CP1, `phone_verified`'s own
docstring described how it would be shown on the shop's card, and nothing had
ever written to it. A shop cannot phone a customer whose number it does not
have, and in Tashkent -- where addressing is approximate and couriers call
ahead -- that is the difference between a delivery and a lost order.

THE SPLIT: skippable at onboarding, required at order time. A customer who only
wants reminders is never made to hand over a number for a service that will not
phone them; a customer placing an order is asked at the exact moment the reason
is obvious.
"""

from __future__ import annotations

import json

import pytest
import pytest_asyncio
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import (
    bound_session_factory,
    contact_update,
    feed,
    make_bot,
    text_update,
)

from gulbot.bot.factory import build_dispatcher
from gulbot.bot.states import Onboarding
from gulbot.i18n.catalog import CATALOG
from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.utils.phone import normalize_phone, normalize_shared_contact

# --------------------------------------------------------------------------
# the parser: pure
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("901234567", "+998901234567"),
        ("90 123 45 67", "+998901234567"),
        ("90-123-45-67", "+998901234567"),
        ("998901234567", "+998901234567"),
        ("+998901234567", "+998901234567"),
        ("+998 (90) 123-45-67", "+998901234567"),
        ("  +998901234567  ", "+998901234567"),
    ],
)
def test_the_shapes_an_uzbek_customer_actually_types(raw: str, expected: str) -> None:
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "salom",
        "90123456",  # eight digits: one short
        "9012345678",  # ten: one too many, and no '+' to claim it is foreign
        "12345678901",  # eleven, bare -- far likelier a typo than a foreign number
        "+1234",  # too short even for E.164
        "+1234567890123456",  # sixteen: past E.164
        "----",
    ],
)
def test_anything_that_might_not_be_a_number_is_refused(raw: str) -> None:
    """A rejected number is a retry prompt the customer sees at once. An
    accepted-but-wrong one is a courier outside the wrong building."""
    assert normalize_phone(raw) is None


def test_a_foreign_number_needs_the_customer_to_write_the_plus() -> None:
    """The '+' is the customer saying "this is international". Without it there
    is no way to tell a foreign number from a mistyped local one."""
    assert normalize_phone("+7 495 123 45 67") == "+74951234567"
    assert normalize_phone("74951234567") is None


def test_a_shared_contact_is_taken_on_telegrams_authority() -> None:
    """Telegram's own value is a real number, so a foreign one needs no '+'
    from the customer -- that is the whole difference from typed input."""
    assert normalize_shared_contact("74951234567") == "+74951234567"
    assert normalize_shared_contact("998901234567") == "+998901234567"
    assert normalize_shared_contact("+998901234567") == "+998901234567"


def test_even_telegram_does_not_get_to_supply_nonsense() -> None:
    assert normalize_shared_contact("123") is None


# --------------------------------------------------------------------------
# the flows, through the real dispatcher
# --------------------------------------------------------------------------

pytestmark = pytest.mark.infra

USER_ID = 981_001
SKIP = next(iter(CATALOG["btn.phone.skip"].values()))
CANCEL = next(iter(CATALOG["btn.nav.cancel"].values()))


class PhoneDriver:
    def __init__(self, dispatcher, bot, recorder, db, shop, customer) -> None:  # type: ignore[no-untyped-def]
        self.dispatcher, self.bot, self.recorder = dispatcher, bot, recorder
        self.db, self.shop, self.customer = db, shop, customer
        self._update = 0

    def _next(self) -> int:
        self._update += 1
        return self._update

    async def say(self, message: str) -> None:
        await feed(
            self.dispatcher, self.bot, text_update(message, user_id=USER_ID, update_id=self._next())
        )

    async def share(self, **kwargs: object) -> None:
        await feed(
            self.dispatcher,
            self.bot,
            contact_update(user_id=USER_ID, update_id=self._next(), **kwargs),  # type: ignore[arg-type]
        )

    @property
    def sent(self) -> list[str]:
        return self.recorder.sent_texts

    async def stored(self) -> tuple[str | None, bool]:
        row = (
            await self.db.execute(
                text("SELECT phone, phone_verified FROM customers WHERE id = :c"),
                {"c": self.customer},
            )
        ).one()
        return row.phone, row.phone_verified


@pytest_asyncio.fixture
async def driver(db: AsyncConnection) -> PhoneDriver:
    shop = (
        await db.execute(
            text(
                "INSERT INTO shops (name, working_hours) "
                "VALUES ('S', CAST(:wh AS jsonb)) RETURNING id"
            ),
            {"wh": json.dumps(DEFAULT_WORKING_HOURS)},
        )
    ).scalar_one()
    customer = (
        await db.execute(
            text("INSERT INTO customers (shop_id, telegram_user_id) VALUES (:s, :t) RETURNING id"),
            {"s": shop, "t": USER_ID},
        )
    ).scalar_one()
    bot, recorder = make_bot()
    dispatcher = build_dispatcher(
        session_factory=bound_session_factory(db), shop_id=shop, storage=MemoryStorage()
    )
    driver = PhoneDriver(dispatcher, bot, recorder, db, shop, customer)
    # Park the customer in the phone step directly. Driving the whole onboarding
    # chain to get here is test_occasions_flow's job, not this file's.
    await dispatcher.fsm.get_context(bot, USER_ID, USER_ID).set_state(Onboarding.sharing_phone)
    return driver


async def test_sharing_the_contact_stores_a_verified_number(driver: PhoneDriver) -> None:
    await driver.share()
    assert await driver.stored() == ("+998901234567", True)


async def test_typing_the_number_stores_it_unverified(driver: PhoneDriver) -> None:
    """Marked, never refused. The Telegram-linked number is often not the one a
    customer wants a courier calling, so typing one by hand is a real choice."""
    await driver.say("90 123 45 67")
    assert await driver.stored() == ("+998901234567", False)


async def test_someone_elses_contact_is_refused(driver: PhoneDriver) -> None:
    """`customers.phone` is THIS customer's number. Storing a friend's would put
    a stranger on the shop's card and the courier would ring it."""
    await driver.share(contact_user_id=USER_ID + 5)
    assert await driver.stored() == (None, False)
    assert CATALOG["phone.not_yours"]["uz"] in driver.sent


async def test_an_unreadable_number_asks_again_and_stores_nothing(driver: PhoneDriver) -> None:
    await driver.say("salom")
    assert await driver.stored() == (None, False)
    assert CATALOG["phone.invalid"]["uz"] in driver.sent


async def test_skipping_stores_nothing_and_finishes_onboarding(driver: PhoneDriver) -> None:
    """The reminder half of the product works without a number."""
    await driver.say(SKIP)
    assert await driver.stored() == (None, False)
    assert CATALOG["recipients.onboarding_done"]["uz"] in driver.sent


async def test_skip_is_not_swallowed_as_a_phone_number(driver: PhoneDriver) -> None:
    """The registration-order bug this state is most exposed to.

    "Keyinroq" is text, and the state's own handler accepts ANY text as a
    candidate number. Registered in the wrong order it would be stored as one --
    except it is not a valid number, so it would surface as "that is not a
    number" and the customer could never skip at all. The sweep catches the
    ordering; this catches the behaviour.
    """
    await driver.say(SKIP)
    phone, _ = await driver.stored()
    assert phone is None
    assert CATALOG["phone.invalid"]["uz"] not in driver.sent


async def test_cancel_still_wins_from_the_phone_step(driver: PhoneDriver) -> None:
    """Every text-waiting state has to prove this. The exhaustive half is in
    test_nav_precedence.py, which picks up new states automatically."""
    await driver.say(CANCEL)
    assert await driver.stored() == (None, False)
    assert CATALOG["nav.cancelled"]["uz"] in driver.sent


async def test_start_still_wins_from_the_phone_step(driver: PhoneDriver) -> None:
    await driver.say("/start")
    assert await driver.stored() == (None, False)


async def test_a_second_number_replaces_the_first(driver: PhoneDriver) -> None:
    """Guards the guard: `set_phone` must overwrite, not silently keep the old
    value, or a correction would never take."""
    await driver.say("90 123 45 67")
    assert await driver.stored() == ("+998901234567", False)
    await driver.dispatcher.fsm.get_context(driver.bot, USER_ID, USER_ID).set_state(
        Onboarding.sharing_phone
    )
    await driver.share(phone_number="+998935556677")
    assert await driver.stored() == ("+998935556677", True)
