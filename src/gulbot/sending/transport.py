"""The narrow interface the tick sends through.

Everything the dispatcher knows about Telegram is `send_text`. Tests inject a
fake; production injects the aiogram-backed one. That is also the seam CP9 will
use to attach bouquet suggestions -- a richer transport, not a change to the
dispatch logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


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


class Transport(Protocol):
    """The only capability the dispatcher has."""

    async def send_text(self, *, chat_id: int, text: str) -> SendResult: ...
