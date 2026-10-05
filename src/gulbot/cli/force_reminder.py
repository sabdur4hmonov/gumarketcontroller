"""DEV/DEMO TOOL: force-send one reminder right now, bypassing the schedule.

    .\\.venv\\Scripts\\python.exe -m gulbot.cli.force_reminder --list
    .\\.venv\\Scripts\\python.exe -m gulbot.cli.force_reminder \\
        --shop-id=1 --customer-id=3 --occasion-id=7

THE SHOP IS NAMED, NOT INFERRED (L1 of AUDIT_MULTI_TENANT.md). Sending needs
`--shop-id`, and the customer, the date and the person are each looked up
inside that shop -- so a customer id from another shop is refused rather than
sent to as whichever shop it happens to belong to.

NOT the production send path, and never imported by it. It builds a transient
`DueGroup` from one real customer + occasion, then calls the exact same
rendering and bouquet-attachment code the real tick uses --
`gulbot.sending.render.render_reminder` and `gulbot.sending.attach.attach_bouquet`
-- so what you see is the real reminder, photo and order button included, not a
mock-up of one.

WHAT IT DOES NOT TOUCH. Nothing is read from or written to
`scheduled_notifications` or `message_log`: no claim, no due row, no state, no
`sent_at`, no attempt count. The row it renders from is a plain Python object
that is never added to a session. Running this twice sends the reminder twice
-- there is no idempotency here, deliberately, because this is a demo button,
not a scheduler. It must stay that way: never call this from `worker/tasks.py`
or any router.

REFUSES TO RUN IN PRODUCTION. `get_settings().environment == "production"` exits
before building a Bot or touching the database. This tool sends through the
REAL bot token with no rate limiting, no retry ladder and no dead-letter --
exactly the shortcut that has no place anywhere near real customers.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.config import PRODUCTION, get_settings
from gulbot.db.session import task_session_factory

# A real ScheduledNotification, never added to a session -- see the module
# docstring. Imported this way (not `from ... import ScheduledNotification`) so
# a reader scanning imports sees immediately that it is the model, not a row.
from gulbot.models import notification as notification_model
from gulbot.models.customer import Customer
from gulbot.models.occasion import Occasion
from gulbot.models.recipient import Recipient
from gulbot.models.shop import Shop
from gulbot.scheduling.occurrences import TASHKENT, occurrence_date_for
from gulbot.sending.attach import attach_bouquet
from gulbot.sending.dispatcher import DueGroup
from gulbot.sending.render import render_reminder
from gulbot.sending.transport import Attachment


def _next_occurrence(month: int, day: int, *, today: date) -> date:
    """The next real calendar date this occasion falls on, on or after today.

    Mirrors `scheduling.occurrences._occurrences` for one occasion: try this
    year, then next, so a birthday already past this year still demos as a
    real future date rather than a stale one.
    """
    for year in (today.year, today.year + 1):
        candidate = occurrence_date_for(month, day, year)
        if candidate >= today:
            return candidate
    raise AssertionError("unreachable: next year's date is always >= today")  # pragma: no cover


async def _list(shop_id: int | None, customer_id: int | None) -> None:
    async with task_session_factory() as factory, factory() as session:
        shop_stmt = select(Shop).order_by(Shop.id)
        if shop_id is not None:
            shop_stmt = shop_stmt.where(Shop.id == shop_id)
        shops = list(await session.scalars(shop_stmt))
        if not shops:
            print("no shops in this database" if shop_id is None else f"no shop id={shop_id}")
            return
        for shop in shops:
            print(f"shop id={shop.id} {shop.name!r}  reminder_offsets={shop.reminder_offsets}")
            customer_stmt = select(Customer).where(Customer.shop_id == shop.id)
            if customer_id is not None:
                customer_stmt = customer_stmt.where(Customer.id == customer_id)
            customers = list(await session.scalars(customer_stmt.order_by(Customer.id)))
            if not customers:
                print("  (no customers)" if customer_id is None else "  (no such customer)")
                continue
            for customer in customers:
                print(
                    f"  customer id={customer.id}  telegram_user_id={customer.telegram_user_id}"
                    f"  lang={customer.lang}  status={customer.status}"
                )
                occasions = list(
                    await session.scalars(
                        select(Occasion)
                        .where(Occasion.customer_id == customer.id, Occasion.active.is_(True))
                        .order_by(Occasion.id)
                    )
                )
                if not occasions:
                    print("      (no active occasions)")
                for occasion in occasions:
                    recipient = await session.scalar(
                        select(Recipient).where(
                            Recipient.id == occasion.recipient_id, Recipient.shop_id == shop.id
                        )
                    )
                    label = recipient.label if recipient else occasion.label
                    print(
                        f"      occasion id={occasion.id}  {label!r}  kind={occasion.kind}"
                        f"  {occasion.month:02d}-{occasion.day:02d}"
                    )


async def _build_group(
    session: AsyncSession, *, shop_id: int, customer_id: int, occasion_id: int, offset_days: int
) -> DueGroup:
    """Every lookup inside `shop_id`. See the module docstring."""
    customer = await session.scalar(
        select(Customer).where(Customer.id == customer_id, Customer.shop_id == shop_id)
    )
    if customer is None:
        raise SystemExit(f"no customer id={customer_id} in shop {shop_id}")

    occasion = await session.scalar(
        select(Occasion).where(
            Occasion.id == occasion_id,
            Occasion.shop_id == shop_id,
            Occasion.customer_id == customer.id,
        )
    )
    if occasion is None:
        raise SystemExit(
            f"occasion id={occasion_id} does not belong to customer id={customer_id} "
            f"in shop {shop_id}"
        )

    recipient = await session.scalar(
        select(Recipient).where(Recipient.id == occasion.recipient_id, Recipient.shop_id == shop_id)
    )
    if recipient is None:  # pragma: no cover - FK makes this unreachable
        raise SystemExit(f"occasion {occasion_id} has no recipient row")

    today = datetime.now(TASHKENT).date()
    anchor = _next_occurrence(occasion.month, occasion.day, today=today)
    # Mirrors plan_notifications: due date = anchor + offset_days. Reversing it
    # here is what makes render_reminder's "today/tomorrow/in N days" and its
    # displayed date agree with the real occasion date, for any offset.
    send_local_date = anchor + timedelta(days=offset_days)
    due_at_utc = datetime.combine(send_local_date, datetime.now(TASHKENT).time(), tzinfo=TASHKENT)

    # A real model instance, never `session.add()`-ed -- see the module
    # docstring. render_reminder and attach_bouquet only ever READ these
    # attributes; nothing here is persisted or flushed.
    fake_row = notification_model.ScheduledNotification(
        shop_id=customer.shop_id,
        customer_id=customer.id,
        occasion_id=occasion.id,
        occurrence_year=anchor.year,
        offset_days=offset_days,
        due_at_utc=due_at_utc.astimezone(UTC),
        channel="telegram",
        state=notification_model.NotificationState.PENDING.value,
        attempts=0,
        merge_key=None,
    )

    return DueGroup(
        key=f"force-reminder:{occasion.id}",
        customer_id=customer.id,
        shop_id=customer.shop_id,
        telegram_user_id=customer.telegram_user_id,
        lang=customer.lang,
        rows=(fake_row,),
        occasions=(occasion,),
        recipients=(recipient,),
    )


async def _render(
    shop_id: int, customer_id: int, occasion_id: int, offset_days: int
) -> tuple[str, Attachment | None, int, int]:
    """Everything that only READS: build the group, render, attach a bouquet.

    Returns (text, attachment, chat_id, shop_id).
    """
    async with task_session_factory() as factory, factory() as session:
        group = await _build_group(
            session,
            shop_id=shop_id,
            customer_id=customer_id,
            occasion_id=occasion_id,
            offset_days=offset_days,
        )
        attachment = await attach_bouquet(session, group, render=render_reminder)
    return render_reminder(group), attachment, group.telegram_user_id, group.shop_id


async def _deliver(shop_id: int, chat_id: int, text: str, attachment: Attachment | None) -> None:
    """The one part that talks to Telegram. No confirmation prompt in here --
    `input()` is blocking, and this coroutine must not block the event loop."""
    # The customer's OWN shop's bot, resolved exactly the way the real tick
    # resolves it (worker/tasks.py) -- its stored token, or the logged legacy
    # fallback -- and never cached across a call; see gulbot.bot.registry.
    from gulbot.bot.registry import registry_for
    from gulbot.sending.telegram import TelegramTransport
    from gulbot.sending.transport import ShopBotUnavailable

    async with task_session_factory() as factory, factory() as session:
        registry = await registry_for(session, shop_ids=[shop_id])
    try:
        try:
            bot = registry.bot_for(shop_id)
        except ShopBotUnavailable as missing:
            print(f"NOT sent: {missing}")
            sys.exit(1)
        transport = TelegramTransport(bot)
        if attachment is None:
            result = await transport.send_text(chat_id=chat_id, text=text)
        else:
            result = await transport.send_photo(
                chat_id=chat_id,
                file_id=attachment.file_id,
                caption=attachment.caption,
                reply_markup=attachment.reply_markup,
            )
    finally:
        await registry.close()

    if result.ok:
        print(f"sent. message_id={result.message_id}")
    else:
        print(f"NOT sent: error_code={result.error_code} blocked={result.blocked}")
        sys.exit(1)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m gulbot.cli.force_reminder",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--list", action="store_true", help="print shops, customers and their active occasions"
    )
    parser.add_argument(
        "--shop-id",
        type=int,
        default=None,
        help="the shop to send as (required to send); with --list, narrows to one shop",
    )
    parser.add_argument("--customer-id", type=int, default=None)
    parser.add_argument("--occasion-id", type=int, default=None)
    parser.add_argument(
        "--offset-days",
        type=int,
        default=0,
        help="simulate this reminder offset (0 = on the day, -1 = 1 day before, "
        "-7 = 7 days before -- see the shop's reminder_offsets from --list)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="render and attach, print the result, but never call Telegram",
    )
    args = parser.parse_args(argv)

    if not args.list and None in (args.shop_id, args.customer_id, args.occasion_id):
        parser.error("--shop-id, --customer-id and --occasion-id are required (or use --list)")
    return args


def main(argv: list[str] | None = None) -> None:
    # The reminder text carries real emoji (e.g. the heading's flower). A
    # Windows console's default codepage (cp1251, cp866, ...) cannot encode
    # them, and this is the one place that matters: an operator running this
    # from a plain terminal, not through pytest's captured output.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    settings = get_settings()
    if settings.environment.strip().lower() == PRODUCTION:
        raise SystemExit(
            "REFUSING TO RUN: this is a dev/demo tool that bypasses every rate limit, "
            "retry rule and claim in the send path. ENVIRONMENT=production is not allowed here."
        )

    args = _parse_args(argv)
    if args.list:
        asyncio.run(_list(args.shop_id, args.customer_id))
        return

    text, attachment, chat_id, shop_id = asyncio.run(
        _render(args.shop_id, args.customer_id, args.occasion_id, args.offset_days)
    )

    print("--- reminder text ---------------------------------------------------")
    print(text)
    print("-----------------------------------------------------------------------")
    if attachment is None:
        print("(no bouquet attached -- would send as bare text)")
    else:
        print(f"(bouquet attached: file_id={attachment.file_id!r}, has order button)")

    if args.dry_run:
        print("\n--dry-run: nothing sent.")
        return

    # Blocking on purpose, and outside any coroutine: this is the one place a
    # human confirms before the real Bot API gets called.
    print(f"\nAbout to send this to telegram_user_id={chat_id} for REAL.")
    answer = input("Send it now? [y/N] ").strip().lower()
    if answer not in ("y", "yes"):
        print("cancelled.")
        return

    asyncio.run(_deliver(shop_id, chat_id, text, attachment))


if __name__ == "__main__":
    main()
