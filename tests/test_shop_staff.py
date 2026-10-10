"""Who may decide a shop's orders: the staff allowlist (CP19).

docs/AUDIT.md section 3, A: the order card's permission was by CHAT, so anyone
a shop added to its group -- a courier, a supplier, a relative -- could confirm
or reject any order. The list fixes that without breaking any shop today:

* EMPTY LIST = TODAY'S RULE. No shop has a row after the migration, and a shop
  without one behaves exactly as before.
* ONE ROW SWITCHES THE SHOP. From then on only the listed people and the
  shop's owners decide; everyone else in the group gets an alert and nothing
  changes.
* CRAFTED CALLBACKS GET NOTHING. Telegram does not prove a callback came from a
  button the bot sent, so every check here runs on the TAPPER, whatever the
  callback names: another order's id, the abort of someone else's prompt, a
  reason typed after the typist was taken off the list.
* ONE SHOP'S LIST NEVER SPEAKS FOR ANOTHER. Being staff at A is nothing at B.

Driven through the real dispatcher, as tests/test_admin_orders.py is: the
chat gate and the customer middleware both sit in front of these handlers.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import AnswerCallbackQuery, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
from tests.bot_harness import bound_session_factory, make_bot

from gulbot.bot.callbacks import OrderAdminCB
from gulbot.bot.factory import build_dispatcher
from gulbot.bot.states import AdminOrder
from gulbot.i18n import t
from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.services import shop_staff
from gulbot.services.shop_staff import MAX_STAFF, StaffRefused

pytestmark = pytest.mark.infra

GROUP_A, GROUP_B = -1_003_900_000_001, -1_003_900_000_002
OWNER_A, OWNER_B = 640_001, 640_002
COURIER = 640_101  # in A's group, never listed
CLERK = 640_102  # A's listed staff
CUSTOMER_TG = 640_901


class Shop:
    def __init__(self, db, shop_id, group, order, dispatcher, bot, recorder):  # type: ignore[no-untyped-def]
        self.db, self.id, self.group, self.order = db, shop_id, group, order
        self.dispatcher, self.bot, self.recorder = dispatcher, bot, recorder
        self._update = 0

    def _next(self) -> int:
        self._update += 1
        return self._update

    async def tap(self, action: str, order_id: int | None = None, *, by: int) -> None:
        self.recorder.calls.clear()
        update_id = self._next()
        await self.dispatcher.feed_update(
            self.bot,
            Update(
                update_id=update_id,
                callback_query=CallbackQuery(
                    id=f"cb{update_id}",
                    from_user=User(id=by, is_bot=False, first_name="Someone"),
                    chat_instance=f"chat{update_id}",
                    data=OrderAdminCB(
                        action=action, order_id=self.order if order_id is None else order_id
                    ).pack(),
                    message=Message(
                        message_id=500 + update_id,
                        date=datetime.now(tz=UTC),
                        chat=Chat(id=self.group, type="supergroup", title="Shop"),
                        from_user=User(id=1, is_bot=True, first_name="bot"),
                        text="Yangi buyurtma",
                    ),
                ),
            ),
        )

    async def type(self, body: str, *, by: int) -> None:
        self.recorder.calls.clear()
        update_id = self._next()
        await self.dispatcher.feed_update(
            self.bot,
            Update(
                update_id=update_id,
                message=Message(
                    message_id=600 + update_id,
                    date=datetime.now(tz=UTC),
                    chat=Chat(id=self.group, type="supergroup", title="Shop"),
                    from_user=User(id=by, is_bot=False, first_name="Someone"),
                    text=body,
                ),
            ),
        )

    async def status(self, order_id: int | None = None) -> str:
        found = await self.db.execute(
            text("SELECT status FROM orders WHERE id = :o"),
            {"o": self.order if order_id is None else order_id},
        )
        return str(found.scalar_one())

    def alerts(self) -> list[str]:
        return [
            str(call.text)
            for call in self.recorder.calls
            if isinstance(call, AnswerCallbackQuery) and call.show_alert and call.text
        ]

    async def state_of(self, user_id: int) -> str | None:
        context = self.dispatcher.fsm.get_context(bot=self.bot, chat_id=self.group, user_id=user_id)
        return await context.get_state()

    async def list(self, *people: int) -> None:
        for person in people:
            await self.db.execute(
                text("INSERT INTO shop_staff (shop_id, telegram_id, added_by) VALUES (:s, :p, :o)"),
                {"s": self.id, "p": person, "o": OWNER_A},
            )

    async def unlist(self, person: int) -> None:
        await self.db.execute(
            text("DELETE FROM shop_staff WHERE shop_id = :s AND telegram_id = :p"),
            {"s": self.id, "p": person},
        )


async def _shop(db: AsyncConnection, *, group: int, owner: int, token: str) -> Shop:
    shop_id = (
        await db.execute(
            text(
                "INSERT INTO shops (name, working_hours, group_chat_id, owner_telegram_ids) "
                "VALUES ('S', CAST(:wh AS jsonb), :g, ARRAY[CAST(:o AS bigint)]) RETURNING id"
            ),
            {"wh": json.dumps(DEFAULT_WORKING_HOURS), "g": group, "o": owner},
        )
    ).scalar_one()
    customer = (
        await db.execute(
            text(
                "INSERT INTO customers (shop_id, telegram_user_id, lang) "
                "VALUES (:s, :t, 'uz') RETURNING id"
            ),
            {"s": shop_id, "t": CUSTOMER_TG},
        )
    ).scalar_one()
    order = await _order(db, shop_id, customer, token)
    bot, recorder = make_bot()
    dispatcher = build_dispatcher(
        session_factory=bound_session_factory(db),
        shop_id=shop_id,
        storage=MemoryStorage(),
        schedule_finalize=lambda **kwargs: None,
    )
    return Shop(db, shop_id, group, order, dispatcher, bot, recorder)


async def _order(db: AsyncConnection, shop_id: int, customer: int, token: str) -> int:
    return int(
        (
            await db.execute(
                text(
                    "INSERT INTO orders (shop_id, customer_id, product_name_snapshot, "
                    " price_uzs_snapshot, telegram_file_id_snapshot, delivery_date, "
                    " delivery_hour, delivery_location_text, landmark, status, submit_token) "
                    "VALUES (:s, :c, 'Oq atirgul', 450000, 'f', :d, '14:00', 'Chilonzor', "
                    " 'eshik', 'placed', :tok) RETURNING id"
                ),
                {"s": shop_id, "c": customer, "d": date(2027, 3, 8), "tok": token},
            )
        ).scalar_one()
    )


@pytest_asyncio.fixture
async def shop_a(db: AsyncConnection) -> Shop:
    return await _shop(db, group=GROUP_A, owner=OWNER_A, token="staff-a")


@pytest_asyncio.fixture
async def shop_b(db: AsyncConnection) -> Shop:
    return await _shop(db, group=GROUP_B, owner=OWNER_B, token="staff-b")


def refusal() -> str:
    return t("group.not_staff", "uz")


# --- the default: nothing changes until an owner acts ---------------------


async def test_with_no_list_anyone_in_the_group_still_decides(shop_a: Shop) -> None:
    """Every shop after the migration. A courier the shop trusts today keeps
    working tomorrow."""
    await shop_a.tap("confirm", by=COURIER)
    assert await shop_a.status() == "confirmed"
    assert shop_a.alerts() == []


async def test_the_migration_gives_no_shop_a_list(db: AsyncConnection, shop_a: Shop) -> None:
    rows = await db.execute(text("SELECT count(*) FROM shop_staff"))
    assert rows.scalar_one() == 0


# --- once a list exists ---------------------------------------------------


async def test_a_member_not_on_the_list_cannot_confirm(shop_a: Shop) -> None:
    await shop_a.list(CLERK)
    await shop_a.tap("confirm", by=COURIER)
    assert await shop_a.status() == "placed"
    assert shop_a.alerts() == [refusal()]


async def test_a_member_not_on_the_list_cannot_start_a_rejection(shop_a: Shop) -> None:
    await shop_a.list(CLERK)
    await shop_a.tap("reject", by=COURIER)
    assert await shop_a.state_of(COURIER) is None
    assert shop_a.alerts() == [refusal()]
    # No reason prompt in the group.
    assert [c for c in shop_a.recorder.calls if isinstance(c, SendMessage)] == []


async def test_a_member_not_on_the_list_cannot_withdraw_someone_elses_rejection(
    shop_a: Shop,
) -> None:
    await shop_a.list(CLERK)
    await shop_a.tap("reject", by=CLERK)
    await shop_a.tap("abort", by=COURIER)
    assert shop_a.alerts() == [refusal()]
    edits = [c for c in shop_a.recorder.calls if type(c).__name__.startswith("Edit")]
    assert edits == []


async def test_a_listed_member_decides(shop_a: Shop) -> None:
    await shop_a.list(CLERK)
    await shop_a.tap("confirm", by=CLERK)
    assert await shop_a.status() == "confirmed"


async def test_a_listed_member_rejects_with_a_reason(shop_a: Shop) -> None:
    await shop_a.list(CLERK)
    await shop_a.tap("reject", by=CLERK)
    assert await shop_a.state_of(CLERK) == AdminOrder.entering_reject_reason.state
    await shop_a.type("gul tugadi", by=CLERK)
    assert await shop_a.status() == "rejected"


async def test_the_owner_always_decides_even_off_the_list(shop_a: Shop) -> None:
    """An owner who lists a clerk must not lock themself out."""
    await shop_a.list(CLERK)
    await shop_a.tap("confirm", by=OWNER_A)
    assert await shop_a.status() == "confirmed"


async def test_a_reason_typed_after_being_taken_off_the_list_rejects_nothing(
    shop_a: Shop,
) -> None:
    """The prompt was allowed; the reason is checked again when it arrives."""
    await shop_a.list(CLERK, 640_103)
    await shop_a.tap("reject", by=CLERK)
    await shop_a.unlist(CLERK)
    await shop_a.type("gul tugadi", by=CLERK)
    assert await shop_a.status() == "placed"
    assert refusal() in shop_a.recorder.sent_texts
    assert await shop_a.state_of(CLERK) is None


# --- crafted callbacks ----------------------------------------------------


async def test_a_crafted_callback_for_another_order_is_still_refused(
    db: AsyncConnection, shop_a: Shop
) -> None:
    """The order id is the callback's to choose; the decision is not."""
    customer = (
        await db.execute(text("SELECT id FROM customers WHERE shop_id = :s"), {"s": shop_a.id})
    ).scalar_one()
    other = await _order(db, shop_a.id, customer, "staff-a-2")
    await shop_a.list(CLERK)
    for action in ("confirm", "reject", "abort"):
        await shop_a.tap(action, other, by=COURIER)
        assert shop_a.alerts() == [refusal()], action
    assert await shop_a.status(other) == "placed"


