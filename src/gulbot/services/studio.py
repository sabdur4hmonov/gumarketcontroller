"""Getting into Taklifnoma Studio, the web creator, and the record of it (CP27).

The /shop design (services/shop_auth.py), bound to ONE customer of ONE shop:

    "Taklifnoma yaratish" in THAT shop's bot -> mint_link
    open the link, press Kirish                -> consume_link
    every /studio request                      -> load_session

THE SHOP AND THE CUSTOMER COME FROM THE LINK, AND ONLY FROM THE LINK. The bot
that minted it is the shop's own and the customer is the sender it registered;
nothing in a /studio URL or form can name another shop or another customer.

ENTITLEMENT IS ONE FUNCTION, `entitled`, checked at minting, at spending and on
every request, so changing who may use the studio is a one-line change and
takes effect on the next request. Premium parts stay behind services/premium.py
whatever `entitled` says: the studio only ever calls the same share-page
services the bot calls.
"""

from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.models.customer import Customer
from gulbot.models.shop import Shop, ShopStatus
from gulbot.models.studio import StudioAuditEntry, StudioLink, StudioSession
from gulbot.services.admin_auth import LINK_RATE_LIMIT, LINK_RATE_WINDOW, TOKEN_RE, hash_token

__all__ = [
    "LINK_RATE_LIMIT",
    "LINK_TTL",
    "SESSION_TTL",
    "TOKEN_RE",
    "Creator",
    "NewSession",
    "audit",
    "consume_link",
    "csrf_ok",
    "end_session",
    "entitled",
    "load_session",
    "mint_link",
    "open_session",
]

#: How long a studio link stays usable (the owner's choice: 15 minutes).
LINK_TTL = timedelta(minutes=15)
#: How long a studio session lasts, from login. Absolute, not sliding. Longer
#: than /shop's hour: a creator filling in a whole invitation must not lose it.
SESSION_TTL = timedelta(hours=2)


async def entitled(session: AsyncSession, *, shop_id: int, customer_id: int) -> bool:
    """Who may open the studio. THE ONE PLACE this is decided.

    OWNER DECISION (CP27.1, 2026-10-16): every customer of this shop -- the same
    people the bot's wizard serves today -- unless the shop is paused (its bot
    then answers customers with one "paused" line, and so does the studio).
    Premium designs, photos and music stay behind the CP18 gift either way.
    """
    found = await session.scalar(
        select(Customer.id)
        .join(Shop, Shop.id == Customer.shop_id)
        .where(
            Customer.id == customer_id,
            Customer.shop_id == shop_id,
            Shop.status != ShopStatus.PAUSED.value,
        )
    )
    return found is not None


async def audit(
    session: AsyncSession,
    *,
    shop_id: int,
    action: str,
    customer_id: int | None,
    detail: dict[str, Any] | None = None,
    reason: str | None = None,
    ip: str | None = None,
) -> None:
    """Append one entry, in the caller's transaction."""
    await session.execute(
        insert(StudioAuditEntry).values(
            shop_id=shop_id,
            customer_id=customer_id,
            action=action,
            detail=detail,
            reason=reason,
            ip=ip,
        )
    )


async def mint_link(
    session: AsyncSession,
    *,
    shop_id: int,
    customer_id: int,
    bot_username: str | None,
    now: datetime | None = None,
) -> str | None:
    """A fresh one-time token for this customer of this shop, or None if they
    are not entitled (or have asked too often). The raw token is returned once
    and never stored."""
    now = now or datetime.now(UTC)
    if not await entitled(session, shop_id=shop_id, customer_id=customer_id):
        return None
    recent = await session.scalar(
        select(func.count())
        .select_from(StudioLink)
        .where(
            StudioLink.shop_id == shop_id,
            StudioLink.customer_id == customer_id,
            StudioLink.created_at > now - LINK_RATE_WINDOW,
        )
    )
    if int(recent or 0) >= LINK_RATE_LIMIT:
        await audit(
            session,
            shop_id=shop_id,
            action="link_refused",
            customer_id=customer_id,
            reason="rate",
        )
        return None
    raw = secrets.token_urlsafe(32)
    await session.execute(
        insert(StudioLink).values(
            shop_id=shop_id,
            customer_id=customer_id,
            token_hash=hash_token(raw),
            bot_username=bot_username,
            created_at=now,
            expires_at=now + LINK_TTL,
        )
    )
    await audit(session, shop_id=shop_id, action="link_sent", customer_id=customer_id)
    return raw


