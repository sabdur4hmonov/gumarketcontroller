"""Token buckets for Telegram's published limits.

Two independent buckets, both of which must admit a send:

* GLOBAL  ~30 messages/second across the whole bot
* PER CHAT ~1 message/second to any single chat

BOTH ARE PER BOT, because Telegram's are: every shop has its own bot, so every
bucket is keyed by the shop it sends for. One limiter serves a whole tick, and
the tick sends for every shop; a single global bucket throttled the entire
fleet to one bot's 28 msg/s (H4 of AUDIT_MULTI_TENANT.md), and a shared
per-chat bucket paced a person who is a customer of two shops as one chat.

Pure except for the clock and the sleeper, both injectable, so the tests assert
actual waits instead of watching the wall clock.

This governs OUR pacing. A 429 from Telegram is a different thing entirely and
is handled by honouring `retry_after` exactly -- see the sender. Backing off by
a guessed amount after a 429 is how a bot earns a longer ban.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

#: Telegram's documented ceilings, with a little headroom.
GLOBAL_RATE_PER_SECOND = 28.0
PER_CHAT_RATE_PER_SECOND = 1.0
GLOBAL_BURST = 28.0
PER_CHAT_BURST = 1.0

Clock = Callable[[], float]
Sleeper = Callable[[float], Awaitable[None]]


@dataclass
class TokenBucket:
    rate: float
    burst: float
    _tokens: float = field(init=False)
    #: None until the first refill. NOT 0.0: a clock that legitimately starts
    #: at zero would make every elapsed interval look like "never refilled",
    #: silently discarding the time and over-charging the caller.
    _updated: float | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self._tokens = self.burst

    def _refill(self, now: float) -> None:
        if self._updated is None:
            self._updated = now
            return
        elapsed = max(0.0, now - self._updated)
        self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
        self._updated = now

    def wait_time(self, now: float) -> float:
        """Seconds to wait before a token is available. 0.0 if one is ready."""
        self._refill(now)
        if self._tokens >= 1.0:
            return 0.0
        return (1.0 - self._tokens) / self.rate

    def consume(self, now: float) -> None:
        self._refill(now)
        self._tokens -= 1.0


class RateLimiter:
    """Per-bot global + per-chat pacing for outbound sends. See the module
    docstring: `shop_id` names the bot, because each shop has exactly one."""

    def __init__(
        self,
        *,
        clock: Clock,
        sleeper: Sleeper | None = None,
        global_rate: float = GLOBAL_RATE_PER_SECOND,
        per_chat_rate: float = PER_CHAT_RATE_PER_SECOND,
    ) -> None:
        self._clock = clock
        self._sleep = sleeper or asyncio.sleep
        self._global_rate = global_rate
        self._per_chat_rate = per_chat_rate
        self._per_bot: dict[int, TokenBucket] = {}
        self._per_chat: dict[tuple[int, int], TokenBucket] = {}

    def _bot_bucket(self, shop_id: int) -> TokenBucket:
        if shop_id not in self._per_bot:
            self._per_bot[shop_id] = TokenBucket(rate=self._global_rate, burst=GLOBAL_BURST)
        return self._per_bot[shop_id]

    def _chat_bucket(self, shop_id: int, chat_id: int) -> TokenBucket:
        key = (shop_id, chat_id)
        if key not in self._per_chat:
            self._per_chat[key] = TokenBucket(rate=self._per_chat_rate, burst=PER_CHAT_BURST)
        return self._per_chat[key]

    def wait_time(self, chat_id: int, *, shop_id: int) -> float:
        now = self._clock()
        return max(
            self._bot_bucket(shop_id).wait_time(now),
            self._chat_bucket(shop_id, chat_id).wait_time(now),
        )

    async def acquire(self, chat_id: int, *, shop_id: int) -> float:
        """Block until THIS SHOP'S BOT may send to this chat. Returns how long
        it waited. `shop_id` is required: a default would put every caller
        that forgot it back into one shared bucket."""
        waited = 0.0
        while True:
            delay = self.wait_time(chat_id, shop_id=shop_id)
            if delay <= 0.0:
                break
            await self._sleep(delay)
            waited += delay
        now = self._clock()
        self._bot_bucket(shop_id).consume(now)
        self._chat_bucket(shop_id, chat_id).consume(now)
        return waited
