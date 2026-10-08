"""Getting into the platform admin panel, and the record of what happens there (CP18).

THE ONLY WAY IN is a link the PLATFORM bot sends to a Telegram account listed in
PLATFORM_ADMIN_TELEGRAM_IDS. There is no password to guess, phish or reuse: being
an admin means controlling that Telegram account.

    /admin in the platform bot  ->  mint_login_link   (10 minutes, one use)
    open the link, press Kirish ->  consume_login_link -> a session (1 hour)
    every panel request          ->  load_session       (and its CSRF token)

The admin list is checked TWICE -- when the link is minted and again when it is
spent -- so an id removed from the list in between cannot finish logging in, and
on every request, so removing an id ends its sessions at once.

Every login, refusal and logout is written to the audit log.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.config import Settings, get_settings, parse_admin_ids
from gulbot.models.admin import AdminAuditEntry, AdminLoginLink, AdminSession

#: A raw link or session token, as `secrets.token_urlsafe(32)` makes it.
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{40,64}$")
#: How long a login link stays usable.
LINK_TTL = timedelta(minutes=10)
#: How long a session lasts, from login. Absolute, not sliding: short on purpose.
SESSION_TTL = timedelta(hours=1)
#: At most this many links per admin in LINK_RATE_WINDOW -- a stolen phone
#: session cannot mint an unbounded stream of them.
LINK_RATE_LIMIT = 5
LINK_RATE_WINDOW = timedelta(minutes=10)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def admin_ids(settings: Settings | None = None) -> frozenset[int]:
    """PLATFORM_ADMIN_TELEGRAM_IDS as a set (gulbot.config.parse_admin_ids)."""
    raw = (settings or get_settings()).platform_admin_telegram_ids
    return parse_admin_ids(raw)


async def audit(
    session: AsyncSession,
    *,
    action: str,
    admin: int | None,
    shop_id: int | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
    ip: str | None = None,
) -> None:
    """Append one entry. In the caller's transaction, so an action and its
    record commit -- or roll back -- together."""
    await session.execute(
        insert(AdminAuditEntry).values(
            admin_telegram_id=admin,
            action=action,
            shop_id=shop_id,
            target_type=target_type,
            target_id=target_id,
            before=before,
            after=after,
            reason=reason,
            ip=ip,
        )
    )


async def mint_login_link(
    session: AsyncSession,
    *,
    telegram_id: int,
    allowed: Iterable[int],
    now: datetime | None = None,
) -> str | None:
    """A fresh one-time token for this admin, or None if they are not one (or
    have asked too often). The raw token is returned once and never stored."""
    now = now or datetime.now(UTC)
    if telegram_id not in set(allowed):
        return None
    recent = await session.scalar(
        select(func.count())
        .select_from(AdminLoginLink)
        .where(
            AdminLoginLink.telegram_id == telegram_id,
            AdminLoginLink.created_at > now - LINK_RATE_WINDOW,
        )
    )
    if int(recent or 0) >= LINK_RATE_LIMIT:
        await audit(session, action="login_link_refused", admin=telegram_id, reason="rate")
        return None
    raw = secrets.token_urlsafe(32)
    await session.execute(
        insert(AdminLoginLink).values(
            token_hash=hash_token(raw),
            telegram_id=telegram_id,
            created_at=now,
            expires_at=now + LINK_TTL,
        )
    )
    await audit(session, action="login_link_sent", admin=telegram_id)
    return raw


@dataclass(frozen=True)
class NewSession:
    token: str  # the raw cookie value; only its hash is stored
    telegram_id: int
    csrf: str
    expires_at: datetime


async def consume_login_link(
    session: AsyncSession,
    raw: str,
    *,
    allowed: Iterable[int],
    ip: str | None = None,
    now: datetime | None = None,
) -> NewSession | None:
    """Spend the link -- once, by compare-and-swap -- and open a session.

    None for an unknown, spent or expired link, or one whose owner is no longer
    on the admin list. Each refusal is audited; nothing says which it was."""
    now = now or datetime.now(UTC)
    spent_by = await session.scalar(
        update(AdminLoginLink)
        .where(
            AdminLoginLink.token_hash == hash_token(raw),
            AdminLoginLink.used_at.is_(None),
            AdminLoginLink.expires_at > now,
        )
        .values(used_at=now)
        .returning(AdminLoginLink.telegram_id)
    )
    if spent_by is None:
        await audit(session, action="login_refused", admin=None, reason="link", ip=ip)
        return None
    if spent_by not in set(allowed):
        await audit(session, action="login_refused", admin=spent_by, reason="not_admin", ip=ip)
        return None
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    expires = now + SESSION_TTL
    await session.execute(
        insert(AdminSession).values(
            token_hash=hash_token(token),
            telegram_id=spent_by,
            csrf_token=csrf,
            created_at=now,
            expires_at=expires,
        )
    )
    await audit(session, action="login", admin=spent_by, ip=ip)
    return NewSession(token=token, telegram_id=spent_by, csrf=csrf, expires_at=expires)


@dataclass(frozen=True)
class Admin:
    """Who is making this panel request."""

    telegram_id: int
    csrf: str
    session_id: int


async def load_session(
    session: AsyncSession,
    raw: str | None,
    *,
    allowed: Iterable[int],
    now: datetime | None = None,
) -> Admin | None:
    """The admin behind this cookie, or None: unknown, expired, revoked, or no
    longer on the admin list."""
    if not raw:
        return None
    now = now or datetime.now(UTC)
    row = (
        await session.execute(
            select(AdminSession.id, AdminSession.telegram_id, AdminSession.csrf_token).where(
                AdminSession.token_hash == hash_token(raw),
                AdminSession.revoked_at.is_(None),
                AdminSession.expires_at > now,
            )
        )
    ).one_or_none()
    if row is None or row[1] not in set(allowed):
        return None
    return Admin(telegram_id=int(row[1]), csrf=str(row[2]), session_id=int(row[0]))


def csrf_ok(admin: Admin, submitted: str | None) -> bool:
    return submitted is not None and hmac.compare_digest(admin.csrf, submitted)


async def end_session(
    session: AsyncSession, admin: Admin, *, ip: str | None = None, now: datetime | None = None
) -> None:
    await session.execute(
        update(AdminSession)
        .where(AdminSession.id == admin.session_id)
        .values(revoked_at=now or datetime.now(UTC))
    )
    await audit(session, action="logout", admin=admin.telegram_id, ip=ip)