@dataclass(frozen=True)
class NewSession:
    token: str  # the raw cookie value; only its hash is stored
    shop_id: int
    customer_id: int
    csrf: str


async def consume_link(
    session: AsyncSession, raw: str, *, ip: str | None = None, now: datetime | None = None
) -> NewSession | None:
    """Spend the link -- once, by compare-and-swap -- and open a session for
    ITS customer of ITS shop. None for an unknown, spent or expired link, or
    one whose customer is no longer entitled."""
    now = now or datetime.now(UTC)
    spent = (
        await session.execute(
            update(StudioLink)
            .where(
                StudioLink.token_hash == hash_token(raw),
                StudioLink.used_at.is_(None),
                StudioLink.expires_at > now,
            )
            .values(used_at=now)
            .returning(StudioLink.shop_id, StudioLink.customer_id, StudioLink.bot_username)
        )
    ).one_or_none()
    if spent is None:
        # Nothing names a shop here: an unknown, spent or expired token.
        return None
    shop_id, customer_id, bot_username = int(spent[0]), int(spent[1]), spent[2]
    if not await entitled(session, shop_id=shop_id, customer_id=customer_id):
        await audit(
            session,
            shop_id=shop_id,
            action="login_refused",
            customer_id=customer_id,
            reason="not_entitled",
            ip=ip,
        )
        return None
    return await open_session(
        session,
        shop_id=shop_id,
        customer_id=customer_id,
        bot_username=bot_username,
        action="login",
        ip=ip,
        now=now,
    )


async def open_session(
    session: AsyncSession,
    *,
    shop_id: int,
    customer_id: int,
    bot_username: str | None,
    action: str,
    ip: str | None,
    now: datetime,
) -> NewSession:
    """A new studio session for an ENTITLED customer -- the caller has checked.
    One way to open one, whether by the bot's link or by the Mini App (CP27.4)."""
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    await session.execute(
        insert(StudioSession).values(
            shop_id=shop_id,
            customer_id=customer_id,
            token_hash=hash_token(token),
            csrf_token=csrf,
            bot_username=bot_username,
            created_at=now,
            expires_at=now + SESSION_TTL,
        )
    )
    await audit(session, shop_id=shop_id, action=action, customer_id=customer_id, ip=ip)
    return NewSession(token=token, shop_id=shop_id, customer_id=customer_id, csrf=csrf)


@dataclass(frozen=True)
class Creator:
    """Who is making this /studio request, for which shop. Every screen and
    every write uses THESE ids; nothing in a URL or a form can name others."""

    shop_id: int
    customer_id: int
    csrf: str
    session_id: int
    #: The shop bot a page made here links back to ("Gul buyurtma qilish").
    bot_username: str | None


async def load_session(
    session: AsyncSession, raw: str | None, *, now: datetime | None = None
) -> Creator | None:
    """The creator behind this cookie, or None: unknown, expired, revoked, or
    no longer entitled (checked on every request, not only at login)."""
    if not raw:
        return None
    now = now or datetime.now(UTC)
    row = (
        await session.execute(
            select(
                StudioSession.id,
                StudioSession.shop_id,
                StudioSession.customer_id,
                StudioSession.csrf_token,
                StudioSession.bot_username,
            ).where(
                StudioSession.token_hash == hash_token(raw),
                StudioSession.revoked_at.is_(None),
                StudioSession.expires_at > now,
            )
        )
    ).one_or_none()
    if row is None:
        return None
    shop_id, customer_id = int(row.shop_id), int(row.customer_id)
    if not await entitled(session, shop_id=shop_id, customer_id=customer_id):
        return None
    return Creator(
        shop_id=shop_id,
        customer_id=customer_id,
        csrf=str(row.csrf_token),
        session_id=int(row.id),
        bot_username=row.bot_username,
    )


def csrf_ok(creator: Creator, submitted: str | None) -> bool:
    return submitted is not None and hmac.compare_digest(creator.csrf, submitted)


async def end_session(
    session: AsyncSession, creator: Creator, *, ip: str | None = None, now: datetime | None = None
) -> None:
    await session.execute(
        update(StudioSession)
        .where(StudioSession.id == creator.session_id)
        .values(revoked_at=now or datetime.now(UTC))
    )
    await audit(
        session, shop_id=creator.shop_id, action="logout", customer_id=creator.customer_id, ip=ip
    )
