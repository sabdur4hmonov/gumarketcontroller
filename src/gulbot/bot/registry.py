"""shop_id -> Bot, for code that sends on behalf of more than one shop.

C1/C2 of AUDIT_MULTI_TENANT.md gave every outbox row its own shop's bot; this
module is where "its own shop's bot" is decided.

WHICH TOKEN (`stored_tokens`), in order:

1. The shop's own token, decrypted from `shops.bot_token_encrypted`. Always,
   the legacy shop included, once it has one.
2. The process BOT_TOKEN -- but ONLY for the shop flagged
   `uses_process_bot_token`, the single shop that existed before per-shop
   tokens. LOGGED at WARNING by every registry that falls back, because the
   fallback is meant to stop being used.
3. Otherwise `ShopBotUnavailable`: one clear sentence naming the shop and what
   to set. The send paths catch it per row, so one shop without a bot fails
   loudly on its own and every other shop is still served.

LIFETIME. One registry per task call, closed in a `finally` by its owner.
`build_bot()` is deliberately uncached (see worker/tasks.py): an aiohttp session
that outlives its Celery task hands the next task a client bound to a closed
event loop. So this caches only WITHIN one call -- and resolves each shop once
per call, which is also what keeps the fallback warning to one line per shop.

ONE BOT PER TOKEN, not per shop: shops sharing a token share a Bot and its
aiohttp session.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Mapping
from types import TracebackType

from aiogram import Bot
from aiogram.utils.token import TokenValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.sending.transport import ShopBotUnavailable
from gulbot.services.shop_tokens import (
    ShopBotCredential,
    TokenCipherError,
    decrypt_token,
    load_bot_credentials,
)

log = logging.getLogger("gulbot.bot.registry")

#: shop_id -> that shop's token, or None for the process-wide BOT_TOKEN.
#: Raises ShopBotUnavailable when neither is allowed.
TokenResolver = Callable[[int], str | None]
#: token (None = the process-wide one) -> a new Bot.
BotFactory = Callable[[str | None], Bot]


def build_bot_for(token: str | None) -> Bot:
    """The production factory, looked up at CALL time.

    Looked up late, and called with NO argument for the process token, on
    purpose: the lifetime and outage tests replace `factory.build_bot` with a
    zero-argument wrapper around the real one, and that seam must keep seeing
    every Bot the send path builds.
    """
    from gulbot.bot import factory

    return factory.build_bot() if token is None else factory.build_bot(token)


def _process_token_is_set() -> bool:
    # Asked of the factory, late, so the answer always agrees with what
    # `build_bot()` would actually use -- including under the tests' seam.
    from gulbot.bot import factory

    return factory.process_token_is_set()


def stored_tokens(credentials: Mapping[int, ShopBotCredential]) -> TokenResolver:
    """The resolution rule in the module docstring, over loaded credentials."""

    def token_for(shop_id: int) -> str | None:
        credential = credentials.get(shop_id)
        if credential is None:
            raise ShopBotUnavailable(
                shop_id, "no such shop was loaded, so no bot token is known for it"
            )
        if credential.token_encrypted is not None:
            try:
                return decrypt_token(credential.token_encrypted)
            except TokenCipherError as unreadable:
                raise ShopBotUnavailable(shop_id, str(unreadable)) from None
        if credential.uses_process_bot_token:
            if not _process_token_is_set():
                raise ShopBotUnavailable(
                    shop_id,
                    "it has no token of its own (shops.bot_token_encrypted is empty), and "
                    "BOT_TOKEN -- the legacy fallback it is allowed -- is not set",
                )
            log.warning(
                "shop %s has no bot token of its own; using the process BOT_TOKEN (legacy "
                "fallback). Store this shop's token to retire the fallback.",
                shop_id,
            )
            return None
        raise ShopBotUnavailable(
            shop_id,
            "no bot token is stored for it (shops.bot_token_encrypted is empty) and it is "
            "not the legacy shop allowed to use BOT_TOKEN",
        )

    return token_for


class BotRegistry:
    def __init__(
        self, *, token_for: TokenResolver, bot_factory: BotFactory = build_bot_for
    ) -> None:
        self._token_for = token_for
        self._bot_factory = bot_factory
        self._by_shop: dict[int, Bot] = {}
        self._by_token: dict[str | None, Bot] = {}

    def bot_for(self, shop_id: int) -> Bot:
        """This shop's Bot, or ShopBotUnavailable. Failures are not cached:
        a shop fixed mid-call is served on its next row."""
        bot = self._by_shop.get(shop_id)
        if bot is not None:
            return bot
        token = self._token_for(shop_id)
        bot = self._by_token.get(token)
        if bot is None:
            try:
                bot = self._bot_factory(token)
            except TokenValidationError:
                # aiogram's message carries no token, but a crash here would
                # stop a whole tick; this is one shop's problem.
                raise ShopBotUnavailable(
                    shop_id, "its stored token is not one Telegram would accept"
                ) from None
            self._by_token[token] = bot
        self._by_shop[shop_id] = bot
        return bot

    async def close(self) -> None:
        bots, self._by_token, self._by_shop = list(self._by_token.values()), {}, {}
        for bot in bots:
            await bot.session.close()

    async def __aenter__(self) -> BotRegistry:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()


async def registry_for(
    session: AsyncSession,
    *,
    shop_ids: Collection[int] | None = None,
    bot_factory: BotFactory = build_bot_for,
) -> BotRegistry:
    """A registry over the shops' stored credentials, loaded now.

    Loaded up front, still encrypted, so `bot_for` needs no database and a
    tick's `transport_for` can stay synchronous. A shop created after this
    load simply is not in it -- its row fails loudly this tick and is served
    the next.
    """
    credentials = await load_bot_credentials(session, shop_ids=shop_ids)
    return BotRegistry(token_for=stored_tokens(credentials), bot_factory=bot_factory)
