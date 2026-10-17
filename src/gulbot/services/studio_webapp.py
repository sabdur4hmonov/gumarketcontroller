"""Into Taklifnoma Studio from a Telegram Mini App (CP27.4).

The shop's bot shows a WebAppInfo button (only when the site is https). Telegram
opens /studio/app inside the client and hands the page its launch data in the
URL FRAGMENT (`#tgWebAppData=...`), which never reaches a server log; the page's
own script posts it to /studio/webapp, and this module decides:

1. WHICH BOT. The page says which shop; that shop's OWN bot token (or the legacy
   process BOT_TOKEN, by the same rule as bot/registry.stored_tokens) is the
   only key the data is checked with. Data signed by another shop's bot fails.
2. SIGNED. Telegram's rule (core.telegram.org/bots/webapps, "Validating data
   received via the Mini App"): HMAC-SHA256 over the sorted data-check-string
   with HMAC-SHA256("WebAppData", bot_token) as the key, compared in constant
   time -- aiogram.utils.web_app.check_webapp_signature, the library the bot
   already runs on.
3. FRESH. auth_date at most WEBAPP_MAX_AGE old and not from the future.
4. ONCE. The data's own hash is stored (sha256, UNIQUE); a second post of the
   same launch data is refused -- the replay nonce, bound on the first POST.
5. THIS SHOP'S CUSTOMER, entitled (services/studio.entitled), exactly as for a
   link: the Telegram user must already be this shop's customer.

Then the same session as a link opens (services/studio.open_session).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Final
from urllib.parse import parse_qsl

from aiogram.utils.web_app import check_webapp_signature
from sqlalchemy import delete, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.config import get_settings
from gulbot.models.customer import Customer
from gulbot.models.shop import Shop
from gulbot.models.studio import StudioWebAppUse
from gulbot.services import studio
from gulbot.services.shop_tokens import TokenCipherError, decrypt_token, load_bot_credentials

#: How old launch data may be (Telegram's own data is checked against this).
WEBAPP_MAX_AGE: Final = timedelta(hours=1)
#: How far ahead of our clock a launch may claim to be.
CLOCK_SKEW: Final = timedelta(minutes=1)
#: Launch data is a few hundred bytes; anything far larger is not Telegram's.
INIT_DATA_MAX: Final = 4096


class WebAppRefused(Exception):
    """`reason`: "shop", "signature", "stale", "user", "not_customer",
    "not_entitled" or "replay". Never says more to the client than 403."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def shop_bot_token(session: AsyncSession, *, shop_id: int) -> str | None:
    """THIS shop's bot token, by bot/registry's rule: its own stored token, or
    the process BOT_TOKEN for the one legacy shop allowed it; else None."""
    credential = (await load_bot_credentials(session, shop_ids=[shop_id])).get(shop_id)
    if credential is None:
        return None
    if credential.token_encrypted is not None:
        try:
            return decrypt_token(credential.token_encrypted)
        except TokenCipherError:
            return None
    if credential.uses_process_bot_token:
        return get_settings().bot_token.get_secret_value() or None
    return None


async def open_from_webapp(
    session: AsyncSession,
    *,
    shop_id: int,
    init_data: str,
    bot_username: str | None,
    ip: str | None = None,
    now: datetime | None = None,
) -> studio.NewSession:
    """A studio session from Mini App launch data, or WebAppRefused."""
    now = now or datetime.now(UTC)
    if not init_data or len(init_data) > INIT_DATA_MAX:
        raise WebAppRefused("signature")
    shop_exists = await session.scalar(select(Shop.id).where(Shop.id == shop_id))
    token = await shop_bot_token(session, shop_id=shop_id) if shop_exists else None
    if token is None:
        raise WebAppRefused("shop")
    if not check_webapp_signature(token, init_data):
        await studio.audit(
            session,
            shop_id=shop_id,
            action="webapp_refused",
            customer_id=None,
            reason="signature",
            ip=ip,
        )
        raise WebAppRefused("signature")
    fields = dict(parse_qsl(init_data, strict_parsing=True))
    try:
        auth_date = datetime.fromtimestamp(int(fields["auth_date"]), tz=UTC)
        telegram_id = int(json.loads(fields["user"])["id"])
    except (KeyError, ValueError, TypeError, OverflowError, OSError):
        raise WebAppRefused("user") from None
    if not (now - WEBAPP_MAX_AGE <= auth_date <= now + CLOCK_SKEW):
        await studio.audit(
            session,
            shop_id=shop_id,
            action="webapp_refused",
            customer_id=None,
            reason="stale",
            ip=ip,
        )
        raise WebAppRefused("stale")
    customer_id = await session.scalar(
        select(Customer.id).where(
            Customer.shop_id == shop_id, Customer.telegram_user_id == telegram_id
        )
    )
    if customer_id is None:
        raise WebAppRefused("not_customer")
    if not await studio.entitled(session, shop_id=shop_id, customer_id=int(customer_id)):
        raise WebAppRefused("not_entitled")
    # Launch data older than the window cannot be replayed anyway: prune it.
    await session.execute(
        delete(StudioWebAppUse).where(
            StudioWebAppUse.shop_id == shop_id,
            StudioWebAppUse.used_at < now - 2 * WEBAPP_MAX_AGE,
        )
    )
    try:
        async with session.begin_nested():
            await session.execute(
                insert(StudioWebAppUse).values(
                    shop_id=shop_id,
                    customer_id=int(customer_id),
                    data_hash=hashlib.sha256(fields["hash"].encode()).hexdigest(),
                    auth_date=auth_date,
                    used_at=now,
                )
            )
    except IntegrityError:
        await studio.audit(
            session,
            shop_id=shop_id,
            action="webapp_refused",
            customer_id=int(customer_id),
            reason="replay",
            ip=ip,
        )
        raise WebAppRefused("replay") from None
    return await studio.open_session(
        session,
        shop_id=shop_id,
        customer_id=int(customer_id),
        bot_username=bot_username,
        action="webapp_login",
        ip=ip,
        now=now,
    )
