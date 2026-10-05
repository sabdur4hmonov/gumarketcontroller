"""Idempotent dev seed: create a local shop, by name, if it is absent.

    python -m gulbot.cli.seed                                  # the dev shop
    python -m gulbot.cli.seed --name "Shop B" --channel-id -100123 \\
        --group-chat-id -100456 --owner-id 111 --owner-id 222

Safe to run repeatedly -- it never overwrites an existing shop's configuration,
because doing so would silently reset working hours someone tuned by hand. A
rerun FILLS wiring that is still unset, and REFUSES a value that disagrees with
what is stored (`SeedConflict`): changing a shop's channel or group is a
deliberate act, not a side effect of seeding.

MORE THAN ONE SHOP (L3 of AUDIT_MULTI_TENANT.md). `--name` picks the shop; the
dev name stays the default. Since H3 a shop indexes only its own `channel_id`,
so a seeded shop is wired here rather than in psql.

NOT A TOKEN. A shop's bot token is not a seed argument: a token on a command
line ends up in shell history. The platform bot's onboarding is the
provisioning path for a real shop; the dev shop speaks through BOT_TOKEN.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.db.session import build_session_factory, session_scope
from gulbot.models.shop import DEFAULT_WORKING_HOURS, Shop

DEV_SHOP_NAME = "Gulbot Dev Shop"


class SeedConflict(RuntimeError):
    """A rerun asked for wiring that disagrees with what the shop has."""


async def ensure_shop(
    session: AsyncSession,
    *,
    name: str,
    channel_id: int | None = None,
    group_chat_id: int | None = None,
    owner_ids: Sequence[int] = (),
) -> tuple[int, bool]:
    """Return (shop_id, created). Does not commit.

    Creates the shop with the wiring given, or fills what an existing one has
    unset. Never overwrites: a stored value that differs raises SeedConflict
    before anything is changed.
    """
    shop = await session.scalar(select(Shop).where(Shop.name == name).order_by(Shop.id))
    if shop is None:
        shop = Shop(
            name=name,
            working_hours=DEFAULT_WORKING_HOURS,
            channel_id=channel_id,
            group_chat_id=group_chat_id,
            owner_telegram_ids=list(owner_ids),
        )
        session.add(shop)
        await session.flush()
        return int(shop.id), True

    wanted: dict[str, object] = {}
    for field, value in (("channel_id", channel_id), ("group_chat_id", group_chat_id)):
        if value is None:
            continue
        current = getattr(shop, field)
        if current is not None and current != value:
            raise SeedConflict(
                f"shop {name!r} already has {field}={current}, not {value}; "
                "the seed never overwrites. Change it deliberately, in psql."
            )
        wanted[field] = value
    if owner_ids:
        current_owners = list(shop.owner_telegram_ids or [])
        if current_owners and sorted(current_owners) != sorted(owner_ids):
            raise SeedConflict(
                f"shop {name!r} already has owners {current_owners}; "
                "the seed never overwrites. Change them deliberately, in psql."
            )
        wanted["owner_telegram_ids"] = list(owner_ids)

    for field, filled in wanted.items():
        setattr(shop, field, filled)
    await session.flush()
    return int(shop.id), False


async def seed_dev_shop(
    *,
    name: str = DEV_SHOP_NAME,
    channel_id: int | None = None,
    group_chat_id: int | None = None,
    owner_ids: Sequence[int] = (),
    database: str | None = None,
) -> tuple[int, bool]:
    """Return (shop_id, created), committed."""
    factory = build_session_factory(database)
    async with session_scope(factory) as session:
        return await ensure_shop(
            session,
            name=name,
            channel_id=channel_id,
            group_chat_id=group_chat_id,
            owner_ids=owner_ids,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m gulbot.cli.seed",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--name", default=DEV_SHOP_NAME, help="the shop to create or find")
    parser.add_argument("--channel-id", type=int, default=None, help="its catalogue channel")
    parser.add_argument("--group-chat-id", type=int, default=None, help="its admin group")
    parser.add_argument(
        "--owner-id",
        dest="owner_ids",
        type=int,
        action="append",
        default=[],
        help="an owner's Telegram id; repeat for several",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        shop_id, created = asyncio.run(
            seed_dev_shop(
                name=args.name,
                channel_id=args.channel_id,
                group_chat_id=args.group_chat_id,
                owner_ids=args.owner_ids,
            )
        )
    except SeedConflict as conflict:
        raise SystemExit(f"NOT seeded: {conflict}") from None
    print(f"shop id={shop_id} {args.name!r} {'created' if created else 'already existed'}")


if __name__ == "__main__":
    main()