async def test_being_staff_at_one_shop_is_nothing_at_another(shop_a: Shop, shop_b: Shop) -> None:
    """A's clerk is in B's group too. B has a list without them."""
    await shop_a.list(CLERK)
    await shop_b.db.execute(
        text("INSERT INTO shop_staff (shop_id, telegram_id, added_by) VALUES (:s, :p, :o)"),
        {"s": shop_b.id, "p": 640_201, "o": OWNER_B},
    )
    await shop_b.tap("confirm", by=CLERK)
    assert await shop_b.status() == "placed"
    assert shop_b.alerts() == [refusal()]


async def test_one_shops_owner_is_not_another_shops_owner(shop_a: Shop, shop_b: Shop) -> None:
    await shop_b.db.execute(
        text("INSERT INTO shop_staff (shop_id, telegram_id, added_by) VALUES (:s, :p, :o)"),
        {"s": shop_b.id, "p": 640_201, "o": OWNER_B},
    )
    await shop_b.tap("confirm", by=OWNER_A)
    assert await shop_b.status() == "placed"


async def test_a_list_in_one_shop_leaves_another_shop_open(shop_a: Shop, shop_b: Shop) -> None:
    """B has no list, so B keeps today's rule even though A has one."""
    await shop_a.list(CLERK)
    await shop_b.tap("confirm", by=COURIER)
    assert await shop_b.status() == "confirmed"


