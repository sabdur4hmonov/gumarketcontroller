"""A Bot whose API calls are answered by scripted Bot API JSON.

`RecordingSession` answers every call with a Message, which is enough for a bot
that only ever SENDS. Onboarding asks questions -- getChat, getChatMember --
and branches on the answers, so it needs a session that answers the way
Telegram does. This one hands aiogram the same JSON envelope Telegram would,
through aiogram's own `check_response`, so parsing and the error classes
(TelegramBadRequest, TelegramUnauthorizedError, TelegramForbiddenError) are
aiogram's, not a copy of them.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import GetUpdates, TelegramMethod
from aiogram.methods.base import TelegramType
from aiogram.types import AcceptedGiftTypes, ChatMemberAdministrator
from pydantic import BaseModel

#: A reply: (HTTP status, JSON body). Built by the helpers below.
Reply = tuple[int, dict[str, Any]]
Script = Callable[[TelegramMethod[Any]], Reply]


def ok(result: Any) -> Reply:
    return 200, {"ok": True, "result": result}


def error(status: int, description: str) -> Reply:
    return status, {"ok": False, "error_code": status, "description": description}


CHAT_NOT_FOUND = error(400, "Bad Request: chat not found")
UNAUTHORIZED = error(401, "Unauthorized")
FORBIDDEN = error(403, "Forbidden: bot is not a member of the channel chat")


def _required_flags(model: type[BaseModel], value: bool) -> dict[str, bool]:
    """Every REQUIRED boolean field of an aiogram model, set to `value`.

    Read from the installed aiogram rather than written out by hand: the Bot
    API keeps adding required flags, and a hand-kept list silently stops
    parsing on the next aiogram upgrade.
    """
    return {
        name: value
        for name, field in model.model_fields.items()
        if field.is_required() and field.annotation is bool
    }


def chat(chat_id: int, kind: str, title: str = "T", username: str | None = None) -> dict[str, Any]:
    """A ChatFullInfo payload, as getChat returns it."""
    body: dict[str, Any] = {
        "id": chat_id,
        "type": kind,
        "title": title,
        "accent_color_id": 0,
        "max_reaction_count": 11,
        "accepted_gift_types": _required_flags(AcceptedGiftTypes, False),
    }
    if username is not None:
        body["username"] = username
    return body


def member(bot_id: int, status: str) -> dict[str, Any]:
    """A ChatMember payload for the bot itself, as getChatMember returns it.

    `status` is one of administrator / member / left / kicked -- the four the
    checks actually branch on.
    """
    user = {"id": bot_id, "is_bot": True, "first_name": "Shop bot", "username": "shop_bot"}
    if status == "administrator":
        return {"status": status, "user": user, **_required_flags(ChatMemberAdministrator, True)}
    if status == "kicked":
        return {"status": status, "user": user, "until_date": 0}
    return {"status": status, "user": user}


def sent_message(chat_id: int, message_id: int = 1) -> dict[str, Any]:
    return {
        "message_id": message_id,
        "date": int(datetime.now(UTC).timestamp()),
        "chat": {"id": chat_id, "type": "supergroup", "title": "G"},
        "text": "ok",
    }


class ScriptedSession(BaseSession):
    """Answers each call from `script`; records every call it was asked."""

    def __init__(self, script: Script, *, idle: float = 0.02) -> None:
        super().__init__()
        self.script = script
        self.idle = idle
        self.calls: list[TelegramMethod[Any]] = []

    async def close(self) -> None:
        return None

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[TelegramType],
        timeout: int | None = None,  # noqa: ASYNC109  aiogram's BaseSession contract
    ) -> TelegramType:
        self.calls.append(method)
        if isinstance(method, GetUpdates):
            # A real long poll waits; an instant empty answer would spin the
            # polling loop without ever yielding to the event loop.
            await asyncio.sleep(self.idle)
        status, body = self.script(method)
        return self.check_response(
            bot=bot, method=method, status_code=status, content=json.dumps(body)
        ).result  # type: ignore[return-value]

    async def stream_content(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def names(self) -> list[str]:
        return [type(call).__name__ for call in self.calls]


def scripted_bot(token: str, script: Script) -> tuple[Bot, ScriptedSession]:
    session = ScriptedSession(script)
    return Bot(token=token, session=session), session
