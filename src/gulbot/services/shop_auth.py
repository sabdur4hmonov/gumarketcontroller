"""Getting into a shop's own panel, /shop, and the record of what happens there (CP20).

Same design as the platform admin's (services/admin_auth.py), bound to ONE shop:

    /panel in THAT shop's bot, from one of its owners -> mint_login_link
    open the link, press Kirish                       -> consume_login_link
    every /shop request                                -> load_session

THE SHOP COMES FROM THE LINK, AND ONLY FROM THE LINK. The bot that minted it
is the shop's own; the session it opens names that shop; every /shop screen
reads `ShopOwner.shop_id` and nothing in the URL. An owner of two shops holds
two sessions, one per bot, and neither can see the other's shop.

OWNERSHIP IS CHECKED THREE TIMES -- at minting, at spending, and on every
request -- against `shops.owner_telegram_ids`, so removing an owner from a
shop ends their sessions at once.
"""

from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import BigInteger, ColumnElement, any_, func, insert, literal, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from gulbot.models.shop import Shop
from gulbot.models.shop_panel import ShopAuditEntry, ShopLoginLink, ShopSession
from gulbot.services.admin_auth import (
    LINK_RATE_LIMIT,
    LINK_RATE_WINDOW,
    LINK_TTL,
    SESSION_TTL,
    TOKEN_RE,
    hash_token,
)

__all__ = [
    "LINK_RATE_LIMIT",
    "LINK_TTL",
    "SESSION_TTL",
    "TOKEN_RE",
    "ShopOwner",
    "audit",
    "consume_login_link",
    "csrf_ok",
    "end_session",
    "is_owner",
    "load_session",
    "mint_login_link",
]


def _owns(
    telegram_id: int | ColumnElement[int] | InstrumentedAttribute[int],
) -> ColumnElement[bool]:
    """`<id> = ANY (shops.owner_telegram_ids)`, for a value or a column."""
    value: Any = telegram_id if not isinstance(telegram_id, int) else literal(telegram_id)
    return value.cast(BigInteger) == any_(Shop.owner_telegram_ids)  # type: ignore[no-any-return]


async def is_owner(session: AsyncSession, *, shop_id: int, telegram_id: int) -> bool:
    found = await session.scalar(select(Shop.id).where(Shop.id == shop_id, _owns(telegram_id)))
    return found is not None


async def audit(
    session: AsyncSession,
    *,
    shop_id: int,
    action: str,
    owner: int | None,
    detail: dict[str, Any] | None = None,
    reason: str | None = None,
    ip: str | None = None,
) -> None:
    """Append one entry, in the caller's transaction."""
    await session.execute(
        insert(ShopAuditEntry).values(
            shop_id=shop_id,
            telegram_id=owner,
            action=action,
            detail=detail,
            reason=reason,
            ip=ip,
        )
    )


async def mint_login_link(
    session: AsyncSession, *, shop_id: int, telegram_id: int, now: datetime | None = None
) -> str | None:
    """A fresh one-time token for this owner of this shop, or None if they do
    not own it (or have asked too often). The raw token is returned once and
    never stored."""
    now = now or datetime.now(UTC)
    if not await is_owner(session, shop_id=shop_id, telegram_id=telegram_id):
        return None
    recent = await session.scalar(
        select(func.count())
        .select_from(ShopLoginLink)
        .where(
            ShopLoginLink.shop_id == shop_id,
            ShopLoginLink.telegram_id == telegram_id,
            ShopLoginLink.created_at > now - LINK_RATE_WINDOW,
        )
    )
    if int(recent or 0) >= LINK_RATE_LIMIT:
        await audit(
            session, shop_id=shop_id, action="login_link_refused", owner=telegram_id, reason="rate"
        )
        return None
    raw = secrets.token_urlsafe(32)
    await session.execute(
        insert(ShopLoginLink).values(
            shop_id=shop_id,
            token_hash=hash_token(raw),
            telegram_id=telegram_id,
            created_at=now,
            expires_at=now + LINK_TTL,
        )
    )
    await audit(session, shop_id=shop_id, action="login_link_sent", owner=telegram_id)
    return raw


@dataclass(frozen=True)
class NewSession:
    token: str  # the raw cookie value; only its hash is stored
    shop_id: int
    telegram_id: int
    csrf: str


async def consume_login_link(
    session: AsyncSession, raw: str, *, ip: str | None = None, now: datetime | None = None
) -> NewSession | None:
    """Spend the link -- once, by compare-and-swap -- and open a session for
    ITS shop. None for an unknown, spent or expired link, or one whose owner no
    longer owns the shop."""
    now = now or datetime.now(UTC)
    spent = (
        await session.execute(
            update(ShopLoginLink)
            .where(
                ShopLoginLink.token_hash == hash_token(raw),
                ShopLoginLink.used_at.is_(None),
                ShopLoginLink.expires_at > now,
            )
            .values(used_at=now)
            .returning(ShopLoginLink.shop_id, ShopLoginLink.telegram_id)
        )
    ).one_or_none()
    if spent is None:
        # Nothing names a shop here: an unknown, spent or expired token.
        return None
    shop_id, owner = int(spent[0]), int(spent[1])
    if not await is_owner(session, shop_id=shop_id, telegram_id=owner):
        await audit(
            session, shop_id=shop_id, action="login_refused", owner=owner, reason="not_owner", ip=ip
        )
        return None
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    await session.execute(
        insert(ShopSession).values(
            shop_id=shop_id,
            token_hash=hash_token(token),
            telegram_id=owner,
            csrf_token=csrf,
            created_at=now,
            expires_at=now + SESSION_TTL,
        )
    )
    await audit(session, shop_id=shop_id, action="login", owner=owner, ip=ip)
    return NewSession(token=token, shop_id=shop_id, telegram_id=owner, csrf=csrf)


@dataclass(frozen=True)
class ShopOwner:
    """Who is making this /shop request, and for which shop. The shop every
    screen shows is THIS one; nothing in a URL can name another."""

    shop_id: int
    telegram_id: int
    csrf: str
    session_id: int


async def load_session(
    session: AsyncSession, raw: str | None, *, now: datetime | None = None
) -> ShopOwner | None:
    """The owner behind this cookie, or None: unknown, expired, revoked, or no
    longer an owner of the session's shop. One statement."""
    if not raw:
        return None
    now = now or datetime.now(UTC)
    row = (
        await session.execute(
            select(
                ShopSession.id, ShopSession.shop_id, ShopSession.telegram_id, ShopSession.csrf_token
            )
            .join(Shop, Shop.id == ShopSession.shop_id)
            .where(
                ShopSession.token_hash == hash_token(raw),
                ShopSession.revoked_at.is_(None),
                ShopSession.expires_at > now,
                _owns(ShopSession.telegram_id),
            )
        )
    ).one_or_none()
    if row is None:
        return None
    return ShopOwner(
        shop_id=int(row.shop_id),
        telegram_id=int(row.telegram_id),
        csrf=str(row.csrf_token),
        session_id=int(row.id),
    )


def csrf_ok(owner: ShopOwner, submitted: str | None) -> bool:
    return submitted is not None and hmac.compare_digest(owner.csrf, submitted)


async def end_session(
    session: AsyncSession, owner: ShopOwner, *, ip: str | None = None, now: datetime | None = None
) -> None:
    await session.execute(
        update(ShopSession)
        .where(ShopSession.id == owner.session_id)
        .values(revoked_at=now or datetime.now(UTC))
    )
    await audit(session, shop_id=owner.shop_id, action="logout", owner=owner.telegram_id, ip=ip)
