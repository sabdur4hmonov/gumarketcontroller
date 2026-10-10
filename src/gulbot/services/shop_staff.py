"""Who may confirm and reject a shop's orders (CP19).

Before CP19 the order card's permission was by CHAT: anyone in the shop's group
could decide any order (docs/AUDIT.md section 3, A). Now:

* A shop with NO staff list keeps exactly that rule. That is the default for
  every existing shop, so nothing changes for anyone until an owner acts; the
  admin panel's shop screen warns while the list is empty.
* Once the list has one person, only the people on it -- and the shop's
  owners, always -- may confirm, reject, withdraw a rejection or finish one.
  Everyone else in the group is refused, by an alert only they see.

The chat check in bot/routers/admin_orders.py still applies first: the list
narrows WHO, inside the chats the card was sent to; it never widens WHERE.

Owners manage the list from the platform bot (bot/routers/shop_staff.py). Every
write takes the acting owner's id and checks it against THAT shop, so a crafted
callback naming another shop finds nothing to change.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import BigInteger, ColumnElement, any_, delete, func, literal, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.models.shop import Shop
from gulbot.models.staff import STAFF_LABEL_MAX, ShopStaff

log = logging.getLogger("gulbot.services.shop_staff")

#: A list is for a shop's handful of people, not a second group.
MAX_STAFF = 20

#: Telegram user ids are positive and fit in 52 bits (Bot API docs).
MAX_TELEGRAM_ID = 2**52


class StaffRefused(Exception):
    """A list change that was not made. `reason` is a catalog key suffix."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class StaffMember:
    telegram_id: int
    label: str | None


@dataclass(frozen=True)
class OwnedShop:
    shop_id: int
    name: str


_MAY_DECIDE = text(
    """
    SELECT NOT EXISTS (SELECT 1 FROM shop_staff WHERE shop_id = :shop)
        OR EXISTS (SELECT 1 FROM shop_staff WHERE shop_id = :shop AND telegram_id = :user)
        OR CAST(:user AS bigint) = ANY (owner_telegram_ids)
    FROM shops
    WHERE id = :shop
    """
)


async def may_decide(session: AsyncSession, *, shop_id: int, telegram_id: int) -> bool:
    """May this person act on this shop's order cards?

    One statement, so the list cannot change between "is there a list" and
    "is this person on it". No shop row means no: nothing to decide for.
    """
    allowed = await session.scalar(_MAY_DECIDE, {"shop": shop_id, "user": telegram_id})
    return bool(allowed)


async def staff_of(session: AsyncSession, *, shop_id: int) -> list[StaffMember]:
    rows = await session.execute(
        select(ShopStaff.telegram_id, ShopStaff.label)
        .where(ShopStaff.shop_id == shop_id)
        .order_by(ShopStaff.added_at, ShopStaff.telegram_id)
    )
    return [StaffMember(int(row.telegram_id), row.label) for row in rows]


def _owned_by(telegram_id: int) -> ColumnElement[bool]:
    """`:id = ANY (shops.owner_telegram_ids)`."""
    return literal(telegram_id, BigInteger) == any_(Shop.owner_telegram_ids)


async def staff_count(session: AsyncSession, *, shop_id: int) -> int:
    found = await session.scalar(
        select(func.count()).select_from(ShopStaff).where(ShopStaff.shop_id == shop_id)
    )
    return int(found or 0)


async def owned_shops(session: AsyncSession, *, telegram_id: int) -> list[OwnedShop]:
    rows = await session.execute(
        select(Shop.id, Shop.name).where(_owned_by(telegram_id)).order_by(Shop.id)
    )
    return [OwnedShop(int(row.id), str(row.name)) for row in rows]


async def owned_shop(session: AsyncSession, *, shop_id: int, telegram_id: int) -> OwnedShop | None:
    """The shop, if this person owns it; None for anyone else's shop."""
    found = (
        await session.execute(
            select(Shop.id, Shop.name).where(
                Shop.id == shop_id,
                _owned_by(telegram_id),
            )
        )
    ).first()
    return None if found is None else OwnedShop(int(found.id), str(found.name))


async def is_owner(session: AsyncSession, *, shop_id: int, telegram_id: int) -> bool:
    return await owned_shop(session, shop_id=shop_id, telegram_id=telegram_id) is not None


def clean_label(raw: str | None) -> str | None:
    label = " ".join((raw or "").split())[:STAFF_LABEL_MAX]
    return label or None


async def add_staff(
    session: AsyncSession,
    *,
    shop_id: int,
    owner_id: int,
    telegram_id: int,
    label: str | None,
) -> bool:
    """Put a person on the list. True when they were not on it already.

    Refuses (StaffRefused) a caller who does not own this shop, an id that is
    not a person, an owner (owners always decide), and a full list.
    """
    if not await is_owner(session, shop_id=shop_id, telegram_id=owner_id):
        raise StaffRefused("not_owner")
    if not 0 < telegram_id < MAX_TELEGRAM_ID:
        raise StaffRefused("bad_id")
    if await is_owner(session, shop_id=shop_id, telegram_id=telegram_id):
        raise StaffRefused("is_owner")
    # Serialise adds per shop, so two at once cannot both pass the cap.
    await session.execute(select(Shop.id).where(Shop.id == shop_id).with_for_update())
    present = await session.scalar(
        select(ShopStaff.telegram_id).where(
            ShopStaff.shop_id == shop_id, ShopStaff.telegram_id == telegram_id
        )
    )
    if present is None and await staff_count(session, shop_id=shop_id) >= MAX_STAFF:
        raise StaffRefused("full")
    statement = (
        insert(ShopStaff)
        .values(
            shop_id=shop_id,
            telegram_id=telegram_id,
            label=clean_label(label),
            added_by=owner_id,
        )
        .on_conflict_do_update(
            index_elements=[ShopStaff.shop_id, ShopStaff.telegram_id],
            set_={"label": clean_label(label)},
        )
    )
    await session.execute(statement)
    log.info("shop %s: owner %s put %s on the staff list", shop_id, owner_id, telegram_id)
    return present is None


async def remove_staff(
    session: AsyncSession, *, shop_id: int, owner_id: int, telegram_id: int
) -> bool:
    """Take a person off the list. True when they were on it."""
    if not await is_owner(session, shop_id=shop_id, telegram_id=owner_id):
        raise StaffRefused("not_owner")
    removed = await session.execute(
        delete(ShopStaff)
        .where(ShopStaff.shop_id == shop_id, ShopStaff.telegram_id == telegram_id)
        .returning(ShopStaff.telegram_id)
    )
    gone = removed.first() is not None
    if gone:
        log.info("shop %s: owner %s took %s off the staff list", shop_id, owner_id, telegram_id)
    return gone