# --- the service ----------------------------------------------------------


@pytest_asyncio.fixture
async def session(db: AsyncConnection) -> AsyncSession:
    return bound_session_factory(db)()


async def test_only_an_owner_of_that_shop_changes_its_list(
    session: AsyncSession, shop_a: Shop, shop_b: Shop
) -> None:
    for owner, shop in ((OWNER_B, shop_a.id), (COURIER, shop_a.id), (OWNER_A, shop_b.id)):
        try:
            await shop_staff.add_staff(
                session, shop_id=shop, owner_id=owner, telegram_id=CLERK, label="x"
            )
        except StaffRefused as refused:
            assert refused.reason == "not_owner"
        else:
            raise AssertionError(f"owner {owner} changed shop {shop}'s list")
        try:
            await shop_staff.remove_staff(session, shop_id=shop, owner_id=owner, telegram_id=CLERK)
        except StaffRefused as refused:
            assert refused.reason == "not_owner"
        else:
            raise AssertionError(f"owner {owner} changed shop {shop}'s list")
    assert await shop_staff.staff_of(session, shop_id=shop_a.id) == []
    assert await shop_staff.staff_of(session, shop_id=shop_b.id) == []


async def test_an_owner_adds_and_removes(session: AsyncSession, shop_a: Shop) -> None:
    added = await shop_staff.add_staff(
        session, shop_id=shop_a.id, owner_id=OWNER_A, telegram_id=CLERK, label="  Dilnoza  K. "
    )
    assert added is True
    assert await shop_staff.staff_of(session, shop_id=shop_a.id) == [
        shop_staff.StaffMember(CLERK, "Dilnoza K.")
    ]
    again = await shop_staff.add_staff(
        session, shop_id=shop_a.id, owner_id=OWNER_A, telegram_id=CLERK, label="Dilnoza"
    )
    assert again is False
    assert await shop_staff.remove_staff(
        session, shop_id=shop_a.id, owner_id=OWNER_A, telegram_id=CLERK
    )
    assert not await shop_staff.remove_staff(
        session, shop_id=shop_a.id, owner_id=OWNER_A, telegram_id=CLERK
    )


