"""Live evidence for the share pages: one Ha/Yo'q page and one taklifnoma,
made through the REAL dispatcher with the REAL dev bot against the real dev
database. The bot's replies, the links included, arrive in the customer's DM.

THE ONE SYNTHETIC PART, as in live_order.py: the taps. A CallbackQuery needs an
id Telegram issued, so the Update objects are built here and
`CallbackQuery.answer` (the spinner acknowledgement) is stubbed. Everything
downstream of a tap is production code.

Then, as a visitor would: the Ha page is opened and Ha is pressed over HTTP
against the running page server, and the creator's "they said Ha" message is
sent exactly as the worker task sends it -- through the shop's own bot.

    python -m gulbot.web.run                      # in another terminal
    python scripts/live_pages.py --shop-id 1 --customer-id 3

The token is read through Settings and never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

import aiohttp  # noqa: E402
import psycopg  # noqa: E402
from aiogram.fsm.storage.memory import MemoryStorage  # noqa: E402
from aiogram.types import CallbackQuery  # noqa: E402
from tests.bot_harness import callback_update, location_update, text_update  # noqa: E402

from gulbot.bot.callbacks import (  # noqa: E402
    InviteDayCB,
    InviteEventCB,
    InviteHourCB,
    InviteMinuteCB,
    InviteMonthCB,
    PageChoiceCB,
    PageConfirmCB,
    PageLangCB,
    PageMenuCB,
    PageQuestionCB,
    PageTemplateCB,
)
from gulbot.bot.factory import build_dispatcher  # noqa: E402
from gulbot.bot.registry import registry_for  # noqa: E402
from gulbot.config import get_settings  # noqa: E402
from gulbot.db.session import build_session_factory  # noqa: E402
from gulbot.i18n.catalog import CATALOG  # noqa: E402
from gulbot.sending.page_notify import notify_page_answer  # noqa: E402


def dsn() -> str:
    s = get_settings()
    return (
        f"host={s.postgres_host} port={s.postgres_port} user={s.postgres_user} "
        f"password={s.postgres_password.get_secret_value()} dbname={s.postgres_db}"
    )


def show(title: str) -> None:
    print(f"\n{'-' * 68}\n{title}\n{'-' * 68}")


async def main(shop_id: int, customer_id: int) -> None:
    settings = get_settings()
    with psycopg.connect(dsn(), autocommit=True) as conn:
        row = conn.execute(
            "SELECT telegram_user_id FROM customers WHERE id = %s AND shop_id = %s",
            (customer_id, shop_id),
        ).fetchone()
    if row is None:
        raise SystemExit(f"no customer {customer_id} in shop {shop_id}")
    user = int(row[0])

    factory = build_session_factory(settings.postgres_db)
    async with factory() as session:
        registry = await registry_for(session, shop_ids=[shop_id])
    bot = registry.bot_for(shop_id)
    me = await bot.get_me()
    print(f"shop {shop_id}, bot @{me.username}, customer {customer_id}")

    dispatcher = build_dispatcher(session_factory=factory, shop_id=shop_id, storage=MemoryStorage())

    async def no_op_answer(self: CallbackQuery, *args: Any, **kwargs: Any) -> bool:
        return True

    CallbackQuery.answer = no_op_answer  # type: ignore[method-assign,assignment]
    counter = {"n": 0}

    async def feed(update: Any) -> None:
        counter["n"] += 1
        await dispatcher.feed_update(bot, update)

    async def tap(data: str, label: str) -> None:
        print(f"  tap  -> {label}")
        await feed(callback_update(data, user_id=user, update_id=counter["n"] + 1))

    async def say(body: str) -> None:
        print(f"  type -> {body!r}")
        await feed(text_update(body, user_id=user, update_id=counter["n"] + 1))

    try:
        show("1. Ha/Yo'q page: Uzbek, the proposal question, Romantik, tell me on Ha")
        await say(CATALOG["btn.menu.pages"]["uz"])
        await tap(PageMenuCB(action="yesno").pack(), "Ha/Yo'q sahifa")
        await tap(PageLangCB(lang="uz").pack(), "O'zbekcha (lotin)")
        await tap(PageQuestionCB(preset="marry").pack(), "Menga turmushga chiqasanmi?")
        await tap(PageTemplateCB(template="romantik").pack(), "Romantik")
        await tap(PageChoiceCB(field="notify", value="yes").pack(), "Ha, xabar bering")
        await tap(PageConfirmCB(action="create").pack(), "Yaratish")

        show("2. Taklifnoma: wedding, Uzbek, two names, a date next month, a pin, RSVP, Milliy")
        today = datetime.now(ZoneInfo("Asia/Tashkent")).date()
        year, month = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
        await say(CATALOG["btn.menu.pages"]["uz"])
        await tap(PageMenuCB(action="invite").pack(), "Taklifnoma")
        await tap(InviteEventCB(event="wedding").pack(), "To'y")
        await tap(PageLangCB(lang="uz").pack(), "O'zbekcha (lotin)")
        await say("Sardor")
        await say("Madina")
        await tap(InviteMonthCB(year=year, month=month).pack(), f"{month:02d}.{year}")
        await tap(InviteDayCB(day=14).pack(), "14")
        await tap(InviteHourCB(hour=18).pack(), "18:__")
        await tap(InviteMinuteCB(minute=30).pack(), "18:30")
        await say("Toshkent, Yunusobod tumani, «Bahor» to'yxonasi")
        print("  pin  -> 41.3647, 69.2850")
        await feed(
            location_update(
                user_id=user, latitude=41.3647, longitude=69.2850, update_id=counter["n"] + 1
            )
        )
        await say("Sizni to'yimizda ko'rishdan baxtiyor bo'lamiz!")
        await tap(PageChoiceCB(field="rsvp", value="yes").pack(), "RSVP: ha")
        await tap(PageTemplateCB(template="milliy").pack(), "Milliy naqsh")
        await tap(PageConfirmCB(action="create").pack(), "Yaratish")
    finally:
        await registry.close()

    with psycopg.connect(dsn(), autocommit=True) as conn:
        pages = conn.execute(
            "SELECT id, kind, template, lang, token, bot_username FROM share_pages "
            "WHERE shop_id = %s AND customer_id = %s ORDER BY id DESC LIMIT 2",
            (shop_id, customer_id),
        ).fetchall()
    show("3. The two pages, as stored")
    base = settings.public_base_url.rstrip("/")
    for page_id, kind, template, lang, token, username in reversed(pages):
        print(f"  page {page_id}: {kind} / {template} / {lang} / links back to @{username}")
        print(f"    {base}/p/{token}")

    yesno = next(p for p in pages if p[1] == "yesno")
    invite = next(p for p in pages if p[1] == "invite")
    show("4. A visitor opens the Ha/Yo'q page, presses Ha, and RSVPs to the taklifnoma")
    headers = {"X-Requested-With": "gulbot", "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as http:
        for token, action, body in (
            (yesno[4], "yes", {}),
            (invite[4], "rsvp", {"answer": "yes", "guests": 2, "name": "Dilnoza"}),
        ):
            async with http.get(f"{base}/p/{token}") as page:
                print(f"  GET  page  -> {page.status}")
            async with http.post(
                f"{base}/p/{token}/{action}", data=json.dumps(body), headers=headers
            ) as response:
                print(f"  POST {action:5} -> {response.status}")

    show("5. The creator is told -- once -- through the shop's own bot")
    print("  first :", await notify_page_answer(yesno[0], session_factory=factory))
    print("  second:", await notify_page_answer(yesno[0], session_factory=factory))

    with psycopg.connect(dsn(), autocommit=True) as conn:
        for row in conn.execute(
            "SELECT id, kind, view_count, answered_at IS NOT NULL, notified_at IS NOT NULL, "
            " (SELECT count(*) FROM share_page_rsvps r WHERE r.page_id = p.id) "
            "FROM share_pages p WHERE id IN (%s, %s) ORDER BY id",
            (yesno[0], invite[0]),
        ):
            print(
                f"  page {row[0]} {row[1]:6}: views={row[2]} answered={row[3]} "
                f"notified={row[4]} rsvps={row[5]}"
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--shop-id", type=int, required=True)
    parser.add_argument("--customer-id", type=int, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.shop_id, args.customer_id))
