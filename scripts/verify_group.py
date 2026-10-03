"""Prove the bot can actually POST to the shop's group, then wire it up.

Presence is not permission. The channel taught us that at CP8: the bot was a
member for hours while every post made before it was promoted produced no update
at all, and nothing in the database moved. The same trap applies to a group --
"added the bot" and "the bot can send messages there" are different facts, and
only the second one matters.

So this does not ask Telegram what rights the bot has; it SENDS something and
reports what came back.

    python scripts/verify_group.py --shop-id 1                  # discover, verify, wire
    python scripts/verify_group.py --shop-id 1 --chat-id -100…  # skip discovery
    python scripts/verify_group.py --shop-id 1 --dry-run        # verify only, write nothing

`--shop-id` IS REQUIRED, and a run without it stops before Telegram or the
database is touched. C4 of AUDIT_MULTI_TENANT.md: this script used to run its
UPDATE with no WHERE clause, which against a database of many shops would
point EVERY shop's order cards at this one group, with no record of where they
went before. An id that matches no shop is an error, not a zero-row update.

DISCOVERY. Telegram gives bots no way to list their chats, so the id has to
arrive in an update. Send any message in the group (or re-add the bot) and it
will be in the queue -- provided no `bot.run` is polling, because a poller
consumes the queue and this will then find it empty.

The token is read through Settings and never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import psycopg  # noqa: E402

from gulbot.bot.chat_checks import check_group  # noqa: E402
from gulbot.bot.registry import BotRegistry, registry_for  # noqa: E402
from gulbot.config import get_settings  # noqa: E402
from gulbot.db.session import task_session_factory  # noqa: E402
from gulbot.i18n import t  # noqa: E402
from gulbot.sending.transport import ShopBotUnavailable  # noqa: E402

GROUP_TYPES = ("group", "supergroup")


async def discover(bot) -> list[tuple[int, str, str]]:  # type: ignore[no-untyped-def]
    """Every group the update queue mentions: (chat_id, type, title)."""
    found: dict[int, tuple[int, str, str]] = {}
    for update in await bot.get_updates(timeout=0, limit=100):
        event = (
            update.message or update.my_chat_member or update.edited_message or update.channel_post
        )
        if event is None:
            continue
        chat = event.chat
        if chat.type in GROUP_TYPES:
            found[chat.id] = (chat.id, chat.type, chat.title or "")
    return list(found.values())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--shop-id",
        type=int,
        required=True,
        help="the ONE shop to wire to this group (shops.id)",
    )
    parser.add_argument("--chat-id", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def wire_group(conn: psycopg.Connection, *, shop_id: int, chat_id: int) -> str:
    """Point exactly one shop at `chat_id`. Returns that shop's name.

    Raises LookupError, having written nothing, if no shop has that id.
    """
    row = conn.execute(
        "UPDATE shops SET group_chat_id = %s WHERE id = %s RETURNING name",
        (chat_id, shop_id),
    ).fetchone()
    if row is None:
        raise LookupError(f"no shop with id={shop_id}; group_chat_id was not written")
    return str(row[0])


async def shop_bots(shop_id: int) -> BotRegistry:
    """A registry holding THIS shop's bot: its stored token, or the logged
    legacy fallback. Proving that some other bot can post in the group would
    prove nothing about the bot that will actually send the order cards."""
    async with task_session_factory() as factory, factory() as session:
        return await registry_for(session, shop_ids=[shop_id])


async def main() -> int:
    # Parsed FIRST: a missing --shop-id exits here, before any network or
    # database access.
    args = build_parser().parse_args()

    settings = get_settings()
    registry = await shop_bots(args.shop_id)
    try:
        try:
            bot = registry.bot_for(args.shop_id)
        except ShopBotUnavailable as missing:
            print(f"NOT VERIFIED: {missing}")
            return 3
        me = await bot.get_me()
        print(f"bot: @{me.username} (id={me.id})")

        chat_id = args.chat_id
        if chat_id is None:
            groups = await discover(bot)
            if not groups:
                print(
                    "\nNo group found in the update queue.\n"
                    "  * send any message in the group, then run this again; and\n"
                    "  * make sure no `bot.run` is polling -- it eats the queue."
                )
                return 2
            for found_id, kind, title in groups:
                print(f"  found {kind}: chat_id={found_id} title={title!r}")
            if len(groups) > 1:
                print("\nMore than one group. Re-run with --chat-id to choose.")
                return 2
            chat_id = groups[0][0]

        # THE check, shared with shop-owner onboarding (gulbot/bot/chat_checks.py)
        # so there is one definition of "this bot can work in this group": an
        # administrator, AND a real post -- a permissions read can succeed
        # while a send fails, and the send is what the ping tick does.
        result = await check_group(bot, chat_id, test_text=t("owner.group_test_message"))
        if not result.ok:
            print(f"\nNOT VERIFIED: chat_id={chat_id}: {result.problem}")
            return 3
        print(f"\ntarget: {result.title!r} (chat_id={chat_id})")
        print("POSTED OK: the bot is an administrator and can post there")

        if args.dry_run:
            print("--dry-run: shops.group_chat_id not written")
            return 0

        dsn = (
            f"host={settings.postgres_host} port={settings.postgres_port} "
            f"user={settings.postgres_user} "
            f"password={settings.postgres_password.get_secret_value()} "
            f"dbname={settings.postgres_db}"
        )
        try:
            with psycopg.connect(dsn, autocommit=True) as conn:
                name = wire_group(conn, shop_id=args.shop_id, chat_id=chat_id)
        except LookupError as missing:
            print(f"\nNOT WIRED: {missing}")
            return 3
        print(f"wired shop {args.shop_id} ({name}) -> group_chat_id={chat_id}")
        return 0
    finally:
        await registry.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