@pytest.mark.parametrize(("person", "reason"), [(0, "bad_id"), (-5, "bad_id"), (2**52, "bad_id")])
async def test_an_id_that_is_not_a_person_is_refused(
    session: AsyncSession, shop_a: Shop, person: int, reason: str
) -> None:
    try:
        await shop_staff.add_staff(
            session, shop_id=shop_a.id, owner_id=OWNER_A, telegram_id=person, label=None
        )
    except StaffRefused as refused:
        assert refused.reason == reason
    else:
        raise AssertionError(f"{person} was listed")


async def test_an_owner_is_not_listed_because_owners_always_decide(
    session: AsyncSession, shop_a: Shop
) -> None:
    try:
        await shop_staff.add_staff(
            session, shop_id=shop_a.id, owner_id=OWNER_A, telegram_id=OWNER_A, label=None
        )
    except StaffRefused as refused:
        assert refused.reason == "is_owner"
    else:
        raise AssertionError("the owner was listed")


async def test_the_list_is_capped(session: AsyncSession, shop_a: Shop) -> None:
    for n in range(MAX_STAFF):
        await shop_staff.add_staff(
            session, shop_id=shop_a.id, owner_id=OWNER_A, telegram_id=700_000 + n, label=None
        )
    try:
        await shop_staff.add_staff(
            session, shop_id=shop_a.id, owner_id=OWNER_A, telegram_id=799_999, label=None
        )
    except StaffRefused as refused:
        assert refused.reason == "full"
    else:
        raise AssertionError("the list went past its cap")
    # Re-adding someone already listed is a label update, not a new place.
    assert (
        await shop_staff.add_staff(
            session, shop_id=shop_a.id, owner_id=OWNER_A, telegram_id=700_000, label="Ali"
        )
        is False
    )


async def test_may_decide_is_false_for_a_shop_that_does_not_exist(session: AsyncSession) -> None:
    assert not await shop_staff.may_decide(session, shop_id=-1, telegram_id=OWNER_A)


async def test_owned_shops_are_only_ones_own(
    session: AsyncSession, shop_a: Shop, shop_b: Shop
) -> None:
    mine = await shop_staff.owned_shops(session, telegram_id=OWNER_A)
    assert [found.shop_id for found in mine] == [shop_a.id]
    assert await shop_staff.owned_shops(session, telegram_id=COURIER) == []


# --- the database ---------------------------------------------------------


async def test_the_database_refuses_an_id_that_is_not_a_person(
    db: AsyncConnection, shop_a: Shop
) -> None:
    with pytest.raises(IntegrityError, match="ck_shop_staff_telegram_id_is_a_person"):
        async with db.begin_nested():
            await shop_a.list(0)


async def test_the_database_holds_one_row_per_person_per_shop(
    db: AsyncConnection, shop_a: Shop
) -> None:
    await shop_a.list(CLERK)
    with pytest.raises(IntegrityError, match="pk_shop_staff"):
        async with db.begin_nested():
            await shop_a.list(CLERK)


async def test_a_list_goes_with_its_shop(db: AsyncConnection, shop_a: Shop) -> None:
    await shop_a.list(CLERK)
    await db.execute(text("DELETE FROM orders WHERE shop_id = :s"), {"s": shop_a.id})
    await db.execute(text("DELETE FROM customers WHERE shop_id = :s"), {"s": shop_a.id})
    await db.execute(text("DELETE FROM shops WHERE id = :s"), {"s": shop_a.id})
    left = await db.execute(
        text("SELECT count(*) FROM shop_staff WHERE shop_id = :s"), {"s": shop_a.id}
    )
    assert left.scalar_one() == 0
