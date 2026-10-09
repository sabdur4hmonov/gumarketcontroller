"""One shop's bot, as a customer drives it, for the share-page tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from itertools import count
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Chat, Location, Message, Update, User
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import (
    RecordingSession,
    bound_session_factory,
    callback_update,
    feed,
    photo_sizes,
    text_update,
)

from gulbot.bot.factory import build_dispatcher
from gulbot.models.shop import DEFAULT_WORKING_HOURS

_updates = count(1)


async def make_shop(db: AsyncConnection, name: str) -> int:
    row = await db.execute(
        text(
            "INSERT INTO shops (name, working_hours) VALUES (:n, CAST(:wh AS jsonb)) RETURNING id"
        ),
        {"n": name, "wh": json.dumps(DEFAULT_WORKING_HOURS)},
    )
    return int(row.scalar_one())


class ShopBot:
    """A shop's dispatcher and its bot, recorded rather than sent."""

    def __init__(self, db: AsyncConnection, shop_id: int, *, bot_id: int, username: str) -> None:
        self.db, self.shop_id = db, shop_id
        self.recorder = RecordingSession()
        self.bot = Bot(token=f"{bot_id}:{'A' * 35}", session=self.recorder)
        # aiogram caches getMe on the Bot; the router reads the username from it.
        self.bot._me = User(id=bot_id, is_bot=True, first_name=username, username=username)  # noqa: SLF001
        self.dispatcher: Dispatcher = build_dispatcher(
            session_factory=bound_session_factory(db), shop_id=shop_id, storage=MemoryStorage()
        )

    async def say(self, body: str, *, user: int) -> None:
        await feed(
            self.dispatcher, self.bot, text_update(body, user_id=user, update_id=next(_updates))
        )

    async def tap(self, data: str, *, user: int) -> None:
        await feed(
            self.dispatcher, self.bot, callback_update(data, user_id=user, update_id=next(_updates))
        )

    async def pin(self, *, user: int, lat: float, lon: float) -> None:
        update = Update(
            update_id=next(_updates),
            message=Message(
                message_id=next(_updates),
                date=datetime.now(tz=UTC),
                chat=Chat(id=user, type="private"),
                from_user=User(id=user, is_bot=False, first_name="Aziz"),
                location=Location(latitude=lat, longitude=lon),
            ),
        )
        await feed(self.dispatcher, self.bot, update)

    async def photo(self, file_id: str, *, user: int) -> None:
        """A photo message, as Telegram sends one: several sizes, largest last."""
        update = Update(
            update_id=next(_updates),
            message=Message(
                message_id=next(_updates),
                date=datetime.now(tz=UTC),
                chat=Chat(id=user, type="private"),
                from_user=User(id=user, is_bot=False, first_name="Aziz"),
                photo=photo_sizes(file_id),
            ),
        )
        await feed(self.dispatcher, self.bot, update)

    def texts(self) -> list[str]:
        return self.recorder.sent_texts

    def last(self) -> str:
        return self.recorder.sent_texts[-1]

    def markups(self) -> list[Any]:
        return [getattr(call, "reply_markup", None) for call in self.recorder.calls]

    def clear(self) -> None:
        self.recorder.calls.clear()


def every_customer_has_the_gift(monkeypatch: Any) -> None:
    """For tests of the premium parts' MECHANICS (the music player, the
    gallery, the sections): their customers have unlocked premium, as a
    customer with a confirmed order would have. The GATING itself -- locked
    before, unlocked per shop after a confirmed order -- is proven in
    tests/test_premium_gift.py, never by this shortcut."""
    from gulbot.services import premium

    async def unlocked(session: Any, *, shop_id: int, customer_id: int) -> bool:
        return True

    monkeypatch.setattr(premium, "unlocked", unlocked)
