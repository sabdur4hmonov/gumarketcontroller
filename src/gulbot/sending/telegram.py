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
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.types import InlineKeyboardMarkup, Message

from gulbot.sending.transport import SendResult

log = logging.getLogger("gulbot.sending.telegram")


class TelegramTransport:
    """Adapts aiogram to the narrow interface the dispatcher uses."""

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def send_text(
        self,
        *,
        chat_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> SendResult:
        return await self._attempt(
            self._bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup),
            chat_id,
        )

    async def send_photo(
        self,
        *,
        chat_id: int,
        file_id: str,
        caption: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> SendResult:
        """CP9. One call, so a reminder with a bouquet is still atomic.

        `file_id` is Telegram's own identifier for the photo already in the
        shop's channel, so nothing is uploaded and nothing is copied -- which
        also means the caption is entirely ours, rather than the shop's raw
        post with its phone numbers and stale prices in it.
        """
        return await self._attempt(
            self._bot.send_photo(
                chat_id=chat_id, photo=file_id, caption=caption, reply_markup=reply_markup
            ),
            chat_id,
        )

    async def copy_message(
        self,
        *,
        chat_id: int,
        from_chat_id: int,
        message_id: int,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> SendResult:
        """Reproduce a channel post exactly as the shop wrote it.

        Telegram copies the message server-side, so the caption arrives with
        the shop's own entities intact and nothing of ours is parsed over the
        top of it. That is the point: passing their text through `send_photo`
        with parse_mode=HTML would make a caption containing `<` or `&` fail
        outright, and escaping it would stop being verbatim.

        An ALBUM copies its anchor photo only. `copyMessages` can take the
        whole group but cannot carry a keyboard, and the order button is
        worth more than the extra angles.

        Returns the NEW message's id, not the original's -- `copyMessage`
        answers with a MessageId rather than a Message, so this is the one
        call that cannot share `_attempt`'s return path.
        """
        try:
            copied = await self._bot.copy_message(
                chat_id=chat_id,
                from_chat_id=from_chat_id,
                message_id=message_id,
                reply_markup=reply_markup,
            )
        except TelegramRetryAfter as exc:
            log.warning("rate limited for chat=%s retry_after=%s", chat_id, exc.retry_after)
            return SendResult.rate_limited(float(exc.retry_after))
        except TelegramForbiddenError:
            log.info("blocked by chat=%s", chat_id)
            return SendResult.forbidden()
        except TelegramNetworkError as exc:
            log.warning("copy got no answer for chat=%s: %s", chat_id, type(exc).__name__)
            return SendResult.unreachable(type(exc).__name__)
        except TelegramAPIError as exc:
            log.warning("copy failed for chat=%s: %s", chat_id, type(exc).__name__)
            return SendResult.failed(type(exc).__name__)
        return SendResult.sent(copied.message_id)

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
        except TelegramNetworkError as exc:
            # Nothing answered: a timeout or a connection error. BEFORE the
            # generic branch, because it is a subclass of TelegramAPIError. Still
            # a plain failure to the row; the flag is what the breaker counts.
            log.warning("send got no answer for chat=%s: %s", chat_id, type(exc).__name__)
            return SendResult.unreachable(type(exc).__name__)
        except TelegramAPIError as exc:
            log.warning("send failed for chat=%s: %s", chat_id, type(exc).__name__)
            return SendResult.failed(type(exc).__name__)
        return SendResult.sent(message.message_id)
