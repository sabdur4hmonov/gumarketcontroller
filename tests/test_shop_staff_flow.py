"""/staff on the PLATFORM bot: an owner manages the staff list (CP19).

Through the real platform dispatcher, as tests/test_shop_onboarding_flow.py
is, so the router order, the filters and the shadow-sweep-shaped exceptions
(Cancel and /start belong to onboarding) all run as in production.

What it proves beyond the happy path: the shop id an action names -- in a
callback or in the adding step's state -- is a claim, and a claim about a shop
the tapper does not own changes nothing.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import AnswerCallbackQuery, SendMessage
from aiogram.types import Chat, Message, SharedUser, Update, User, UsersShared
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

from gulbot.bot.callbacks import StaffCB
from gulbot.bot.factory import build_platform_dispatcher
from gulbot.bot.keyboards import STAFF_REQUEST_ID
from gulbot.bot.states import StaffAdmin
from gulbot.i18n import t
from gulbot.i18n.catalog import CATALOG
from gulbot.models.shop import DEFAULT_WORKING_HOURS

pytestmark = pytest.mark.infra

OWNER_A, OWNER_B = 650_001, 650_002
STRANGER = 650_009
CLERK = 650_101
CANCEL = CATALOG["btn.nav.cancel"]["uz"]
UZ = "uz"


class Person:
    def __init__(self, dispatcher: Dispatcher, bot: Bot, recorder: RecordingSession, uid: int):
        self.dispatcher, self.bot, self.recorder, self.uid = dispatcher, bot, recorder, uid
        self._update = uid * 10

    def _next(self) -> int:
        self._update += 1
        return self._update

    async def say(self, body: str) -> None:
        self.recorder.calls.clear()
        await feed(
            self.dispatcher, self.bot, text_update(body, user_id=self.uid, update_id=self._next())
        )

    async def tap(self, data: str) -> None:
        self.recorder.calls.clear()
        await feed(
            self.dispatcher,
            self.bot,
            callback_update(data, user_id=self.uid, update_id=self._next()),
        )

    async def pick(self, person: int, first_name: str | None = "Dilnoza") -> None:
        self.recorder.calls.clear()
        update_id = self._next()
        await feed(
            self.dispatcher,
            self.bot,
            Update(
                update_id=update_id,
                message=Message(
                    message_id=update_id,
                    date=datetime.now(tz=UTC),
                    chat=Chat(id=self.uid, type="private"),
                    from_user=User(id=self.uid, is_bot=False, first_name="Owner"),
                    users_shared=UsersShared(
                        request_id=STAFF_REQUEST_ID,
                        users=[SharedUser(user_id=person, first_name=first_name)],
                    ),
                ),
            ),
        )

    @property
    def said(self) -> list[str]:
        return [str(c.text) for c in self.recorder.calls if isinstance(c, SendMessage)]

    @property
    def alerts(self) -> list[str]:
        return [
            str(c.text)
            for c in self.recorder.calls
            if isinstance(c, AnswerCallbackQuery) and c.show_alert and c.text
        ]

    def buttons(self) -> list[str]:
        found: list[str] = []
        for call in self.recorder.calls:
            markup = getattr(call, "reply_markup", None)
            for row in getattr(markup, "inline_keyboard", None) or []:
                found.extend(str(b.callback_data) for b in row)
        return found

    async def state(self) -> str | None:
        context = self.dispatcher.fsm.get_context(bot=self.bot, chat_id=self.uid, user_id=self.uid)
        return await context.get_state()

    async def set_adding_for(self, shop_id: int) -> None:
        context = self.dispatcher.fsm.get_context(bot=self.bot, chat_id=self.uid, user_id=self.uid)
        await context.set_state(StaffAdmin.adding)
        await context.update_data(staff_shop_id=shop_id)


class World:
    def __init__(self, db: AsyncConnection, a: int, b: int, people: dict[int, Person]) -> None:
        self.db, self.a, self.b, self.people = db, a, b, people

    def __getitem__(self, uid: int) -> Person:
        return self.people[uid]

    async def staff(self, shop_id: int) -> list[int]:
        rows = await self.db.execute(
            text("SELECT telegram_id FROM shop_staff WHERE shop_id = :s ORDER BY telegram_id"),
            {"s": shop_id},
        )
        return list(rows.scalars())


async def _shop(db: AsyncConnection, name: str, owner: int) -> int:
    return int(
        (
            await db.execute(
                text(
                    "INSERT INTO shops (name, working_hours, owner_telegram_ids) "
                    "VALUES (:n, CAST(:wh AS jsonb), ARRAY[CAST(:o AS bigint)]) RETURNING id"
                ),
                {"n": name, "wh": json.dumps(DEFAULT_WORKING_HOURS), "o": owner},
            )
        ).scalar_one()
    )


@pytest_asyncio.fixture
async def world(db: AsyncConnection) -> World:
    a = await _shop(db, "Lola Gullari", OWNER_A)
    b = await _shop(db, "Bog Gullari", OWNER_B)
    dispatcher = build_platform_dispatcher(
        session_factory=bound_session_factory(db), storage=MemoryStorage()
    )
    bot, recorder = make_bot()
    people = {uid: Person(dispatcher, bot, recorder, uid) for uid in (OWNER_A, OWNER_B, STRANGER)}
    return World(db, a, b, people)


def _t(key: str, **kwargs: Any) -> str:
    return t(key, UZ, **kwargs)


# --- who gets in ---------------------------------------------------------


async def test_staff_means_nothing_to_someone_who_owns_no_shop(world: World) -> None:
    await world[STRANGER].say("/staff")
    assert world[STRANGER].said == [_t("owner.idle")]


async def test_an_owner_of_one_shop_sees_its_list_at_once(world: World) -> None:
    await world[OWNER_A].say("/staff")
    (screen,) = world[OWNER_A].said
    assert "Lola Gullari" in screen
    assert _t("staff.empty") in screen
    assert StaffCB(action="add", shop_id=world.a).pack() in world[OWNER_A].buttons()


async def test_an_owner_of_two_shops_picks_one_first(world: World) -> None:
    await world.db.execute(
        text("UPDATE shops SET owner_telegram_ids = ARRAY[CAST(:o AS bigint)] WHERE id = :b"),
        {"o": OWNER_A, "b": world.b},
    )
    await world[OWNER_A].say("/staff")
    assert world[OWNER_A].said == [_t("staff.pick_shop")]
    assert world[OWNER_A].buttons() == [
        StaffCB(action="open", shop_id=world.a).pack(),
        StaffCB(action="open", shop_id=world.b).pack(),
    ]
    await world[OWNER_A].tap(StaffCB(action="open", shop_id=world.b).pack())
    assert "Bog Gullari" in world[OWNER_A].said[0]


# --- adding and removing -------------------------------------------------


async def test_picking_a_person_puts_them_on_the_list(world: World) -> None:
    await world[OWNER_A].tap(StaffCB(action="add", shop_id=world.a).pack())
    assert await world[OWNER_A].state() == StaffAdmin.adding.state
    await world[OWNER_A].pick(CLERK)
    assert await world.staff(world.a) == [CLERK]
    assert _t("staff.added", name="Dilnoza") in world[OWNER_A].said
    assert await world[OWNER_A].state() is None
    listing = world[OWNER_A].said[-1]
    assert "Dilnoza" in listing and str(CLERK) in listing


async def test_a_typed_id_works_too(world: World) -> None:
    await world[OWNER_A].tap(StaffCB(action="add", shop_id=world.a).pack())
    await world[OWNER_A].say(f" {CLERK} ")
    assert await world.staff(world.a) == [CLERK]


async def test_a_typed_number_that_is_no_person_keeps_asking(world: World) -> None:
    await world[OWNER_A].tap(StaffCB(action="add", shop_id=world.a).pack())
    await world[OWNER_A].say("0")
    assert world[OWNER_A].said == [_t("staff.refused.bad_id")]
    assert await world[OWNER_A].state() == StaffAdmin.adding.state
    assert await world.staff(world.a) == []


async def test_anything_else_while_adding_asks_again(world: World) -> None:
    await world[OWNER_A].tap(StaffCB(action="add", shop_id=world.a).pack())
    await world[OWNER_A].say("Dilnoza")
    assert world[OWNER_A].said == [_t("staff.add_ask")]
    assert await world.staff(world.a) == []


async def test_cancel_while_adding_saves_nothing(world: World) -> None:
    """Cancel is onboarding's, from every platform state."""
    await world[OWNER_A].tap(StaffCB(action="add", shop_id=world.a).pack())
    await world[OWNER_A].say(CANCEL)
    assert await world[OWNER_A].state() is None
    assert world[OWNER_A].said == [_t("owner.cancelled")]
    assert await world.staff(world.a) == []


