"""Outer middlewares: database session, then customer identity.

Registered as OUTER middlewares on the update observer so they run once per
update, before any router filtering. An inner middleware would run per matching
handler, opening a session even for updates nothing handles.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, User
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gulbot.services.customers import get_or_create_customer


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
