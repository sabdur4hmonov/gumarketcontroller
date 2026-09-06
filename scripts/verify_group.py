"""Prove the bot can actually POST to the shop's group, then wire it up.

Presence is not permission. The channel taught us that at CP8: the bot was a
member for hours while every post made before it was promoted produced no update
at all, and nothing in the database moved. The same trap applies to a group --
"added the bot" and "the bot can send messages there" are different facts, and
only the second one matters.

So this does not ask Telegram what rights the bot has; it SENDS something and
reports what came back.

    python scripts/verify_group.py                 # discover, verify, and wire
    python scripts/verify_group.py --chat-id -100…  # skip discovery
    python scripts/verify_group.py --dry-run       # verify only, write nothing

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

from gulbot.bot.factory import build_bot  # noqa: E402
from gulbot.config import get_settings  # noqa: E402

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


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chat-id", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    bot = build_bot()
    try:
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

        chat = await bot.get_chat(chat_id)
        print(f"\ntarget: {chat.title!r} (chat_id={chat_id}, type={chat.type})")

        # THE actual test. Not get_chat_member -- a permissions read can succeed
        # while a send fails, and the send is what the ping tick does.
        sent = await bot.send_message(
            chat_id, "Gulbot: yetkazib berish xabarnomalari shu yerga keladi. ✅"
        )
        print(f"POSTED OK: message_id={sent.message_id}")

        if args.dry_run:
            print("--dry-run: shops.group_chat_id not written")
            return 0

        dsn = (
            f"host={settings.postgres_host} port={settings.postgres_port} "
            f"user={settings.postgres_user} password={settings.postgres_password} "
            f"dbname={settings.postgres_db}"
        )
        with psycopg.connect(dsn, autocommit=True) as conn:
            rows = conn.execute(
                "UPDATE shops SET group_chat_id = %s RETURNING id, name", (chat_id,)
            ).fetchall()
        for shop_id, name in rows:
            print(f"wired shop {shop_id} ({name}) -> group_chat_id={chat_id}")
        return 0
    finally:
        await bot.session.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