async def test_removing_takes_them_off(world: World) -> None:
    await world[OWNER_A].tap(StaffCB(action="add", shop_id=world.a).pack())
    await world[OWNER_A].pick(CLERK)
    await world[OWNER_A].tap(StaffCB(action="remove", shop_id=world.a, person=CLERK).pack())
    assert await world.staff(world.a) == []
    assert _t("staff.empty") in world[OWNER_A].said[-1]


async def test_the_owner_cannot_list_themself(world: World) -> None:
    await world[OWNER_A].tap(StaffCB(action="add", shop_id=world.a).pack())
    await world[OWNER_A].pick(OWNER_A)
    assert _t("staff.refused.is_owner") in world[OWNER_A].said
    assert await world.staff(world.a) == []


# --- crafted callbacks and stale claims ----------------------------------


async def test_a_crafted_button_for_another_owners_shop_changes_nothing(world: World) -> None:
    await world.db.execute(
        text("INSERT INTO shop_staff (shop_id, telegram_id, added_by) VALUES (:s, :p, :o)"),
        {"s": world.b, "p": CLERK, "o": OWNER_B},
    )
    for action in ("open", "add", "remove"):
        await world[OWNER_A].tap(StaffCB(action=action, shop_id=world.b, person=CLERK).pack())
        assert world[OWNER_A].alerts == [_t("staff.refused.not_owner")], action
        assert world[OWNER_A].said == [], action  # B's list is never shown
        assert await world[OWNER_A].state() is None, action
    assert await world.staff(world.b) == [CLERK]


