"""Live evidence for CP18, against the dev database and the local page server.

1. A bot-health snapshot of every shop, through each shop's REAL bot
   (getMe, getChat, getChatMember -- read-only; nothing is posted).
2. "/admin" sent to the REAL platform dispatcher by an admin id, and the
   one-time login link it answers with, written to --link-file.

THE ONE SYNTHETIC PART: there is no platform bot token on this machine yet
(PLATFORM_BOT_TOKEN, from BotFather -- an owner's step). So the platform
dispatcher's Bot uses a recording session: the update is real aiogram, the
handler and the database are real, and the reply that Telegram would deliver
is captured instead. With PLATFORM_BOT_TOKEN set, the same handler sends the
same message to the admin's DM.

    PLATFORM_ADMIN_TELEGRAM_IDS=<id> python scripts/live_cp18.py --admin-id <id> \\
        --link-file <path>

The link is a secret for 10 minutes: it is written to the file, never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from aiogram import Bot  # noqa: E402
from aiogram.methods import SendMessage  # noqa: E402
from aiogram.types import User  # noqa: E402
from tests.bot_harness import RecordingSession, feed, text_update  # noqa: E402

from gulbot.bot.factory import build_platform_dispatcher  # noqa: E402
from gulbot.bot.registry import registry_for  # noqa: E402
from gulbot.config import get_settings  # noqa: E402
from gulbot.db.session import build_session_factory  # noqa: E402
from gulbot.services import admin_auth  # noqa: E402
from gulbot.services.shop_health import snapshot_all_shops  # noqa: E402


async def main(admin_id: int, link_file: Path) -> None:
    settings = get_settings()
    if admin_id not in admin_auth.admin_ids(settings):
        raise SystemExit("set PLATFORM_ADMIN_TELEGRAM_IDS to include --admin-id for this run")
    factory = build_session_factory(settings.postgres_db)

    print("1. bot-health snapshot, through every shop's own bot (read-only)")
    async with factory() as session:
        registry = await registry_for(session)
        try:
            for snap in await snapshot_all_shops(session, registry.bot_for):
                print(
                    f"   shop {snap.shop_id}: token_valid={snap.token_valid} "
                    f"bot=@{snap.bot_username} channel_ok={snap.channel_ok} "
                    f"group_ok={snap.group_ok} {snap.detail or ''}"
                )
            await session.commit()
        finally:
            await registry.close()

    print("2. /admin to the platform dispatcher, from the admin's id")
    recorder = RecordingSession()
    bot = Bot(token="555000111:" + "P" * 35, session=recorder)
    bot._me = User(id=555_000_111, is_bot=True, first_name="platform", username="platform_bot")  # noqa: SLF001
    dispatcher = build_platform_dispatcher(session_factory=factory)
    await feed(dispatcher, bot, text_update("/admin", user_id=admin_id, update_id=1))
    replies = [c for c in recorder.calls if isinstance(c, SendMessage)]
    for reply in replies:
        shown = re.sub(r"/admin/login/[A-Za-z0-9_-]+", "/admin/login/<secret>", reply.text)
        preview = (
            "off" if reply.link_preview_options and reply.link_preview_options.is_disabled else "ON"
        )
        print(f"   bot -> {shown!r} (link preview {preview})")
    found = re.search(
        r"https?://\S+/admin/login/[A-Za-z0-9_-]+", replies[-1].text if replies else ""
    )
    if not found:
        raise SystemExit("no login link was sent")
    link_file.write_text(found.group(0), encoding="utf-8")
    print(f"   link written to {link_file} (valid {admin_auth.LINK_TTL}, one use)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--admin-id", type=int, required=True)
    parser.add_argument("--link-file", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.admin_id, args.link_file))
