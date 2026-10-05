"""M3 of AUDIT_MULTI_TENANT.md: the chat gate lets in only the shop's OWN group.

THE DEFECT. `ChatGateMiddleware` exists so that nothing from a group reaches
the bot except the shop acting on its own order card. Its contract says "the
shop's own group"; what it checked was "a group, and a button with our
prefix" -- or "a group, and someone with a rejection reason pending". It never
compared the chat with `shops.group_chat_id`.

The order path was safe anyway, one layer down: `admin_orders` re-checks the
chat with `ping_targets` before any transition. But the gate's protection was
only as good as every FUTURE group-reachable handler remembering to do the
same, and an update from a stranger's group still opened a database session
and reached a handler that then had to say no.

THE FIX. The gate itself asks whether the chat is the shop's `group_chat_id`,
after the cheap shape checks and before anything else runs. A foreign group's
tap now reaches nothing: no session, no handler, no reply.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import RecordingSession, bound_session_factory, make_bot

from gulbot.bot.callbacks import OrderAdminCB
from gulbot.bot.factory import build_dispatcher
from gulbot.bot.middlewares import ChatGateMiddleware
from gulbot.bot.states import AdminOrder
from gulbot.models.shop import DEFAULT_WORKING_HOURS

pytestmark = pytest.mark.infra

OWN_GROUP = -1003901602095
FOREIGN_GROUP = -1005550001111
ADMIN_ID = 777_001


def tap_in(chat_id: int, *, update_id: int = 1) -> Update:
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id=f"cb{update_id}",
            from_user=User(id=ADMIN_ID, is_bot=False, first_name="Admin"),
            chat_instance=f"chat{update_id}",
            data=OrderAdminCB(action="confirm", order_id=7).pack(),
            message=Message(
                message_id=update_id,
                date=datetime.now(tz=UTC),
                chat=Chat(id=chat_id, type="supergroup", title="admins"),
                from_user=User(id=1, is_bot=True, first_name="bot"),
                text="card",
            ),
        ),
    )


def reason_in(chat_id: int) -> Update:
    return Update(
        update_id=2,
        message=Message(
            message_id=2,
            date=datetime.now(tz=UTC),
            chat=Chat(id=chat_id, type="supergroup", title="admins"),
            from_user=User(id=ADMIN_ID, is_bot=False, first_name="Admin"),
            text="gul tugadi",
        ),
    )


@pytest_asyncio.fixture
async def world(db: AsyncConnection) -> dict[str, Any]:
    shop = (
        await db.execute(
            text(
                "INSERT INTO shops (name, working_hours, group_chat_id) "
                "VALUES ('S', CAST(:wh AS jsonb), :g) RETURNING id"
            ),
            {"wh": json.dumps(DEFAULT_WORKING_HOURS), "g": OWN_GROUP},
        )
    ).scalar_one()
    bot, recorder = make_bot()
    sessions = bound_session_factory(db)
    dispatcher = build_dispatcher(
        session_factory=sessions,
        shop_id=shop,
        storage=MemoryStorage(),
        schedule_finalize=lambda **kwargs: None,
    )
    return {
        "db": db,
        "shop": shop,
        "bot": bot,
        "recorder": recorder,
        "sessions": sessions,
        "dispatcher": dispatcher,
    }


async def _feed(world: dict[str, Any], update: Update) -> RecordingSession:
    recorder: RecordingSession = world["recorder"]
    recorder.calls.clear()
    await world["dispatcher"].feed_update(world["bot"], update)
    return recorder


# --- through the real dispatcher ------------------------------------------


async def test_an_order_card_tap_from_a_strangers_group_reaches_nothing(
    world: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    """DEFECT IF THIS FAILS. Before the fix the tap passed the gate on its
    prefix alone and reached `admin_orders`, which had to refuse it itself --
    logging the refusal and answering the callback."""
    with caplog.at_level(logging.WARNING, logger="gulbot.bot.admin_orders"):
        recorder = await _feed(world, tap_in(FOREIGN_GROUP))
    assert recorder.calls == [], "a handler answered a tap from another group"
    assert "which is not shop" not in caplog.text, "the order router had to refuse it"


async def test_a_tap_from_the_shops_own_group_still_gets_through(world: dict[str, Any]) -> None:
    """GUARDS THE FIX. A gate that refused every group would pass the test
    above and ship an order card whose buttons do nothing."""
    recorder = await _feed(world, tap_in(OWN_GROUP))
    assert recorder.calls, "the shop's own tap never reached the order router"


async def test_a_shop_with_no_group_lets_no_group_in(world: dict[str, Any]) -> None:
    """DEFECT IF THIS FAILS. NULL is "no group yet", not "any group"."""
    await world["db"].execute(
        text("UPDATE shops SET group_chat_id = NULL WHERE id = :s"), {"s": world["shop"]}
    )
    recorder = await _feed(world, tap_in(OWN_GROUP))
    assert recorder.calls == []


# --- the gate alone ---------------------------------------------------------


async def _passes(world: dict[str, Any], update: Update, state: Any = None) -> bool:
    reached: list[bool] = []

    async def handler(event: Any, data: dict[str, Any]) -> None:
        reached.append(True)

    gate = ChatGateMiddleware(shop_id=world["shop"], session_factory=world["sessions"])
    chat = (update.callback_query.message if update.callback_query else update.message).chat  # type: ignore[union-attr]
    await gate(handler, update, {"event_chat": chat, "state": state})
    return bool(reached)


async def test_a_rejection_reason_from_a_strangers_group_is_dropped(
    world: dict[str, Any],
) -> None:
    """The gate's other hole, closed the same way: the typist's FSM state is
    only half the question; the chat must also be the shop's."""
    dispatcher = world["dispatcher"]
    for chat_id, expected in ((FOREIGN_GROUP, False), (OWN_GROUP, True)):
        context = dispatcher.fsm.get_context(world["bot"], chat_id, ADMIN_ID)
        await context.set_state(AdminOrder.entering_reject_reason)
        assert await _passes(world, reason_in(chat_id), context) is expected, chat_id


async def test_the_gate_checks_the_chat_not_just_the_button(world: dict[str, Any]) -> None:
    assert await _passes(world, tap_in(OWN_GROUP)) is True
    assert await _passes(world, tap_in(FOREIGN_GROUP)) is False
