"""Run INSIDE the rehearsal server, as the gulbot user, with the production
environment loaded (deploy/rehearsal/rehearse.sh does both). Each command
prints one line the rehearsal transcript keeps. Nothing here prints a secret.

    inside.py guard            what get_settings() sees: environment and database
    inside.py page             make a share page for the seeded shop; prints its path
    inside.py plant            plant one reminder due a minute ago; prints its id
    inside.py reminder <id>    that reminder's state, attempts and ledger entry
    inside.py jobs             the heartbeats: each periodic job's last finish
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from gulbot.config import get_settings
from gulbot.db.session import build_session_factory

#: A Telegram chat no bot can reach: the reminder is PROCESSED -- claimed,
#: attempted, its outcome recorded -- and delivered to no one. The rehearsal
#: must not message a real person.
NOBODY = 1


async def _shop_id(session) -> int:  # type: ignore[no-untyped-def]
    found = await session.scalar(text("SELECT min(id) FROM shops"))
    if found is None:
        raise SystemExit("no shop: run the seed first")
    return int(found)


async def page() -> None:
    from gulbot.services import share_pages
    from gulbot.services.customers import get_or_create_customer
    from gulbot.services.share_pages import YesNoDraft

    factory = build_session_factory()
    async with factory() as session:
        shop = await _shop_id(session)
        customer, _ = await get_or_create_customer(session, shop_id=shop, telegram_user_id=NOBODY)
        made = await share_pages.create_page(
            session,
            shop_id=shop,
            customer_id=customer.id,
            bot_username="rehearsal_bot",
            draft=YesNoDraft(
                template="minimal",
                lang="uz",
                question_preset="custom",
                question="Rehearsal: ishlayaptimi?",
                notify_creator=False,
            ),
        )
        await session.commit()
        print(f"/p/{made.token}")


async def plant() -> None:
    factory = build_session_factory()
    async with factory() as session:
        shop = await _shop_id(session)
        customer = await session.scalar(
            text(
                "INSERT INTO customers (shop_id, telegram_user_id) VALUES (:s, :t) "
                "ON CONFLICT (shop_id, telegram_user_id) DO UPDATE SET telegram_user_id = :t "
                "RETURNING id"
            ),
            {"s": shop, "t": NOBODY},
        )
        recipient = await session.scalar(
            text(
                "INSERT INTO recipients (shop_id, customer_id, label, type) "
                "VALUES (:s, :c, 'Onam', 'mother') RETURNING id"
            ),
            {"s": shop, "c": customer},
        )
        today = datetime.now(UTC)
        occasion = await session.scalar(
            text(
                "INSERT INTO occasions (shop_id, customer_id, recipient_id, label, type, kind, "
                " month, day) VALUES (:s, :c, :r, 'Onam', 'mother', 'birthday', :m, :d) "
                "RETURNING id"
            ),
            {"s": shop, "c": customer, "r": recipient, "m": today.month, "d": today.day},
        )
        row = await session.scalar(
            text(
                "INSERT INTO scheduled_notifications (shop_id, customer_id, occasion_id, "
                " occurrence_year, offset_days, due_at_utc, channel, merge_key) "
                "VALUES (:s, :c, :o, :y, 0, :due, 'telegram', :mk) RETURNING id"
            ),
            {
                "s": shop,
                "c": customer,
                "o": occasion,
                "y": today.year,
                "due": today - timedelta(minutes=1),
                "mk": f"rehearsal:{occasion}",
            },
        )
        await session.commit()
        print(row)


async def reminder(row_id: int) -> None:
    factory = build_session_factory()
    async with factory() as session:
        found = (
            await session.execute(
                text(
                    "SELECT n.state, n.attempts, m.status AS ledger, m.error_code "
                    "FROM scheduled_notifications n "
                    "LEFT JOIN message_log m ON m.transition_key = n.merge_key "
                    "WHERE n.id = :i"
                ),
                {"i": row_id},
            )
        ).one()
        print(
            f"state={found.state} attempts={found.attempts} "
            f"ledger={found.ledger} error={found.error_code}"
        )


async def jobs() -> None:
    factory = build_session_factory()
    async with factory() as session:
        rows = await session.execute(
            text("SELECT name, last_finished_at, last_ok FROM job_runs ORDER BY name")
        )
        for row in rows:
            print(f"{row.name}: finished {row.last_finished_at:%H:%M:%S} ok={row.last_ok}")


def main() -> None:
    command = sys.argv[1]
    if command == "guard":
        s = get_settings()
        print(f"environment={s.environment} database={s.postgres_db} host={s.postgres_host}")
    elif command == "page":
        asyncio.run(page())
    elif command == "plant":
        asyncio.run(plant())
    elif command == "reminder":
        asyncio.run(reminder(int(sys.argv[2])))
    elif command == "jobs":
        asyncio.run(jobs())
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
