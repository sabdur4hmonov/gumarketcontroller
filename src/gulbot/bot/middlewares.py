"""Outer middlewares: chat gate, then database session, then customer identity.

Registered as OUTER middlewares on the update observer so they run once per
update, before any router filtering. An inner middleware would run per matching
handler, opening a session even for updates nothing handles.

ORDER MATTERS. The chat gate is first, so an update from a group never reaches
the session middleware and never reaches the customer middleware -- which would
otherwise register a member of the shop's own admin group as a customer.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Chat, TelegramObject, User
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gulbot.services.customers import get_or_create_customer

#: Chat types the bot will act on, as an ALLOW list rather than a block list.
#: A block list would silently start answering in whatever chat type Telegram
#: invents next; this way an unknown type is ignored, which is the safe default
#: for a bot that also sits in the shop's own admin group.
#:
#: "private"  the customer conversation, which is the entire product.
#: "channel"  the shop's catalogue, read by CP8's indexer. Not a conversation:
#:            the channel router only registers channel_post updates, and
#:            nothing there replies.
SERVED_CHAT_TYPES = frozenset({"private", "channel"})


class ChatGateMiddleware(BaseMiddleware):
    """Ignore anything that is not a private chat or the catalogue channel.

    WHY THIS EXISTS. The bot is a member of the shop's admin group so it can
    post order cards there. Without this gate it also ANSWERS there: `/start`
    returned the language picker into the group, every message it received got
    the "choose a button" fallback with a customer keyboard attached, and the
    admin who typed it was registered as a customer of the shop.

    Telegram's privacy mode hid most of that -- while it is on, a bot in a group
    only receives commands, replies and mentions. But `/start` is a command, so
    that half was always visible, and promoting the bot to group administrator
    turns privacy mode off and exposes the rest. Being an admin of your own
    group is a normal thing to do, so this cannot rest on a Telegram setting.

    Dropping the update here rather than filtering per router means a router
    added later cannot forget the rule, and means no database session is opened
    for traffic the bot has no business in.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Populated by aiogram's own UserContextMiddleware, which is registered
        # in Dispatcher.__init__ and therefore runs ahead of this one.
        chat: Chat | None = data.get("event_chat")
        if chat is not None and chat.type not in SERVED_CHAT_TYPES:
            return None
        return await handler(event, data)


class DbSessionMiddleware(BaseMiddleware):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self.session_factory() as session:
            data["session"] = session
            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise


class CustomerMiddleware(BaseMiddleware):
    """Resolve the customer for this shop, creating them on first contact."""

    def __init__(self, shop_id: int) -> None:
        self.shop_id = shop_id

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: User | None = data.get("event_from_user")
        session: AsyncSession | None = data.get("session")
        if user is not None and session is not None and not user.is_bot:
            customer, created = await get_or_create_customer(
                session, shop_id=self.shop_id, telegram_user_id=user.id
            )
            data["customer"] = customer
            data["customer_created"] = created
            data["lang"] = customer.lang
        data.setdefault("shop_id", self.shop_id)
        return await handler(event, data)
