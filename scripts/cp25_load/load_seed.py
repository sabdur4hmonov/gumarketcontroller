"""Seed only the owned CP25 capacity database; never the dev/live/test database."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, time, timedelta

import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import create_engine, insert, text

from gulbot.announcements.extraction import Fields
from gulbot.config import get_settings
from gulbot.models.announcement import AnnouncementDraft
from gulbot.models.shop import DEFAULT_WORKING_HOURS, Shop
from gulbot.services.shop_tokens import encrypt_token

DATABASE = "gulbot_cp25_load"
OWNER_MARKER = "gulbot-cp25-capacity-fixtures-only"
NOW = datetime(2027, 3, 8, 5, 0, tzinfo=UTC)
BOT_BASE = 600000
USER_BASE = 2000000
OWNER_BASE = 3000000


def token(bot_id: int) -> str:
    return f"{bot_id}:CP25TEST" + "T" * 27


def reset_owned_database() -> None:
    settings = get_settings()
    dsn = settings.database_url(database="postgres", driver="psycopg").replace(
        "postgresql+psycopg://", "postgresql://"
    )
    with psycopg.connect(dsn, autocommit=True) as connection:
        row = connection.execute(
            "SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname = %s",
            (DATABASE,),
        ).fetchone()
        if row is not None:
            if row[0] != OWNER_MARKER:
                raise RuntimeError("Capacity DB exists without this harness ownership marker")
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(DATABASE))
            )
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DATABASE)))
        connection.execute(
            sql.SQL("COMMENT ON DATABASE {} IS {}").format(
                sql.Identifier(DATABASE), sql.Literal(OWNER_MARKER)
            )
        )
    previous = os.environ.get("GULBOT_MIGRATION_DATABASE")
    os.environ["GULBOT_MIGRATION_DATABASE"] = DATABASE
    try:
        command.upgrade(Config("alembic.ini"), "head")
    finally:
        if previous is None:
            os.environ.pop("GULBOT_MIGRATION_DATABASE", None)
        else:
            os.environ["GULBOT_MIGRATION_DATABASE"] = previous


def seed(shops: int, *, customers: int = 3) -> None:
    if shops not in (2, 10, 25, 50, 100, 500, 1000) or customers != 3:
        raise ValueError("Use the bounded CP25 fixture sizes")
    reset_owned_database()
    settings = get_settings()
    engine = create_engine(settings.database_url(database=DATABASE, driver="psycopg"))
    try:
        with engine.begin() as connection:
            connection.execute(
                insert(Shop),
                [
                    {
                        "id": i,
                        "name": f"CP25 shop {i}",
                        "working_hours": DEFAULT_WORKING_HOURS,
                        "status": "active",
                        "channel_id": -1001000000 - i,
                        "group_chat_id": -1002000000 - i,
                        "owner_telegram_ids": [OWNER_BASE + i],
                        "bot_token_encrypted": encrypt_token(token(BOT_BASE + i)),
                        "bot_telegram_id": BOT_BASE + i,
                        "uses_process_bot_token": False,
                    }
                    for i in range(1, shops + 1)
                ],
            )
            connection.execute(
                text(
                    "INSERT INTO customers (id, shop_id, telegram_user_id, phone, phone_verified) "
                    "SELECT (r * :n) + i, i, :base + r * 10000 + i, '+998901234567', true "
                    "FROM generate_series(1, :n) i CROSS JOIN generate_series(0, 2) r"
                ),
                {"n": shops, "base": USER_BASE},
            )
            connection.execute(
                text(
                    "INSERT INTO recipients (id, shop_id, customer_id, label, type) "
                    "SELECT i, i, i, 'Onam', 'mother' FROM generate_series(1, :n) i"
                ),
                {"n": shops},
            )
            connection.execute(
                text(
                    "INSERT INTO occasions (id, shop_id, customer_id, recipient_id, label, "
                    "type, kind, month, day) "
                    "SELECT i, i, i, i, 'Onam', 'mother', 'birthday', 3, 8 "
                    "FROM generate_series(1, :n) i"
                ),
                {"n": shops},
            )
            connection.execute(
                text(
                    "INSERT INTO scheduled_notifications (shop_id, customer_id, occasion_id, "
                    "occurrence_year, "
                    "offset_days, due_at_utc, channel) "
                    "SELECT i, i, i, 2027, 0, :due, 'telegram' FROM generate_series(1, :n) i"
                ),
                {"n": shops, "due": NOW - timedelta(minutes=1)},
            )
            connection.execute(
                text(
                    "INSERT INTO orders (id, shop_id, customer_id, product_name_snapshot, "
                    "price_uzs_snapshot, telegram_file_id_snapshot, delivery_date, delivery_hour, "
                    "delivery_location_text, landmark, "
                    "status, submit_token) SELECT i, i, i, 'Atirgul', 450000, 'cp25-photo-' || i, "
                    ":delivery, :hour, 'CP25 fake address', 'CP25', 'placed', 'cp25-order-' || i "
                    "FROM generate_series(1, :n) i"
                ),
                {"n": shops, "delivery": date(2027, 3, 8), "hour": time(14)},
            )
            connection.execute(
                text(
                    "INSERT INTO order_reminders (shop_id, order_id, ping_number, due_at_utc) "
                    "SELECT i, i, 0, :due FROM generate_series(1, :n) i"
                ),
                {"n": shops, "due": NOW - timedelta(minutes=1)},
            )
            fields = Fields(flowers=["atirgul"], count=51, price=450000, colour="qizil").data()
            connection.execute(
                insert(AnnouncementDraft),
                [
                    {
                        "id": i,
                        "shop_id": i,
                        "author_id": OWNER_BASE + i,
                        "status": "preview",
                        "revision": 1,
                        "photos": [f"cp25-photo-{i}"],
                        "fields": fields,
                        "caption_style": "classic",
                        "image_style": "none",
                        "preview_media": [f"cp25-preview-{i}"],
                        "preview_caption": "Atirgul — 51 dona\nNarxi: 450000 so'm\n#atirgul",
                    }
                    for i in range(1, shops + 1)
                ],
            )
            # Explicit fixture IDs must never collide with owner customer rows
            # subsequently created by the real update middleware.
            for table in (
                "shops",
                "customers",
                "recipients",
                "occasions",
                "orders",
                "announcement_drafts",
            ):
                connection.execute(
                    text(
                        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                        f"(SELECT max(id) FROM {table}), true)"
                    )
                )
    finally:
        engine.dispose()
