"""CP10b's live end-to-end: one real order, one real group message.

Drives the REAL dispatcher -- real routers, real middlewares, real FSM -- with a
REAL Bot against real Telegram and the real dev database. The order is written
to `orders`, the announcement is queued as ping 0, and the handler flushes it,
which is what puts a message in the shop's group.

THE ONE SYNTHETIC PART, stated plainly: the button taps. A `CallbackQuery` needs
an id Telegram issued, and this process is not a phone. So the `Update` objects
are constructed here, and `CallbackQuery.answer` -- the spinner acknowledgement
-- is stubbed out, because Telegram rejects an id it never minted. Everything
downstream of the tap is production code touching production services: the
customer's replies really arrive in their DM, and the shop's card really arrives
in the group.

    python scripts/live_order.py --product 16
    python scripts/live_order.py --product 16 --pin      # drop a pin instead
    python scripts/live_order.py --cleanup ORDER_ID      # remove a probe order

The token is read through Settings and never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

import psycopg  # noqa: E402
from aiogram.fsm.storage.memory import MemoryStorage  # noqa: E402
from aiogram.types import CallbackQuery  # noqa: E402
from tests.bot_harness import callback_update, location_update, text_update  # noqa: E402

from gulbot.bot.callbacks import (  # noqa: E402
    OrderConfirmCB,
    OrderDateCB,
    OrderHourCB,
    OrderLocationCB,
    OrderStartCB,
)
from gulbot.bot.factory import build_bot, build_dispatcher  # noqa: E402
from gulbot.config import get_settings  # noqa: E402
from gulbot.db.session import build_session_factory  # noqa: E402


def dsn() -> str:
    s = get_settings()
    return (
        f"host={s.postgres_host} port={s.postgres_port} user={s.postgres_user} "
        f"password={s.postgres_password} dbname={s.postgres_db}"
    )


def show(title: str) -> None:
    print(f"\n{'-' * 68}\n{title}\n{'-' * 68}")


def dump_state(order_id: int | None = None) -> None:
    with psycopg.connect(dsn(), autocommit=True) as conn:
        orders = conn.execute(
            "SELECT id, status, product_id, product_name_snapshot, price_uzs_snapshot, "
            " delivery_date, delivery_hour, delivery_location_text, delivery_location_lat, "
            " delivery_location_lon, landmark FROM orders ORDER BY id"
        ).fetchall()
        for row in orders:
            print("  order  :", row)
        pings = conn.execute(
            "SELECT id, order_id, ping_number, state, attempts, due_at_utc, sent_at "
            "FROM order_reminders ORDER BY id"
        ).fetchall()
        for row in pings:
            print("  ping   :", row)
        if order_id is not None and not orders:
            print("  (no orders)")


async def place(product_id: int, *, pin: bool) -> int | None:
    settings = get_settings()
    with psycopg.connect(dsn(), autocommit=True) as conn:
        customer = conn.execute(
            "SELECT id, telegram_user_id FROM customers WHERE shop_id = 1 ORDER BY id LIMIT 1"
        ).fetchone()
        group = conn.execute("SELECT group_chat_id FROM shops WHERE id = 1").fetchone()[0]
        product = conn.execute(
            "SELECT id, name, price_uzs FROM products WHERE id = %s AND finalized_at IS NOT NULL",
            (product_id,),
        ).fetchone()
    if customer is None or product is None:
        print("no customer, or the product is not a finalized channel row")
        return None

    print(f"customer  : id={customer[0]} telegram_user_id={customer[1]}")
    print(f"product   : id={product[0]} name={product[1]!r} price_uzs={product[2]}")
    print(f"group     : {group}")

    bot = build_bot()
    me = await bot.get_me()
    print(f"bot       : @{me.username}")

    dispatcher = build_dispatcher(
        session_factory=build_session_factory(settings.postgres_db),
        shop_id=1,
        storage=MemoryStorage(),
    )

    # The only substitution. See the module docstring: the tap is synthetic, so
    # its callback query id is too, and Telegram will not acknowledge one it did
    # not issue. Nothing downstream of the tap is affected.
    async def no_op_answer(self: CallbackQuery, *args: Any, **kwargs: Any) -> bool:
        return True

    CallbackQuery.answer = no_op_answer  # type: ignore[method-assign]

    user = customer[1]
    counter = {"n": 0}

    async def feed(update: Any) -> None:
        counter["n"] += 1
        await dispatcher.feed_update(bot, update)

    async def tap(data: str, label: str) -> None:
        print(f"  tap    -> {label}")
        await feed(callback_update(data, user_id=user, update_id=counter["n"] + 1))

    async def say(message: str) -> None:
        print(f"  type   -> {message!r}")
        await feed(text_update(message, user_id=user, update_id=counter["n"] + 1))

    try:
        show("1. the customer opens the order flow from the bouquet button")
        await tap(OrderStartCB(product_id=product_id).pack(), "Buyurtma berish")

        show("2. date, hour, location method")
        await tap(OrderDateCB(offset=1).pack(), "tomorrow")
        await tap(OrderHourCB(hour=14).pack(), "14:00")
        mode = "pin" if pin else "text"
        await tap(OrderLocationCB(mode=mode).pack(), mode)

        if pin:
            print("  pin    -> 41.311081, 69.240562")
            await feed(
                location_update(
                    user_id=user,
                    latitude=41.311081,
                    longitude=69.240562,
                    update_id=counter["n"] + 1,
                )
            )
        else:
            await say("Chilonzor 5, 12-uy, 4-podyezd")
        await say("Ko'k eshik, dorixona yonida")

        show("3. NOTHING is in `orders` yet -- the confirmation has not been tapped")
        dump_state()

        show("4. submit")
        await tap(OrderConfirmCB(action="submit").pack(), "Ha, tasdiqlayman")

        show("5. after submit: the order, its pings, and the announcement's fate")
        dump_state()
    finally:
        await bot.session.close()

    with psycopg.connect(dsn(), autocommit=True) as conn:
        row = conn.execute("SELECT max(id) FROM orders").fetchone()
    return None if row is None else row[0]


def seed_delivery_ping(order_id: int, *, seconds: int) -> None:
    """Make a DELIVERY reminder (ping 1) due almost immediately.

    Deliberately ping 1, not another 0: the two take different branches in the
    renderer, and the beat has to deliver both. `hours_ahead` is read from the
    ping's own due time, so this reports whatever interval it is given.
    """
    with psycopg.connect(dsn(), autocommit=True) as conn:
        conn.execute(
            "INSERT INTO order_reminders (shop_id, order_id, ping_number, due_at_utc) "
            "VALUES (1, %s, 1, %s) "
            "ON CONFLICT (order_id, ping_number) DO UPDATE "
            "SET due_at_utc = EXCLUDED.due_at_utc, state = 'pending', attempts = 0, "
            "    claimed_at = NULL, sent_at = NULL",
            (order_id, datetime.now(UTC) + timedelta(seconds=seconds)),
        )
    print(f"ping 1 for order {order_id} is due in {seconds}s")


def cleanup(order_id: int) -> None:
    with psycopg.connect(dsn(), autocommit=True) as conn:
        conn.execute("DELETE FROM order_reminders WHERE order_id = %s", (order_id,))
        conn.execute("DELETE FROM orders WHERE id = %s", (order_id,))
    print(f"removed probe order {order_id}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--product", type=int, default=None)
    parser.add_argument("--pin", action="store_true")
    parser.add_argument("--seed-ping", type=int, default=None, metavar="ORDER_ID")
    parser.add_argument("--in-seconds", type=int, default=20)
    parser.add_argument("--cleanup", type=int, default=None, metavar="ORDER_ID")
    parser.add_argument("--state", action="store_true")
    args = parser.parse_args()

    if args.cleanup is not None:
        cleanup(args.cleanup)
        return 0
    if args.seed_ping is not None:
        seed_delivery_ping(args.seed_ping, seconds=args.in_seconds)
        return 0
    if args.state:
        dump_state()
        return 0
    if args.product is None:
        parser.error("--product is required")
    order_id = asyncio.run(place(args.product, pin=args.pin))
    print(f"\norder id: {order_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
