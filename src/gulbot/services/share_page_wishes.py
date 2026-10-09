"""The guest wishes wall of a taklifnoma (CP17).

Guests leave a name and a short wish on the page; the creator can hide any
of them from the bot. It is PUBLIC INPUT, so every rule of the RSVP applies:

* only on a live invitation whose creator switched the wall on;
* name and wish cleaned (clean_text: controls, bidi overrides, zero-width
  and the like removed) and capped -- WISH_NAME_MAX / WISH_TEXT_MAX;
* bounded: WISHES_PER_PAGE in all, WISHES_PER_GUEST per browser (the RSVP
  cookie), on top of the web app's per-address rate limit;
* rendered escaped (Jinja autoescape), never as HTML.

The creator's side is scoped like every other edit: shop + customer + the
wish's page, joined -- a wish id alone opens nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.models.share_page import (
    WISH_NAME_MAX,
    WISH_TEXT_MAX,
    PageKind,
    SharePage,
    SharePageWish,
)
from gulbot.services.share_pages import clean_text

WISHES_PER_PAGE: Final = 300
WISHES_PER_GUEST: Final = 3
#: The page shows the newest this many visible wishes.
WISHES_SHOWN: Final = 60


class WishRefused(Exception):
    """`reason`: "page" (no live invitation with the wall on at this token),
    "invalid" (an empty or non-text name or wish), "full" (the page's or the
    guest's limit)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ShownWish:
    author: str
    body: str


async def leave_wish(
    session: AsyncSession,
    token: str,
    *,
    voter_key: str,
    author: object,
    body: object,
    now: datetime | None = None,
) -> ShownWish:
    now = now or datetime.now(UTC)
    if not isinstance(author, str) or not isinstance(body, str):
        raise WishRefused("invalid")
    name = clean_text(author, WISH_NAME_MAX)
    text = clean_text(body, WISH_TEXT_MAX, multiline=True)
    if not name or not text:
        raise WishRefused("invalid")
    page = await session.scalar(
        select(SharePage)
        .where(
            SharePage.token == token,
            SharePage.kind == PageKind.INVITE.value,
            SharePage.wishes_enabled.is_(True),
            SharePage.deleted_at.is_(None),
            SharePage.hidden_at.is_(None),  # CP18: hidden by moderation
            SharePage.expires_at > now,
        )
        .with_for_update()
    )
    if page is None:
        raise WishRefused("page")
    on_page, by_guest = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(SharePageWish.voter_key == voter_key),
            ).where(SharePageWish.page_id == page.id)
        )
    ).one()
    if on_page >= WISHES_PER_PAGE or by_guest >= WISHES_PER_GUEST:
        raise WishRefused("full")
    session.add(
        SharePageWish(
            shop_id=page.shop_id,
            page_id=page.id,
            voter_key=voter_key,
            author=name,
            body=text,
            created_at=now,
        )
    )
    await session.flush()
    return ShownWish(author=name, body=text)


async def visible_wishes(session: AsyncSession, *, page_id: int) -> list[ShownWish]:
    """What the page shows: not hidden, newest first, at most WISHES_SHOWN."""
    rows = await session.execute(
        select(SharePageWish.author, SharePageWish.body)
        .where(
            SharePageWish.page_id == page_id,
            SharePageWish.hidden.is_(False),
            # CP18: hidden by moderation, which the creator cannot undo.
            SharePageWish.admin_hidden_at.is_(None),
        )
        .order_by(SharePageWish.created_at.desc(), SharePageWish.id.desc())
        .limit(WISHES_SHOWN)
    )
    return [ShownWish(author=str(r[0]), body=str(r[1])) for r in rows]


@dataclass(frozen=True)
class OwnWish:
    id: int
    author: str
    body: str
    hidden: bool


def _own_page(shop_id: int, customer_id: int, page_id: int) -> Select[int]:
    return select(SharePage.id).where(
        SharePage.id == page_id,
        SharePage.shop_id == shop_id,
        SharePage.customer_id == customer_id,
        SharePage.deleted_at.is_(None),
    )


async def wishes_for_creator(
    session: AsyncSession, *, shop_id: int, customer_id: int, page_id: int, limit: int = 20
) -> list[OwnWish] | None:
    """The newest wishes of THIS customer's own page, hidden ones included.
    None if the page is not theirs."""
    if await session.scalar(_own_page(shop_id, customer_id, page_id)) is None:
        return None
    rows = await session.execute(
        select(SharePageWish.id, SharePageWish.author, SharePageWish.body, SharePageWish.hidden)
        .where(SharePageWish.page_id == page_id, SharePageWish.shop_id == shop_id)
        .order_by(SharePageWish.created_at.desc(), SharePageWish.id.desc())
        .limit(limit)
    )
    return [OwnWish(int(r[0]), str(r[1]), str(r[2]), bool(r[3])) for r in rows]


async def set_hidden(
    session: AsyncSession,
    *,
    shop_id: int,
    customer_id: int,
    page_id: int,
    wish_id: int,
    hidden: bool,
) -> bool:
    """Hide or show one wish of THIS customer's own page. False if the wish is
    not on a page of theirs."""
    result = await session.execute(
        update(SharePageWish)
        .where(
            SharePageWish.id == wish_id,
            SharePageWish.page_id == page_id,
            SharePageWish.shop_id == shop_id,
            SharePageWish.page_id.in_(_own_page(shop_id, customer_id, page_id)),
        )
        .values(hidden=hidden)
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]
