"""CP13's live end-to-end: a real card in the real group, really acted on.

Drives the REAL dispatcher -- real routers, real middlewares, real FSM -- with a
REAL Bot against real Telegram and the real dev database. The order is written
to `orders`, the announcement is posted to the shop's actual group WITH the two
buttons on it, the transition really happens in Postgres, the card in the group
is really edited, and the customer really receives the message in their DM.

THE ONE SYNTHETIC PART, stated plainly: the tap itself. A `CallbackQuery` needs
an id Telegram issued, and this process is not a phone. So the `Update` is
constructed here -- carrying the REAL group chat id and the REAL message id of
the card that was just posted -- and `CallbackQuery.answer` is stubbed, because
Telegram rejects an id it never minted. Everything downstream of the tap is
production code: the same handler, the same compare-and-swap, the same edit,
the same notification.

    python scripts/live_confirm.py --shop-id 1 --customer-tg 123456789 --confirm
    python scripts/live_confirm.py --shop-id 1 --customer-tg 123456789 --reject "gul tugadi"
    python scripts/live_confirm.py --shop-id 1 --cleanup ORDER_ID

`--shop-id` is required: the shop is named, never "the first one" (L1 of
AUDIT_MULTI_TENANT.md), and its own bot posts the card and makes the edits.

THE CUSTOMER YOU NAME WILL RECEIVE A REAL MESSAGE. Pass your own Telegram id.

The token is read through Settings and never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

import psycopg  # noqa: E402
from aiogram.fsm.storage.memory import MemoryStorage  # noqa: E402
from aiogram.types import (  # noqa: E402
    CallbackQuery,
    Chat,
    Message,
    PhotoSize,
    Update,
    User,
)

from gulbot.bot.callbacks import OrderAdminCB  # noqa: E402
from gulbot.bot.channel import noop_scheduler  # noqa: E402
from gulbot.bot.factory import build_dispatcher  # noqa: E402
from gulbot.bot.registry import registry_for  # noqa: E402
from gulbot.config import get_settings  # noqa: E402
from gulbot.db.session import build_session_factory  # noqa: E402
from gulbot.sending.order_pings import run_order_ping_tick  # noqa: E402
from gulbot.sending.telegram import TelegramTransport  # noqa: E402

#: Marks a probe order so cleanup can find it. `orders.submit_token` is
#: varchar(32), so this plus a unix timestamp has to fit inside it.
PROBE_TOKEN = "cp13probe"


def dsn() -> str:
    s = get_settings()
    return (
        f"host={s.postgres_host} port={s.postgres_port} user={s.postgres_user} "
        f"password={s.postgres_password.get_secret_value()} dbname={s.postgres_db}"
    )


def show(title: str) -> None:
    print(f"\n{'-' * 68}\n{title}\n{'-' * 68}")


def order_row(order_id: int) -> tuple[Any, ...]:
    with psycopg.connect(dsn(), autocommit=True) as conn:
        row = conn.execute(
            "SELECT status, rejection_reason, status_changed_at FROM orders WHERE id = %s",
            (order_id,),
        ).fetchone()
    if row is None:
        raise SystemExit(f"order {order_id} is gone")
    return row


def ping_states(order_id: int) -> list[tuple[Any, ...]]:
    with psycopg.connect(dsn(), autocommit=True) as conn:
        return conn.execute(
            "SELECT ping_number, state FROM order_reminders WHERE order_id = %s "
            "ORDER BY ping_number",
            (order_id,),
        ).fetchall()


def ledger(order_id: int) -> list[tuple[Any, ...]]:
    with psycopg.connect(dsn(), autocommit=True) as conn:
        return conn.execute(
            "SELECT template_key, transition_key, status, error_code FROM message_log "
            "WHERE transition_key LIKE %s ORDER BY id",
            (f"order:{order_id}:%",),
        ).fetchall()


def make_probe_order(shop_id: int, customer_tg: int) -> tuple[int, int, int]:
    """A real order for a real customer, marked so cleanup can find it."""
    with psycopg.connect(dsn(), autocommit=True) as conn:
        found_shop = conn.execute(
            "SELECT group_chat_id FROM shops WHERE id = %s", (shop_id,)
        ).fetchone()
        if found_shop is None:
            raise SystemExit(f"no shop {shop_id}")
        group_chat_id = found_shop[0]
        if group_chat_id is None:
            raise SystemExit("shop has no group_chat_id; run scripts/verify_group.py first")

        found = conn.execute(
            "SELECT id FROM customers WHERE shop_id = %s AND telegram_user_id = %s",
            (shop_id, customer_tg),
        ).fetchone()
        if found is None:
            raise SystemExit(
                f"telegram id {customer_tg} is not a customer of shop {shop_id}. "
                "Send /start to the bot from that account first -- this script will not "
                "message a stranger."
            )
        customer_id = found[0]

        product = conn.execute(
            "SELECT id, name, price_uzs, telegram_file_id FROM products "
            "WHERE shop_id = %s AND active AND deleted_at IS NULL AND finalized_at IS NOT NULL "
            "ORDER BY indexed_at DESC LIMIT 1",
            (shop_id,),
        ).fetchone()
        if product is None:
            raise SystemExit("no sellable product in the catalogue to snapshot")
        product_id, name, price, file_id = product

        order_id = conn.execute(
            "INSERT INTO orders (shop_id, customer_id, product_id, product_name_snapshot, "
            " price_uzs_snapshot, telegram_file_id_snapshot, delivery_date, delivery_hour, "
            " delivery_location_text, landmark, recipient_name, status, submit_token) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, '14:00', 'Chilonzor 5', 'Kok eshik', "
            " 'Dilnoza', 'placed', %s) RETURNING id",
            (
                shop_id,
                customer_id,
                product_id,
                name,
                price,
                file_id,
                date.today() + timedelta(days=2),
                f"{PROBE_TOKEN}{int(datetime.now(UTC).timestamp())}",
            ),
        ).fetchone()
        assert order_id is not None  # RETURNING always answers an INSERT
        order_id = order_id[0]
        conn.execute(
            "INSERT INTO order_reminders (shop_id, order_id, ping_number, due_at_utc) "
            "VALUES (%s, %s, 0, now() - interval '1 second')",
            (shop_id, order_id),
        )
        # A delivery ping too, so rejection has something to cancel.
        conn.execute(
            "INSERT INTO order_reminders (shop_id, order_id, ping_number, due_at_utc) "
            "VALUES (%s, %s, 1, now() + interval '20 hours')",
            (shop_id, order_id),
        )
        print(f"order {order_id} written for shop {shop_id}, customer {customer_id}")
        print(f"  bouquet: {name} ({price} so'm)")
        return order_id, shop_id, int(group_chat_id)


def group_tap(
    action: str,
    order_id: int,
    *,
    group_id: int,
    card_message_id: int,
    tg: int,
    is_photo: bool,
    body: str,
) -> Update:
    """The tap, shaped like the card it was really attached to.

    `is_photo` is not cosmetic. The handler edits a photo card's CAPTION and a
    text card's TEXT, and Telegram refuses the wrong one -- so a probe that
    always claimed "text" would report a refused edit for every ordinary card
    and the live proof would be a false negative.

    `body` is the card's own rendered text, so the stamped result in the group
    reads exactly as it would after a real tap rather than the word "card".
    """
    card = Message(
        message_id=card_message_id,
        date=datetime.now(tz=UTC),
        chat=Chat(id=group_id, type="supergroup"),
        from_user=User(id=1, is_bot=True, first_name="bot"),
        **(
            {
                "caption": body,
                "photo": [PhotoSize(file_id="probe", file_unique_id="p", width=1, height=1)],
            }
            if is_photo
            else {"text": body}
        ),
    )
    return Update(
        update_id=int(datetime.now(UTC).timestamp()) % 100000,
        callback_query=CallbackQuery(
            id="cp13probe",
            from_user=User(id=tg, is_bot=False, first_name="Admin"),
            chat_instance="cp13probe",
            data=OrderAdminCB(action=action, order_id=order_id).pack(),
            message=card,
        ),
    )


def group_text(body: str, *, group_id: int, tg: int) -> Update:
    return Update(
        update_id=int(datetime.now(UTC).timestamp()) % 100000 + 1,
        message=Message(
            message_id=int(datetime.now(UTC).timestamp()) % 100000 + 2,
            date=datetime.now(tz=UTC),
            chat=Chat(id=group_id, type="supergroup"),
            from_user=User(id=tg, is_bot=False, first_name="Admin"),
            text=body,
        ),
    )


class RecordingTransport:
    """The real transport, plus the message id it just created.

    The tap has to name the card it was attached to, and only Telegram knows
    that id. Asking a human to read it off the screen and pass it back would
    make this a two-step ritual for no gain.
    """

    def __init__(self, inner: TelegramTransport) -> None:
        self.inner = inner
        self.message_ids: list[int] = []
        #: True when the last accepted send was a photo. The handler edits
        #: a caption or a text depending on it, and Telegram refuses the wrong one.
        self.was_photo = False
        self.body = ""

    async def _record(self, result: Any) -> Any:
        if result.ok and result.message_id is not None:
            self.message_ids.append(int(result.message_id))
        return result

    async def send_text(self, **kw: Any) -> Any:
        self.was_photo, self.body = False, str(kw.get("text", ""))
        return await self._record(await self.inner.send_text(**kw))

    async def send_photo(self, **kw: Any) -> Any:
        self.was_photo, self.body = True, str(kw.get("caption", ""))
        return await self._record(await self.inner.send_photo(**kw))

    async def copy_message(self, **kw: Any) -> Any:
        return await self._record(await self.inner.copy_message(**kw))


async def run(args: argparse.Namespace) -> None:
    async def no_op_answer(self: CallbackQuery, *a: Any, **kw: Any) -> bool:
        text = a[0] if a else kw.get("text")
        if text:
            print(f"  [callback answer] {text}")
        return True

    CallbackQuery.answer = no_op_answer  # type: ignore[method-assign,assignment]

    order_id, shop_id, group_id = make_probe_order(args.shop_id, args.customer_tg)
    session_factory = build_session_factory()
    async with session_factory() as session:
        registry = await registry_for(session, shop_ids=[shop_id])
    bot = registry.bot_for(shop_id)

    show("1. posting the card to the real group")
    transport = RecordingTransport(TelegramTransport(bot))
    async with session_factory() as session:
        result = await run_order_ping_tick(
            session,
            transport=transport,
            now_utc=datetime.now(UTC),
            only_order_id=order_id,
        )
    print(f"   tick: sent={result.sent} failed={result.failed} errors={result.errors}")
    if result.sent != 1 or not transport.message_ids:
        raise SystemExit("the card did not reach the group; nothing to act on")

    card_message_id = transport.message_ids[-1]
    kind = "photo + caption" if transport.was_photo else "text"
    print(f"   card posted to {group_id} as message {card_message_id} ({kind}), both buttons")

    dispatcher = build_dispatcher(
        session_factory=session_factory,
        shop_id=shop_id,
        storage=MemoryStorage(),
        schedule_finalize=noop_scheduler,
    )

    admin_tg = args.admin_tg or args.customer_tg
    if args.confirm:
        show("2. tapping Confirm")
        await dispatcher.feed_update(
            bot,
            group_tap(
                "confirm",
                order_id,
                group_id=group_id,
                card_message_id=card_message_id,
                tg=admin_tg,
                is_photo=transport.was_photo,
                body=transport.body,
            ),
        )
    else:
        show("2. tapping Reject")
        await dispatcher.feed_update(
            bot,
            group_tap(
                "reject",
                order_id,
                group_id=group_id,
                card_message_id=card_message_id,
                tg=admin_tg,
                is_photo=transport.was_photo,
                body=transport.body,
            ),
        )
        show(f"3. typing the reason: {args.reject!r}")
        await dispatcher.feed_update(bot, group_text(args.reject, group_id=group_id, tg=admin_tg))

    show("what the database says")
    status, reason, changed_at = order_row(order_id)
    print(f"   status            {status}")
    print(f"   rejection_reason  {reason!r}")
    print(f"   status_changed_at {changed_at}")
    print(f"   pings             {ping_states(order_id)}")
    print(f"   message_log       {ledger(order_id)}")
    print(f"\n   cleanup: python scripts/live_confirm.py --shop-id {shop_id} --cleanup {order_id}")

    await registry.close()


def cleanup(shop_id: int, order_id: int) -> None:
    with psycopg.connect(dsn(), autocommit=True) as conn:
        conn.execute(
            "DELETE FROM message_log WHERE transition_key LIKE %s", (f"order:{order_id}:%",)
        )
        conn.execute(
            "DELETE FROM order_reminders WHERE order_id = %s AND shop_id = %s", (order_id, shop_id)
        )
        deleted = conn.execute(
            "DELETE FROM orders WHERE id = %s AND shop_id = %s AND submit_token LIKE %s "
            "RETURNING id",
            (order_id, shop_id, f"{PROBE_TOKEN}%"),
        ).fetchone()
    print(f"removed probe order {order_id}" if deleted else f"order {order_id} is not a probe")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shop-id", type=int, required=True, help="the shop to act as")
    parser.add_argument("--customer-tg", type=int, help="who receives the real message")
    parser.add_argument("--admin-tg", type=int, help="who taps (defaults to --customer-tg)")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--reject", metavar="REASON")
    parser.add_argument("--cleanup", type=int, metavar="ORDER_ID")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.cleanup:
        cleanup(args.shop_id, args.cleanup)
        return
    if not args.customer_tg:
        parser.error("--customer-tg is required; that account receives a real message")
    if not args.confirm and not args.reject:
        parser.error("choose --confirm or --reject REASON")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
