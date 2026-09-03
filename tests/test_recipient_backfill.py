"""The CP3.5 backfill, run against data that predates it.

The interesting case is not "does the migration run" but "does it run against
rows written by the OLD schema". So this seeds occasions at the pre-recipients
revision and then migrates forward, on a throwaway database.
"""

from __future__ import annotations

import json

import pytest
from alembic import command
from sqlalchemy import create_engine, text
from tests.conftest import alembic_config_for, create_database, drop_database

from gulbot.config import Settings
from gulbot.models.shop import DEFAULT_WORKING_HOURS

BACKFILL_DB = "gulbot_backfill_probe"

# The revision that added occasions, before recipients existed.
PRE_RECIPIENTS_REVISION = "a87cd107a0ed"


@pytest.fixture
def seeded_old_schema(settings: Settings):
    """A database at the pre-recipients revision, holding legacy occasions."""
    drop_database(settings, BACKFILL_DB)
    create_database(settings, BACKFILL_DB)
    url = settings.database_url(database=BACKFILL_DB, driver="psycopg")

    with alembic_config_for(BACKFILL_DB) as cfg:
        command.upgrade(cfg, PRE_RECIPIENTS_REVISION)

        engine = create_engine(url)
        with engine.begin() as conn:
            shop_id = conn.execute(
                text(
                    "INSERT INTO shops (name, working_hours) "
                    "VALUES ('Legacy', CAST(:wh AS jsonb)) RETURNING id"
                ),
                {"wh": json.dumps(DEFAULT_WORKING_HOURS)},
            ).scalar_one()
            alice = conn.execute(
                text(
                    "INSERT INTO customers (shop_id, telegram_user_id) "
                    "VALUES (:s, 1001) RETURNING id"
                ),
                {"s": shop_id},
            ).scalar_one()
            bob = conn.execute(
                text(
                    "INSERT INTO customers (shop_id, telegram_user_id) "
                    "VALUES (:s, 1002) RETURNING id"
                ),
                {"s": shop_id},
            ).scalar_one()

            legacy = [
                # Alice: same label twice (birthday + anniversary) -> ONE recipient.
                (alice, "Onam", "mother", 3, 8),
                (alice, "Onam", "mother", 11, 2),
                (alice, "Otam", "father", 5, 9),
                # Bob shares a label with Alice -> a SEPARATE recipient.
                (bob, "Onam", "mother", 3, 8),
                (bob, "Singlim", "custom", 7, 21),
            ]
            for customer_id, label, type_, month, day in legacy:
                conn.execute(
                    text(
                        "INSERT INTO occasions "
                        "(shop_id, customer_id, label, type, month, day) "
                        "VALUES (:s, :c, :l, :t, :m, :d)"
                    ),
                    {"s": shop_id, "c": customer_id, "l": label, "t": type_, "m": month, "d": day},
                )
        engine.dispose()

        yield {"cfg": cfg, "url": url, "shop_id": shop_id, "alice": alice, "bob": bob}

    drop_database(settings, BACKFILL_DB)


@pytest.mark.infra
def test_backfill_gives_every_occasion_a_recipient(seeded_old_schema: dict) -> None:
    command.upgrade(seeded_old_schema["cfg"], "head")

    engine = create_engine(seeded_old_schema["url"])
    try:
        with engine.connect() as conn:
            orphans = conn.execute(
                text("SELECT count(*) FROM occasions WHERE recipient_id IS NULL")
            ).scalar_one()
            total = conn.execute(text("SELECT count(*) FROM occasions")).scalar_one()
    finally:
        engine.dispose()

    assert total == 5, "seed data was lost by the migration"
    assert orphans == 0


