"""Live evidence for CP17, on the pattern of live_pages.py: made through the
REAL dispatcher with the REAL dev bot against the real dev database, and
answered over HTTP against the running page server, as a visitor would.

1. A date invitation (Ha/Yo'q with a plan): two places, two times. A visitor
   presses Ha, picks one place and one time, and the creator gets ONE message
   naming them -- printed below exactly as the bot sent it.
2. An Uzrnoma: the visitor presses "Kechirdim"; the creator hears it once.
3. A taklifnoma made, then edited AFTER creation at the same link: title,
   message, programme, dress-code colours, countdown, seal letters, music,
   three photos sent to the bot (with GPS EXIF -- shown gone afterwards), and
   the wishes wall switched on; a guest leaves a wish.

THE ONE SYNTHETIC PART, as in live_pages.py: the taps and typed messages. A
CallbackQuery needs an id Telegram issued, so the Update objects are built
here and `CallbackQuery.answer` is stubbed. The photos are REAL Telegram
photos: the bot first sends each one to the customer's DM, and the file_id
Telegram returns is what the synthetic "customer sent a photo" update carries,
so the bot downloads it from Telegram exactly as it would a customer's photo.

Every message the bot sends is printed as it goes out ("bot ->").

    python -m gulbot.web.run                      # in another terminal
    python scripts/live_cp17.py --shop-id 1 --customer-id 3

The token is read through Settings and never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

import aiohttp  # noqa: E402
import psycopg  # noqa: E402
from aiogram import Bot  # noqa: E402
from aiogram.client.session.middlewares.base import BaseRequestMiddleware  # noqa: E402
from aiogram.fsm.storage.memory import MemoryStorage  # noqa: E402
from aiogram.methods import SendMessage, SendPhoto, TelegramMethod  # noqa: E402
from aiogram.types import (  # noqa: E402
    BufferedInputFile,
    CallbackQuery,
    Chat,
    Message,
    Update,
    User,
)
from PIL import Image, ImageDraw  # noqa: E402
from tests.bot_harness import callback_update, photo_sizes, text_update  # noqa: E402

from gulbot.bot.callbacks import (  # noqa: E402
    ColorCB,
    EditFieldCB,
    InviteDayCB,
    InviteEventCB,
    InviteHourCB,
    InviteMinuteCB,
    InviteMonthCB,
    MusicCB,
    MyPageCB,
    PageChoiceCB,
    PageConfirmCB,
    PageLangCB,
    PageMenuCB,
    PageQuestionCB,
    PageSkipCB,
    PageTemplateCB,
    PhotoCB,
    PlanCB,
    SealCB,
)
from gulbot.bot.factory import build_dispatcher  # noqa: E402
from gulbot.bot.registry import build_bot_for, registry_for  # noqa: E402
from gulbot.config import get_settings  # noqa: E402
from gulbot.db.session import build_session_factory  # noqa: E402
from gulbot.i18n.catalog import CATALOG  # noqa: E402
from gulbot.sending.page_notify import notify_page_answer  # noqa: E402

TASHKENT = ZoneInfo("Asia/Tashkent")
JSON_HEADERS = {"X-Requested-With": "gulbot", "Content-Type": "application/json"}


class Spoken(BaseRequestMiddleware):
    """Prints what the bot says, as it goes out to Telegram, and remembers the
    id of the last message it sent: a tap is made ON that message, as a real
    one would be, so a handler that edits its keyboard edits a real message."""

    def __init__(self, sent: list[str]) -> None:
        self.sent = sent
        self.last_message_id = 1

    async def __call__(
        self,
        make_request: Callable[[Bot, TelegramMethod[Any]], Awaitable[Any]],
        bot: Bot,
        method: TelegramMethod[Any],
    ) -> Any:
        if isinstance(method, SendMessage):
            self.sent.append(method.text)
            print("    bot -> " + method.text.replace("\n", "\n           "))
        elif isinstance(method, SendPhoto):
            print("    bot -> [photo]")
        result = await make_request(bot, method)
        if isinstance(method, (SendMessage, SendPhoto)) and isinstance(result, Message):
            self.last_message_id = result.message_id
        return result


def dsn() -> str:
    s = get_settings()
    return (
        f"host={s.postgres_host} port={s.postgres_port} user={s.postgres_user} "
        f"password={s.postgres_password.get_secret_value()} dbname={s.postgres_db}"
    )


def show(title: str) -> None:
    print(f"\n{'-' * 72}\n{title}\n{'-' * 72}")


def query(sql: str, *args: object) -> list[tuple[Any, ...]]:
    with psycopg.connect(dsn(), autocommit=True) as conn:
        return conn.execute(sql, args).fetchall()


def flower_photo(n: int) -> bytes:
    """A small picture made here, carrying a GPS EXIF block -- so the page
    can be shown to have dropped it."""
    image = Image.new("RGB", (900, 700), (250 - 30 * n, 225, 235))
    draw = ImageDraw.Draw(image)
    for i in range(6):
        x, y = 150 + 110 * i, 250 + 60 * ((i + n) % 3)
        draw.ellipse((x - 60, y - 60, x + 60, y + 60), fill=(220, 90 + 20 * n, 130))
        draw.ellipse((x - 18, y - 18, x + 18, y + 18), fill=(250, 210, 90))
    exif = Image.Exif()
    exif[0x8825] = {1: "N", 2: (41.0, 18.0, 0.0), 3: "E", 4: (69.0, 16.0, 0.0)}
    out = io.BytesIO()
    image.save(out, "JPEG", quality=85, exif=exif)
    return out.getvalue()


async def main(shop_id: int, customer_id: int) -> None:
    settings = get_settings()
    [(user,)] = query(
        "SELECT telegram_user_id FROM customers WHERE id = %s AND shop_id = %s",
        customer_id,
        shop_id,
    ) or [(None,)]
    if user is None:
        raise SystemExit(f"no customer {customer_id} in shop {shop_id}")
    user = int(user)
    sent: list[str] = []
    spoken = Spoken(sent)

    def spoken_bot(token: str | None) -> Bot:
        bot = build_bot_for(token)
        bot.session.middleware(spoken)
        return bot

    factory = build_session_factory(settings.postgres_db)
    async with factory() as session:
        registry = await registry_for(session, shop_ids=[shop_id], bot_factory=spoken_bot)
    bot = registry.bot_for(shop_id)
    me = await bot.get_me()
    print(f"shop {shop_id}, bot @{me.username}, customer {customer_id}")
    base = settings.public_base_url.rstrip("/")

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
        await feed(
            callback_update(
                data,
                user_id=user,
                update_id=counter["n"] + 1,
                message_id=spoken.last_message_id,
            )
        )

    async def say(body: str) -> None:
        print(f"  type -> {body!r}")
        await feed(text_update(body, user_id=user, update_id=counter["n"] + 1))

    async def send_photo(n: int) -> None:
        """A real Telegram photo: sent to the DM first, then 'sent back'."""
        posted = await bot.send_photo(
            user, BufferedInputFile(flower_photo(n), filename=f"gul-{n}.jpg")
        )
        assert posted.photo
        file_id = posted.photo[-1].file_id
        print(f"  photo-> gul-{n}.jpg (with GPS EXIF)")
        sizes = photo_sizes(file_id)
        sizes[0] = posted.photo[0]  # the real thumbnail, not the harness's stand-in
        await feed(
            Update(
                update_id=counter["n"] + 1,
                message=Message(
                    message_id=counter["n"] + 1,
                    date=datetime.now(tz=UTC),
                    chat=Chat(id=user, type="private"),
                    from_user=User(id=user, is_bot=False, first_name="Aziz"),
                    photo=sizes,
                ),
            )
        )

    # Only a page made BY THIS RUN is evidence. Without this, a refused
    # creation (the 5-a-day limit counts deleted pages too) silently reused an
    # older page and printed its state as if it were new.
    [(baseline,)] = query("SELECT coalesce(max(id), 0) FROM share_pages")

    def newest(kind: str) -> tuple[int, str]:
        rows = query(
            "SELECT id, token FROM share_pages WHERE shop_id = %s AND customer_id = %s "
            "AND kind = %s AND deleted_at IS NULL AND id > %s ORDER BY id DESC LIMIT 1",
            shop_id,
            customer_id,
            kind,
            baseline,
        )
        if not rows:
            raise SystemExit(
                f"no new {kind} page was made by this run -- see the bot's reply above "
                "(the creation limit is 5 pages per customer in any 24 hours)"
            )
        [(page_id, token)] = rows
        return int(page_id), str(token)

    target = (datetime.now(TASHKENT) + timedelta(days=9)).date()
    wedding = (datetime.now(TASHKENT) + timedelta(days=40)).date()
    try:
        show("1. A date invitation: Ha/Yo'q + plan -- two places, two times, Romantik")
        await say(CATALOG["btn.menu.pages"]["uz"])
        await tap(PageMenuCB(action="yesno").pack(), "Ha/Yo'q sahifa")
        await tap(PageLangCB(lang="uz").pack(), "O'zbekcha (lotin)")
        await tap(PageQuestionCB(preset="date").pack(), "Uchrashuvga chiqamizmi?")
        await tap(PlanCB(action="add").pack(), "Reja qo'shish")
        await say("Kino, Magic Cinema")
        await tap(PlanCB(action="more_place").pack(), "Yana joy")
        await say("Bog'da sayr, Yapon bog'i")
        await tap(PlanCB(action="places_done").pack(), "Joylar tayyor")
        for hour in (19, 20):
            await tap(InviteMonthCB(year=target.year, month=target.month).pack(), "oy")
            await tap(InviteDayCB(day=target.day).pack(), f"{target.day}")
            await tap(InviteHourCB(hour=hour).pack(), f"{hour}:__")
            await tap(InviteMinuteCB(minute=0).pack(), f"{hour}:00")
            if hour == 19:
                await tap(PlanCB(action="more_slot").pack(), "Yana vaqt")
        await tap(PlanCB(action="slots_done").pack(), "Vaqtlar tayyor")
        await tap(PageTemplateCB(template="romantik").pack(), "Romantik")
        await tap(PageChoiceCB(field="notify", value="yes").pack(), "Ha, xabar bering")
        await tap(PageConfirmCB(action="create").pack(), "Yaratish")
        date_id, date_token = newest("yesno")

        show("2. An Uzrnoma: Russian, Konvert, tell me when forgiven")
        await say(CATALOG["btn.menu.pages"]["uz"])
        await tap(PageMenuCB(action="apology").pack(), "Uzrnoma")
        await tap(PageLangCB(lang="ru").pack(), "Русский")
        await say("Прости меня за вчерашнее.\nЯ был неправ и очень скучаю.")
        await tap(PageTemplateCB(template="konvert").pack(), "Konvert")
        await tap(PageChoiceCB(field="notify", value="yes").pack(), "Ha")
        await tap(PageConfirmCB(action="create").pack(), "Yaratish")
        sorry_id, sorry_token = newest("apology")

        show("3. A taklifnoma: wedding, Uzbek, Konvert -- then EDITED after creation")
        await say(CATALOG["btn.menu.pages"]["uz"])
        await tap(PageMenuCB(action="invite").pack(), "Taklifnoma")
        await tap(InviteEventCB(event="wedding").pack(), "To'y")
        await tap(PageLangCB(lang="uz").pack(), "O'zbekcha (lotin)")
        await say("Sardor")
        await say("Madina")
        await tap(InviteMonthCB(year=wedding.year, month=wedding.month).pack(), "oy")
        await tap(InviteDayCB(day=wedding.day).pack(), f"{wedding.day}")
        await tap(InviteHourCB(hour=18).pack(), "18:__")
        await tap(InviteMinuteCB(minute=0).pack(), "18:00")
        await say("Toshkent, «Bahor» to'yxonasi")
        await tap(PageSkipCB(step="location").pack(), "Xaritasiz")
        await say("Sizni kutamiz!")
        await tap(PageChoiceCB(field="rsvp", value="yes").pack(), "RSVP: ha")
        await tap(PageTemplateCB(template="konvert").pack(), "Konvert")
        await tap(SealCB(action="skip").pack(), "Bosh harflar bilan")
        await tap(PageConfirmCB(action="create").pack(), "Yaratish")
        invite_id, invite_token = newest("invite")
        async with aiohttp.ClientSession() as http, http.get(f"{base}/p/{invite_token}") as r:
            before = await r.text()

        show("3b. Editing it: same link, new content")
        await tap(MyPageCB(action="edit", page_id=invite_id).pack(), "Tahrirlash")
        await tap(EditFieldCB(page_id=invite_id, field="title").pack(), "Sarlavha")
        await say("Sardor va Madinaning nikoh oqshomi")
        await tap(EditFieldCB(page_id=invite_id, field="message").pack(), "Xabar")
        await say("Quvonchli kunimizda yonimizda bo'ling!")
        await tap(EditFieldCB(page_id=invite_id, field="program").pack(), "Dastur")
        await say("18:00 Kutib olish\n19.00 Nikoh\n20:30 Ziyofat")
        await tap(EditFieldCB(page_id=invite_id, field="dress_colors").pack(), "Ranglar")
        for key in ("oq", "oltin", "pushti"):
            await tap(ColorCB(color=key).pack(), key)
        await tap(ColorCB(color="done").pack(), "Tayyor")
        await tap(EditFieldCB(page_id=invite_id, field="seal_monogram").pack(), "Muhr")
        await say("s&m")
        await tap(EditFieldCB(page_id=invite_id, field="music").pack(), "Musiqa")
        await tap(MusicCB(track="tantana").pack(), "Tantana")
        await tap(EditFieldCB(page_id=invite_id, field="photo").pack(), "Suratlar")
        for n in (1, 2, 3):
            await send_photo(n)
        await tap(PhotoCB(action="done").pack(), "Tayyor")
        await tap(EditFieldCB(page_id=invite_id, field="wishes_enabled").pack(), "Tilaklar")
    finally:
        await registry.close()

    show("4. Visitors, over HTTP against the page server")
    async with aiohttp.ClientSession() as http:
        async with http.get(f"{base}/p/{date_token}") as r:
            print(f"  GET  date page   -> {r.status}")
        async with http.post(f"{base}/p/{date_token}/yes", data="{}", headers=JSON_HEADERS) as r:
            print(f"  POST Ha          -> {r.status}")
        options = query(
            "SELECT id, kind, place, slot_at FROM share_page_options WHERE page_id = %s "
            "ORDER BY kind, position",
            date_id,
        )
        place = next(o for o in options if o[1] == "place" and o[2].startswith("Bog'"))
        slot = next(o for o in options if o[1] == "slot" and o[3].astimezone(TASHKENT).hour == 20)
        print(f"  choose -> place {place[2]!r}, time {slot[3].astimezone(TASHKENT):%d.%m %H:%M}")
        body = json.dumps({"place": place[0], "slot": slot[0]})
        async with http.post(f"{base}/p/{date_token}/choose", data=body, headers=JSON_HEADERS) as r:
            print(f"  POST choose      -> {r.status}")
        async with http.post(f"{base}/p/{sorry_token}/yes", data="{}", headers=JSON_HEADERS) as r:
            print(f"  POST Kechirdim   -> {r.status}")
        wish = json.dumps({"name": "Dilnoza opa", "text": "Baxtli bo'linglar! <b>Omad</b>"})
        async with http.post(f"{base}/p/{invite_token}/wish", data=wish, headers=JSON_HEADERS) as r:
            print(f"  POST wish        -> {r.status}")
        async with http.get(f"{base}/p/{invite_token}") as r:
            after = await r.text()

    show("5. The creator is told -- once each -- through the shop's own bot")
    for label, page_id in (("date invitation", date_id), ("Uzrnoma", sorry_id)):
        first = await notify_page_answer(page_id, session_factory=factory, bot_factory=spoken_bot)
        second = await notify_page_answer(page_id, session_factory=factory, bot_factory=spoken_bot)
        print(f"  {label}: first={first} second={second}")

    show("6. The taklifnoma, same link before and after editing")
    [(token_now,)] = query("SELECT token FROM share_pages WHERE id = %s", invite_id)
    print(f"  link unchanged: {token_now == invite_token}  ({base}/p/<token>)")
    for label, needle in (
        ("new title", "Sardor va Madinaning nikoh oqshomi"),
        ("programme row", '<span class="program-at">19:00</span>'),
        ("seal letters", ">S&amp;M</button>"),
        ("music button", 'data-track="tantana"'),
        ("guest wish, escaped", "&lt;b&gt;Omad&lt;/b&gt;"),
    ):
        print(f"  {label:20}: before={needle in before}  after={needle in after}")
    photos = query(
        "SELECT position, size_bytes, width, height FROM share_page_photos WHERE page_id = %s "
        "ORDER BY position",
        invite_id,
    )
    print(f"  photos stored: {[(p[0], p[1], f'{p[2]}x{p[3]}') for p in photos]}")
    gps = query(
        "SELECT count(*) FROM share_page_photos WHERE page_id = %s "
        "AND position('GPS'::bytea in data) > 0",
        invite_id,
    )[0][0]
    print(f"  photos still carrying a GPS block: {gps}")
    for row in query(
        "SELECT id, kind, template, answered_at IS NOT NULL, notified_at IS NOT NULL, "
        " chosen_place, chosen_slot_at FROM share_pages WHERE id IN (%s, %s, %s) ORDER BY id",
        date_id,
        sorry_id,
        invite_id,
    ):
        print(
            f"  page {row[0]} {row[1]:8} {row[2]:9} answered={row[3]} notified={row[4]}"
            f" chosen={row[5]!r} {row[6]}"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--shop-id", type=int, required=True)
    parser.add_argument("--customer-id", type=int, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.shop_id, args.customer_id))
