"""Per-update menu visibility. This context is NEVER publication authorization."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

announcement_visible: ContextVar[bool] = ContextVar("announcement_visible", default=False)


class AnnouncementMenuMiddleware(BaseMiddleware):
    def __init__(self, shop_id: int) -> None:
        self.shop_id = shop_id

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        allowed = False
        if isinstance(event, Update):
            message = event.message
            callback = event.callback_query
            user = callback.from_user if callback else message.from_user if message else None
            chat = (
                callback.message.chat
                if callback and callback.message
                else message.chat
                if message
                else None
            )
            if user and chat and chat.type == "private":
                # Shared reminder keyboards import this context too. Load the
                # publishing service only for a bot update, keeping CP9's
                # read-only send path independent of CP8's indexer.
                from gulbot.services.announcements import may_publish

                allowed = await may_publish(data["session"], shop_id=self.shop_id, actor=user.id)
        token = announcement_visible.set(allowed)
        try:
            return await handler(event, data)
        finally:
            announcement_visible.reset(token)