@pytest.mark.infra
def test_backfill_creates_one_recipient_per_customer_label_pair(
    seeded_old_schema: dict,
) -> None:
    """Alice's two "Onam" dates collapse to one recipient; Bob's stays separate."""
    command.upgrade(seeded_old_schema["cfg"], "head")

    engine = create_engine(seeded_old_schema["url"])
    try:
        with engine.connect() as conn:
            duplicates = conn.execute(
                text(
                    "SELECT customer_id, label, count(*) FROM recipients "
                    "GROUP BY customer_id, label HAVING count(*) > 1"
                )
            ).all()
            rows = conn.execute(
                text("SELECT customer_id, label, type FROM recipients ORDER BY customer_id, label")
            ).all()
    finally:
        engine.dispose()

    assert duplicates == [], f"a recipient was created twice: {duplicates}"
    alice, bob = seeded_old_schema["alice"], seeded_old_schema["bob"]
    assert [(r.customer_id, r.label, r.type) for r in rows] == [
        (alice, "Onam", "mother"),
        (alice, "Otam", "father"),
        (bob, "Onam", "mother"),
        (bob, "Singlim", "custom"),
    ]


@pytest.mark.infra
def test_backfill_points_each_occasion_at_its_own_customers_recipient(
    seeded_old_schema: dict,
) -> None:
    """A shared label must never route one customer's date to another's person."""
    command.upgrade(seeded_old_schema["cfg"], "head")

    engine = create_engine(seeded_old_schema["url"])
    try:
        with engine.connect() as conn:
            mismatched = conn.execute(
                text(
                    "SELECT count(*) FROM occasions o JOIN recipients r ON r.id = o.recipient_id "
                    "WHERE r.customer_id <> o.customer_id OR r.label <> o.label"
                )
            ).scalar_one()
            alice_onam = conn.execute(
                text(
                    "SELECT count(DISTINCT o.recipient_id) FROM occasions o "
                    "WHERE o.customer_id = :c AND o.label = 'Onam'"
                ),
                {"c": seeded_old_schema["alice"]},
            ).scalar_one()
    finally:
        engine.dispose()

    assert mismatched == 0
    assert alice_onam == 1, "Alice's two Onam dates should share one recipient"


@pytest.mark.infra
def test_recipient_id_is_not_null_after_the_validating_migration(
    seeded_old_schema: dict,
) -> None:
    """The second migration is what turns a missed row into a failed deploy."""
    command.upgrade(seeded_old_schema["cfg"], "head")

    engine = create_engine(seeded_old_schema["url"])
    try:
        with engine.connect() as conn:
            nullable = conn.execute(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'occasions' AND column_name = 'recipient_id'"
                )
            ).scalar_one()
    finally:
        engine.dispose()

    assert nullable == "NO"


@pytest.mark.infra
def test_two_recipients_may_share_a_label_after_migrating(
    seeded_old_schema: dict,
) -> None:
    """The old unique key made this impossible, which is why it was replaced."""
    command.upgrade(seeded_old_schema["cfg"], "head")

    engine = create_engine(seeded_old_schema["url"])
    try:
        with engine.begin() as conn:
            alice = seeded_old_schema["alice"]
            shop = seeded_old_schema["shop_id"]
            first, second = (
                conn.execute(
                    text(
                        "INSERT INTO recipients (shop_id, customer_id, label, type) "
                        "VALUES (:s, :c, 'Do''stim', 'friend'), (:s, :c, 'Do''stim', 'friend') "
                        "RETURNING id"
                    ),
                    {"s": shop, "c": alice},
                )
                .scalars()
                .all()
            )
            # Same label, same date, two different people: must both be storable.
            for recipient_id in (first, second):
                conn.execute(
                    text(
                        "INSERT INTO occasions "
                        "(shop_id, customer_id, recipient_id, label, type, month, day) "
                        "VALUES (:s, :c, :r, 'Do''stim', 'friend', 6, 6)"
                    ),
                    {"s": shop, "c": alice, "r": recipient_id},
                )

        with engine.connect() as conn:
            count = conn.execute(
                text("SELECT count(*) FROM occasions WHERE month = 6 AND day = 6")
            ).scalar_one()
    finally:
        engine.dispose()

    assert count == 2
