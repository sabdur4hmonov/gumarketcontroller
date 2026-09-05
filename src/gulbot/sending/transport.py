"""The narrow interface the tick sends through.

Everything the dispatcher knows about Telegram is `send_text` and, since CP9,
`send_photo`. Tests inject a fake; production injects the aiogram-backed one.

CP9 widened this rather than dispatch: a reminder that carries a bouquet is
still ONE API call, so CP6's contract -- every row of a group marked in a single
UPDATE, no partially-sent state -- holds unchanged. That is why the reminder text
becomes the photo's CAPTION instead of a separate message.

`Attachment` is deliberately just a file id and a caption. The dispatcher must
not learn what a product is; composing one is `sending/attach.py`'s job.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from aiogram.types import InlineKeyboardMarkup


@dataclass(frozen=True)
class SendResult:
    """What happened. Deliberately not an exception for the expected cases."""

    ok: bool
    #: Telegram's message_id, when it accepted.
    message_id: int | None = None
    #: Machine-readable reason, stored in message_log.error_code.
    error_code: str | None = None
    #: Set when Telegram returned 429. Honoured EXACTLY, never guessed at.
    retry_after: float | None = None
    #: Set when the customer has blocked the bot (403).
    blocked: bool = False

    @classmethod
    def sent(cls, message_id: int) -> SendResult:
        return cls(ok=True, message_id=message_id)

    @classmethod
    def rate_limited(cls, retry_after: float) -> SendResult:
        return cls(ok=False, error_code="rate_limited", retry_after=retry_after)

    @classmethod
    def forbidden(cls) -> SendResult:
        return cls(ok=False, error_code="bot_blocked", blocked=True)

    @classmethod
    def failed(cls, error_code: str) -> SendResult:
        return cls(ok=False, error_code=error_code)


#: Telegram's limit for a photo caption. A reminder longer than this cannot be
#: sent as one photo message, and CP9 falls back to bare text rather than
#: truncating a reminder or splitting it into two sends.
CAPTION_LIMIT = 1024


@dataclass(frozen=True)
class Attachment:
    """A photo message, already composed. No catalogue types leak past here."""

    file_id: str
    caption: str
    #: CP10's "Buyurtma berish" button. Optional so the transport stays usable
    #: for a bouquet shown without an order path -- and so dispatch still knows
    #: nothing about what the button does.
    reply_markup: InlineKeyboardMarkup | None = None


class Transport(Protocol):
    """The only capabilities the dispatcher has."""

    async def send_text(self, *, chat_id: int, text: str) -> SendResult: ...

    async def send_photo(
        self,
        *,
        chat_id: int,
        file_id: str,
        caption: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> SendResult: ...
