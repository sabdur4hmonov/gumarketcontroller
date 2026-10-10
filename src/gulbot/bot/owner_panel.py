"""/panel in a SHOP's bot: its owner's one-time link to /shop (CP20).

A middleware, not a router handler, for one reason: in a shop's bot every
private message reaches `CustomerMiddleware`, which registers the sender as a
customer of the shop. An owner asking for their panel is not a customer, so
the request is answered BEFORE that middleware and goes no further. It also
sits before the pause check: a paused shop's owner still gets into the panel.

Only "/panel", only in a private chat, only from a Telegram id in THIS shop's
`owner_telegram_ids`. Anything else -- including "/panel" from a customer --
passes through untouched and is handled as before. The link is minted for
THIS shop, which is the only thing that will ever name the shop the session
can see (services/shop_auth.py).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import LinkPreviewOptions, Message, TelegramObject, Update
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.i18n import t
from gulbot.services import shop_auth
from gulbot.services.shop_language import shop_language
from gulbot.web.links import base_url, pages_available

log = logging.getLogger("gulbot.bot.owner_panel")

COMMAND = "/panel"


def _asks_for_the_panel(message: Message | None) -> bool:
    if message is None or message.chat.type != "private" or message.from_user is None:
        return False
    first = (message.text or "").split(maxsplit=1)[0] if message.text else ""
    return first == COMMAND or first.startswith(COMMAND + "@")


class OwnerPanelMiddleware(BaseMiddleware):
    def __init__(self, shop_id: int) -> None:
        self.shop_id = shop_id

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        message = event.message if isinstance(event, Update) else None
        session: AsyncSession | None = data.get("session")
        if session is None or not _asks_for_the_panel(message):
            return await handler(event, data)
        assert message is not None and message.from_user is not None
        owner = message.from_user.id
        if not await shop_auth.is_owner(session, shop_id=self.shop_id, telegram_id=owner):
            return await handler(event, data)

        lang = await shop_language(session, shop_id=self.shop_id)
        if not pages_available():
            # Production without HTTPS: a Secure cookie could not be set, and
            # an http:// login link must never be sent.
            await message.answer(t("panel.unavailable", lang))
            return None
        raw = await shop_auth.mint_login_link(session, shop_id=self.shop_id, telegram_id=owner)
        if raw is None:
            await message.answer(t("panel.link_refused", lang))
            return None
        log.info("shop %s: panel link sent to owner %s", self.shop_id, owner)
        minutes = int(shop_auth.LINK_TTL.total_seconds() // 60)
        await message.answer(
            t("panel.link", lang, url=f"{base_url()}/shop/login/{raw}", minutes=minutes),
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        return None