async def test_someone_who_owns_nothing_gets_nothing_from_any_button(world: World) -> None:
    for action in ("open", "add", "remove"):
        await world[STRANGER].tap(StaffCB(action=action, shop_id=world.a, person=CLERK).pack())
        assert world[STRANGER].alerts == [_t("staff.refused.not_owner")], action
        assert world[STRANGER].said == [], action


async def test_the_shop_being_added_to_is_checked_again_when_the_answer_comes(
    world: World,
) -> None:
    """The state names a shop; a state is only a claim. Here the owner was
    removed as an owner mid-step."""
    await world[OWNER_A].tap(StaffCB(action="add", shop_id=world.a).pack())
    await world.db.execute(
        text("UPDATE shops SET owner_telegram_ids = '{}' WHERE id = :a"), {"a": world.a}
    )
    await world[OWNER_A].pick(CLERK)
    assert await world.staff(world.a) == []
    assert _t("staff.refused.not_owner") in world[OWNER_A].said
    assert await world[OWNER_A].state() is None


async def test_a_state_naming_another_owners_shop_adds_nothing_there(world: World) -> None:
    await world[OWNER_A].set_adding_for(world.b)
    await world[OWNER_A].pick(CLERK)
    assert await world.staff(world.b) == []
    assert await world.staff(world.a) == []
