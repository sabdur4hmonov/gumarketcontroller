"""CP11's live end-to-end: browse the real catalogue, in the real bot.

Drives the REAL dispatcher with a REAL Bot against real Telegram and the dev
database, so the list, the paging and the verbatim product view all arrive in
the customer's own chat.

Same one synthetic part as `live_order.py`: the taps. A CallbackQuery needs an
id Telegram issued, so the Update objects are built here and
`CallbackQuery.answer` is stubbed. Everything downstream is production code.

    python scripts/live_browse.py            # list, page, and view one bouquet
    python scripts/live_browse.py --product 22

The token is read through Settings and never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

import psycopg  # noqa: E402
from aiogram.fsm.storage.memory import MemoryStorage  # noqa: E402
from aiogram.types import CallbackQuery  # noqa: E402
from tests.bot_harness import callback_update, text_update  # noqa: E402

from gulbot.bot.callbacks import BrowsePageCB, BrowsePickCB  # noqa: E402
from gulbot.bot.factory import build_bot, build_dispatcher  # noqa: E402
from gulbot.config import get_settings  # noqa: E402
from gulbot.db.session import build_session_factory  # noqa: E402
from gulbot.i18n.catalog import CATALOG  # noqa: E402
from gulbot.services.bouquets import list_bouquets  # noqa: E402


def show(title: str) -> None:
    print(f"\n{'-' * 68}\n{title}\n{'-' * 68}")


async def main(product_id: int | None) -> None:
    settings = get_settings()
    dsn = (
        f"host={settings.postgres_host} port={settings.postgres_port} "
        f"user={settings.postgres_user} password={settings.postgres_password} "
        f"dbname={settings.postgres_db}"
    )
    with psycopg.connect(dsn, autocommit=True) as conn:
        user = conn.execute(
            "SELECT telegram_user_id FROM customers WHERE shop_id = 1 ORDER BY id LIMIT 1"
        ).fetchone()[0]

    factory = build_session_factory(settings.postgres_db)
    async with factory() as session:
        listing = await list_bouquets(session, shop_id=1)
        print(f"catalogue page 1: {len(listing.bouquets)} bouquet(s), more={listing.has_more}")
        for b in listing.bouquets:
            print(f"   id={b.product_id:3} {b.name[:46]!r} price={b.price_uzs}")

    bot = build_bot()
    me = await bot.get_me()
    print(f"\nbot      : @{me.username}")
    print(f"customer : {user}")

    dispatcher = build_dispatcher(session_factory=factory, shop_id=1, storage=MemoryStorage())

    async def no_op_answer(self: CallbackQuery, *args: Any, **kwargs: Any) -> bool:
        return True

    CallbackQuery.answer = no_op_answer  # type: ignore[method-assign]

    counter = {"n": 0}

    async def feed(update: Any) -> None:
        counter["n"] += 1
        await dispatcher.feed_update(bot, update)

    try:
        show("1. the customer taps the new menu button")
        label = CATALOG["btn.menu.browse"]["uz"]
        print(f"   tap -> {label}")
        await feed(text_update(label, user_id=user, update_id=counter["n"] + 1))

        show("2. paging forward, then back")
        print("   tap -> Yana")
        await feed(
            callback_update(
                BrowsePageCB(action="next").pack(), user_id=user, update_id=counter["n"] + 1
            )
        )
        print("   tap -> Oldingi")
        await feed(
            callback_update(
                BrowsePageCB(action="prev").pack(), user_id=user, update_id=counter["n"] + 1
            )
        )

        chosen = product_id
        if chosen is None:
            async with factory() as session:
                page = await list_bouquets(session, shop_id=1)
            chosen = page.bouquets[0].product_id

        show(f"3. choosing bouquet {chosen} -- the shop's own post, verbatim")
        await feed(
            callback_update(
                BrowsePickCB(product_id=chosen).pack(), user_id=user, update_id=counter["n"] + 1
            )
        )
        print("   sent")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--product", type=int, default=None)
    args = parser.parse_args()
    asyncio.run(main(args.product))
