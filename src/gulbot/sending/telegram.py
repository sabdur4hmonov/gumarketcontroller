"""The real transport: aiogram behind the Transport protocol.

Every Telegram-specific failure is translated into a SendResult here, so the
dispatcher never sees an aiogram exception and never has to know what a 429 is.

429 handling honours `retry_after` EXACTLY. Telegram tells us how long to wait;
guessing a backoff instead is how a bot turns a short throttle into a long one.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.types import Message

from gulbot.sending.transport import SendResult

log = logging.getLogger("gulbot.sending.telegram")


class TelegramTransport:
    """Adapts aiogram to the narrow interface the dispatcher uses."""

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def send_text(self, *, chat_id: int, text: str) -> SendResult:
        return await self._attempt(self._bot.send_message(chat_id=chat_id, text=text), chat_id)

    async def send_photo(self, *, chat_id: int, file_id: str, caption: str) -> SendResult:
        """CP9. One call, so a reminder with a bouquet is still atomic.

        `file_id` is Telegram's own identifier for the photo already in the
        shop's channel, so nothing is uploaded and nothing is copied -- which
        also means the caption is entirely ours, rather than the shop's raw
        post with its phone numbers and stale prices in it.
        """
        return await self._attempt(
            self._bot.send_photo(chat_id=chat_id, photo=file_id, caption=caption), chat_id
        )

    async def _attempt(self, call: Awaitable[Message], chat_id: int) -> SendResult:
        """One place where a Telegram failure becomes a SendResult.

        Shared so `send_photo` cannot drift from `send_text` on the three cases
        that carry policy: 429 honours retry_after exactly, 403 is a block and
        not an error to retry, everything else is a plain failure.
        """
        try:
            message = await call
        except TelegramRetryAfter as exc:
            # Telegram states the wait. Honour it exactly.
            log.warning("rate limited for chat=%s retry_after=%s", chat_id, exc.retry_after)
            return SendResult.rate_limited(float(exc.retry_after))
        except TelegramForbiddenError:
            # The customer blocked the bot. Not an error to retry.
            log.info("blocked by chat=%s", chat_id)
            return SendResult.forbidden()
        except TelegramAPIError as exc:
            log.warning("send failed for chat=%s: %s", chat_id, type(exc).__name__)
            return SendResult.failed(type(exc).__name__)
        return SendResult.sent(message.message_id)
