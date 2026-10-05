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

from collections.abc import Callable
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
    #: Set when Telegram never answered at all -- a timeout, a connection
    #: error, or an answer that is not the Bot API (an HTML error page) -- rather
    #: than a refusal. The only kind of failure the circuit breaker
    #: counts, because it is the only kind that says Telegram is unreachable
    #: rather than that one message or one chat has a problem.
    network: bool = False

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

    @classmethod
    def unreachable(cls, error_code: str) -> SendResult:
        return cls(ok=False, error_code=error_code, network=True)


#: Consecutive network failures after which a tick stops sending.
BREAKER_THRESHOLD = 3


class CircuitBreaker:
    """Stop a tick that is sending into a Telegram outage.

    Found in the pre-deployment audit, pass 5. In an outage nothing answers,
    so every send waits out the full request timeout before failing. A tick
    attempts every claimed row one after another, so a hundred due rows cost a
    hundred timeouts -- and the worker runs one task at a time, so everything
    queued behind that tick, the health check included, waits for all of it.

    THREE CONSECUTIVE NETWORK FAILURES, and only those. A 403, a 429 or a 400
    is Telegram answering, which proves it is up; it resets the count exactly
    as a success does. Counting them would let three customers who blocked the
    bot stop the reminders of everyone after them.

    Per tick, never shared: a tick that trips stops, and the next tick starts
    with a closed breaker and tries again. That is the whole recovery path --
    no half-open state, no timers, because the beat already is one.

    ONE PER SHOP since H5 of AUDIT_MULTI_TENANT.md: the ticks hold these
    through `ShopBreakers`, never one across the whole batch.
    """

    def __init__(self, threshold: int = BREAKER_THRESHOLD) -> None:
        self.threshold = threshold
        self.consecutive = 0

    def record(self, outcome: SendResult) -> None:
        self.consecutive = self.consecutive + 1 if outcome.network else 0

    @property
    def open(self) -> bool:
        return self.consecutive >= self.threshold


#: Different shops that must go unanswered in a row -- nothing answering any
#: shop in between -- before a tick reads it as Telegram (or our network) being
#: down rather than as one shop's bot.
FLEET_BREAKER_SHOPS = 3


class ShopBreakers:
    """A `CircuitBreaker` per shop, and one rule across them. Per tick.

    H5 of AUDIT_MULTI_TENANT.md. The outbox spans every shop, and one breaker
    for the batch let three timeouts from ONE shop's bot hand back every other
    shop's rows -- each tick, for as long as that bot stayed broken. Now a shop
    that trips has only its own rows handed back, and the rest keep sending.

    THE FLEET TRIP keeps pass 5's guarantee. Per-shop breakers alone would make
    a real Telegram outage cost BREAKER_THRESHOLD timeouts PER SHOP -- hours,
    at a thousand shops, on a worker that runs one task at a time. So when
    FLEET_BREAKER_SHOPS different shops have each gone unanswered with nothing
    answering in between, every shop is treated as tripped. One or two broken
    bots can never cause that; an outage reaches it within at most
    (FLEET_BREAKER_SHOPS - 1) x BREAKER_THRESHOLD + 1 sends.
    """

    def __init__(
        self, threshold: int = BREAKER_THRESHOLD, fleet_shops: int = FLEET_BREAKER_SHOPS
    ) -> None:
        self.threshold = threshold
        self.fleet_shops = fleet_shops
        self._by_shop: dict[int, CircuitBreaker] = {}
        #: Shops with a network failure since anything last answered.
        self._unanswered: set[int] = set()

    def record(self, shop_id: int, outcome: SendResult) -> str | None:
        """Count one outcome. Returns "shop" or "fleet" when THIS outcome is
        the one that tripped it, so the caller logs each trip exactly once."""
        shop = self._by_shop.setdefault(shop_id, CircuitBreaker(self.threshold))
        was_shop, was_fleet = shop.open, self.fleet_open
        shop.record(outcome)
        if outcome.network:
            self._unanswered.add(shop_id)
        else:
            self._unanswered.clear()
        if self.fleet_open and not was_fleet:
            return "fleet"
        if shop.open and not was_shop:
            return "shop"
        return None

    @property
    def fleet_open(self) -> bool:
        return len(self._unanswered) >= self.fleet_shops

    def open_for(self, shop_id: int) -> bool:
        if self.fleet_open:
            return True
        shop = self._by_shop.get(shop_id)
        return shop is not None and shop.open

    def for_shop(self, shop_id: int) -> ShopBreaker:
        return ShopBreaker(self, shop_id)


class ShopBreaker:
    """One shop's view of `ShopBreakers`, shaped like a `CircuitBreaker`, for
    code that sends several messages for one shop (the order-ping fan-out)."""

    def __init__(self, breakers: ShopBreakers, shop_id: int) -> None:
        self._breakers = breakers
        self._shop_id = shop_id
        #: What the last `record` tripped, if anything; see ShopBreakers.record.
        self.tripped: str | None = None

    def record(self, outcome: SendResult) -> None:
        self.tripped = self._breakers.record(self._shop_id, outcome) or self.tripped

    @property
    def open(self) -> bool:
        return self._breakers.open_for(self._shop_id)


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
    """The only capabilities the dispatcher has.

    `copy_message` is CP11's, and only the browse screen uses it: it
    reproduces the shop's own channel post verbatim -- their words, their
    formatting, their line breaks -- with no parse_mode of ours involved, so
    a caption containing `<` or `&` cannot make the send fail. The reminder
    path deliberately does NOT use it: a reminder has to carry the reminder
    TEXT, and a copy cannot.
    """

    async def send_text(
        self,
        *,
        chat_id: int,
        text: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> SendResult: ...

    async def send_photo(
        self,
        *,
        chat_id: int,
        file_id: str,
        caption: str,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> SendResult: ...

    async def copy_message(
        self,
        *,
        chat_id: int,
        from_chat_id: int,
        message_id: int,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> SendResult: ...


class ShopBotUnavailable(LookupError):
    """There is no bot that may speak for this shop.

    Raised by whatever resolves `transport_for(shop_id)` -- no stored token and
    no fallback, a token that cannot be decrypted, one aiogram rejects -- and
    caught by every send path, which fails THAT shop's row, logs this one
    sentence, and carries on with every other shop. `reason` says what to fix
    and never carries a token, a ciphertext or a key.
    """

    def __init__(self, shop_id: int, reason: str) -> None:
        super().__init__(f"shop {shop_id} has no usable bot: {reason}")
        self.shop_id = shop_id
        self.reason = reason


#: shop_id -> the Transport that speaks as THAT shop's bot.
#:
#: C1/C2 of AUDIT_MULTI_TENANT.md. Both ticks drain an outbox that spans every
#: shop, and used to push all of it through one Bot. They now resolve a
#: transport per row, from the row's own shop_id.
TransportFor = Callable[[int], Transport]


def per_shop(transport: Transport | None, transport_for: TransportFor | None) -> TransportFor:
    """The ticks' one way in. Exactly one of the two, never a guess.

    `transport_for` is what the worker passes: a transport per shop.
    `transport` alone means every shop in the batch uses that one -- right for
    tests and for the order router's immediate flush (one order, so one shop),
    wrong for a worker draining every shop, which is why the worker no longer
    passes it.
    """
    if (transport is None) == (transport_for is None):
        raise TypeError("pass exactly one of transport= or transport_for=")
    if transport_for is not None:
        return transport_for
    single = transport
    return lambda shop_id: single  # type: ignore[return-value]
