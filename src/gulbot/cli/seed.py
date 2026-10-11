"""Idempotent dev seed: create a local shop, by name, if it is absent.

    python -m gulbot.cli.seed                                  # the dev shop
    python -m gulbot.cli.seed --name "Shop B" --channel-id -100123 \\
        --group-chat-id -100456 --owner-id 111 --owner-id 222 --lang ru

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
provisioning path for a real shop.

THE PILOT ON A FRESH SERVER (CP21, found by the staging rehearsal). The process
BOT_TOKEN serves only the shop the per-shop-tokens migration flagged -- and on
an empty database it flags none. `--store-bot-token` makes the process
BOT_TOKEN, read from the ENVIRONMENT the seed runs in, the shop's OWN token,
encrypted exactly as onboarding stores one:

    python -m gulbot.cli.seed --name "<pilot shop>" --owner-id <id> --store-bot-token
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.brand import brand_name
from gulbot.config import get_settings
from gulbot.db.session import build_session_factory, session_scope
from gulbot.models.shop import DEFAULT_WORKING_HOURS, Shop
from gulbot.services.shop_tokens import bot_id_of, is_token_shaped, set_shop_bot_token


def dev_shop_name() -> str:
    """The dev shop's default name: the product's, from its one place (CP19)."""
    return f"{brand_name()} Dev Shop"


class SeedConflict(RuntimeError):
    """A rerun asked for wiring that disagrees with what the shop has."""


async def ensure_shop(
    session: AsyncSession,
    *,
    name: str,
    channel_id: int | None = None,
    group_chat_id: int | None = None,
    owner_ids: Sequence[int] = (),
    lang: str | None = None,
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
        if lang is not None:
            shop.lang = lang
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
    if lang is not None and shop.lang != lang:
        # Never unset: a stored language always exists, so any other is a change.
        raise SeedConflict(
            f"shop {name!r} already has lang={shop.lang}, not {lang}; "
            "the seed never overwrites. Change it deliberately, in psql."
        )
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
    name: str | None = None,
    channel_id: int | None = None,
    group_chat_id: int | None = None,
    owner_ids: Sequence[int] = (),
    lang: str | None = None,
    database: str | None = None,
) -> tuple[int, bool]:
    """Return (shop_id, created), committed."""
    factory = build_session_factory(database)
    async with session_scope(factory) as session:
        return await ensure_shop(
            session,
            name=name or dev_shop_name(),
            channel_id=channel_id,
            group_chat_id=group_chat_id,
            owner_ids=owner_ids,
            lang=lang,
        )


async def store_process_bot_token(session: AsyncSession, *, shop_id: int, token: str) -> bool:
    """Make `token` the shop's own bot, encrypted. Does not commit.

    True when stored, False when the shop already holds this very bot. Never
    overwrites another bot, never takes a bot another shop holds, and never
    puts the token in a message: the refusals name bot ids, the public half.
    """
    if not is_token_shaped(token):
        raise SeedConflict(
            "BOT_TOKEN is not set to a bot token (the bot's id, a colon, its secret) in "
            "this environment; nothing was stored."
        )
    bot_id = bot_id_of(token)
    shop = await session.scalar(select(Shop).where(Shop.id == shop_id))
    if shop is None:
        raise SeedConflict(f"no shop with id={shop_id}; nothing was stored.")
    if shop.bot_token_encrypted is not None:
        if shop.bot_telegram_id == bot_id:
            return False
        raise SeedConflict(
            f"shop {shop.name!r} already has its own bot (id {shop.bot_telegram_id}), not "
            f"bot {bot_id}; the seed never overwrites. Change it deliberately."
        )
    holder = await session.scalar(
        select(Shop.id).where(Shop.bot_telegram_id == bot_id, Shop.id != shop_id)
    )
    if holder is not None:
        raise SeedConflict(
            f"bot {bot_id} already belongs to shop {holder}; one bot serves one shop."
        )
    await set_shop_bot_token(session, shop_id=shop_id, token=token)
    return True


def process_bot_token() -> str:
    """BOT_TOKEN as this process's settings hold it -- the environment, in production."""
    return get_settings().bot_token.get_secret_value()


async def seed_bot_token(*, shop_id: int, database: str | None = None) -> tuple[int, bool]:
    """Return (bot id, stored), committed."""
    token = process_bot_token()
    factory = build_session_factory(database)
    async with session_scope(factory) as session:
        stored = await store_process_bot_token(session, shop_id=shop_id, token=token)
    return bot_id_of(token), stored


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m gulbot.cli.seed",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--name", default=dev_shop_name(), help="the shop to create or find")
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
    parser.add_argument(
        "--lang",
        choices=("uz", "ru", "en"),
        default=None,
        help="what the shop's own people read (default: uz, for a new shop)",
    )
    parser.add_argument(
        "--store-bot-token",
        action="store_true",
        help="make the BOT_TOKEN in this environment the shop's own bot (never an argument)",
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
                lang=args.lang,
            )
        )
    except SeedConflict as conflict:
        raise SystemExit(f"NOT seeded: {conflict}") from None
    print(f"shop id={shop_id} {args.name!r} {'created' if created else 'already existed'}")
    if args.store_bot_token:
        try:
            bot_id, stored = asyncio.run(seed_bot_token(shop_id=shop_id))
        except SeedConflict as conflict:
            raise SystemExit(f"NO bot token stored: {conflict}") from None
        print(f"its own bot: id={bot_id} {'stored, encrypted' if stored else 'already stored'}")


if __name__ == "__main__":
    main()
