"""The catalogue schema, proven at the database layer.

Every assertion goes through raw SQL and names the constraint it expects to
fire. Per CP1: an ORM-level check proves only that our Python agreed with
itself, and these constraints exist to hold against psql and against CP8's
indexer, neither of which goes through the ORM.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker
from tests.bot_harness import bound_session_factory
from tests.conftest import alembic_config_for, create_database, drop_database
from tests.test_tenancy import _make_shop

from gulbot.catalog.alias_fixture import ALIASES, FIXTURE_VERSION
from gulbot.services.hashtag_aliases import (
    normalized_pairs,
    resolve_alias,
    seed_hashtag_aliases,
)

ROUNDTRIP_DB = "gulbot_catalog_roundtrip"
CATALOG_TABLES = {"products", "product_hashtags", "hashtag_aliases"}


@pytest_asyncio.fixture
async def sessions(db: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    return bound_session_factory(db)


async def _make_product(
    db: AsyncConnection,
    shop: int,
    *,
    name: str = "Atirgul buketi",
    source: str = "channel",
    message_id: int | None = 100,
    media_group_id: str | None = None,
    price: int | None = None,
    confidence: str = "none",
) -> int:
    result = await db.execute(
        text(
            "INSERT INTO products "
            "(shop_id, name, telegram_file_id, source, channel_message_id, "
            " media_group_id, price_uzs, price_confidence) "
            "VALUES (:s, :n, 'file123', :src, :mid, :mg, :p, :pc) RETURNING id"
        ),
        {
            "s": shop,
            "n": name,
            "src": source,
            "mid": message_id,
            "mg": media_group_id,
            "p": price,
            "pc": confidence,
        },
    )
    return int(result.scalar_one())


# --- tenancy ---------------------------------------------------------------


@pytest.mark.infra
async def test_a_hashtag_cannot_reference_another_shops_product(
    db: AsyncConnection,
) -> None:
    """The composite FK that UNIQUE(products.id, shop_id) exists to support."""
    shop_a = await _make_shop(db, "A")
    shop_b = await _make_shop(db, "B")
    product = await _make_product(db, shop_a)

    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await db.execute(
                text(
                    "INSERT INTO product_hashtags (shop_id, product_id, hashtag_normalized) "
                    "VALUES (:s, :p, 'atirgul')"
                ),
                {"s": shop_b, "p": product},
            )
    assert "fk_product_hashtags_product_id_shop_id_products" in str(excinfo.value)


@pytest.mark.infra
async def test_a_hashtag_for_its_own_shop_is_accepted(db: AsyncConnection) -> None:
    shop = await _make_shop(db, "A")
    product = await _make_product(db, shop)
    await db.execute(
        text(
            "INSERT INTO product_hashtags (shop_id, product_id, hashtag_normalized) "
            "VALUES (:s, :p, 'atirgul')"
        ),
        {"s": shop, "p": product},
    )


@pytest.mark.infra
async def test_deleting_a_product_takes_its_hashtags_with_it(
    db: AsyncConnection,
) -> None:
    shop = await _make_shop(db, "A")
    product = await _make_product(db, shop)
    await db.execute(
        text(
            "INSERT INTO product_hashtags (shop_id, product_id, hashtag_normalized) "
            "VALUES (:s, :p, 'atirgul')"
        ),
        {"s": shop, "p": product},
    )
    await db.execute(text("DELETE FROM products WHERE id = :p"), {"p": product})
    remaining = (
        await db.execute(
            text("SELECT count(*) FROM product_hashtags WHERE product_id = :p"),
            {"p": product},
        )
    ).scalar_one()
    assert remaining == 0


# --- redelivery idempotency ------------------------------------------------


@pytest.mark.infra
async def test_the_same_channel_message_cannot_be_indexed_twice(
    db: AsyncConnection,
) -> None:
    """Telegram may redeliver a channel_post. The second one must conflict."""
    shop = await _make_shop(db, "A")
    await _make_product(db, shop, message_id=555)
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await _make_product(db, shop, message_id=555)
    assert "uq_products_shop_id_channel_message_id" in str(excinfo.value)


@pytest.mark.infra
async def test_two_shops_may_hold_the_same_message_id(db: AsyncConnection) -> None:
    """Message ids are per channel, so uniqueness has to be per shop."""
    shop_a = await _make_shop(db, "A")
    shop_b = await _make_shop(db, "B")
    await _make_product(db, shop_a, message_id=555)
    await _make_product(db, shop_b, message_id=555)


@pytest.mark.infra
async def test_manual_products_may_all_have_no_message_id(db: AsyncConnection) -> None:
    """NULLs do not collide, so a shop can hold many manual rows."""
    shop = await _make_shop(db, "A")
    for name in ("A", "B", "C"):
        await _make_product(db, shop, name=name, source="manual", message_id=None)


# --- the album anchor CP8 will need ----------------------------------------


@pytest.mark.infra
async def test_one_product_per_album_per_shop(db: AsyncConnection) -> None:
    """Five photos share a media_group_id and must collapse to ONE product.

    Nothing writes this yet; the constraint exists so CP8's merge has an anchor
    to conflict against rather than a race to lose.
    """
    shop = await _make_shop(db, "A")
    await _make_product(db, shop, message_id=1, media_group_id="album-1")
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await _make_product(db, shop, message_id=2, media_group_id="album-1")
    assert "uq_products_shop_media_group" in str(excinfo.value)


@pytest.mark.infra
async def test_products_without_an_album_do_not_collide(db: AsyncConnection) -> None:
    """The index is partial: a NULL media_group_id is not an album."""
    shop = await _make_shop(db, "A")
    for i in range(1, 4):
        await _make_product(db, shop, message_id=i, media_group_id=None)


@pytest.mark.infra
async def test_two_shops_may_use_the_same_album_id(db: AsyncConnection) -> None:
    shop_a = await _make_shop(db, "A")
    shop_b = await _make_shop(db, "B")
    await _make_product(db, shop_a, message_id=1, media_group_id="album-1")
    await _make_product(db, shop_b, message_id=1, media_group_id="album-1")


# --- price and confidence must agree ---------------------------------------


@pytest.mark.infra
@pytest.mark.parametrize(
    ("price", "confidence"),
    [(150_000, "high"), (150_000, "medium"), (None, "none")],
)
async def test_coherent_price_and_confidence_pairs_are_accepted(
    db: AsyncConnection, price: int | None, confidence: str
) -> None:
    shop = await _make_shop(db, "A")
    await _make_product(db, shop, price=price, confidence=confidence)


@pytest.mark.infra
@pytest.mark.parametrize(
    ("price", "confidence"),
    [(None, "high"), (None, "medium"), (150_000, "none")],
)
async def test_incoherent_price_and_confidence_pairs_are_refused(
    db: AsyncConnection, price: int | None, confidence: str
) -> None:
    """ "High confidence, no price" is not a state that means anything."""
    shop = await _make_shop(db, "A")
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await _make_product(db, shop, price=price, confidence=confidence)
    assert "ck_products_price_matches_confidence" in str(excinfo.value)


@pytest.mark.infra
async def test_an_unknown_confidence_is_refused(db: AsyncConnection) -> None:
    shop = await _make_shop(db, "A")
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await _make_product(db, shop, price=1000, confidence="probably")
    assert "ck_products_price_confidence_known" in str(excinfo.value)


@pytest.mark.infra
async def test_an_unknown_source_is_refused(db: AsyncConnection) -> None:
    shop = await _make_shop(db, "A")
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            # message_id must be NULL here, or the row also violates
            # only_channel_rows_have_a_message_id and Postgres reports that
            # one instead -- which would leave this test asserting nothing
            # about the source CHECK.
            await _make_product(db, shop, source="scraped", message_id=None)
    assert "ck_products_source_known" in str(excinfo.value)


@pytest.mark.infra
async def test_a_manual_row_may_not_claim_a_channel_message(
    db: AsyncConnection,
) -> None:
    shop = await _make_shop(db, "A")
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await _make_product(db, shop, source="manual", message_id=99)
    assert "ck_products_only_channel_rows_have_a_message_id" in str(excinfo.value)


@pytest.mark.infra
async def test_a_zero_price_is_refused(db: AsyncConnection) -> None:
    shop = await _make_shop(db, "A")
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await _make_product(db, shop, price=0, confidence="high")
    assert "ck_products_price_positive" in str(excinfo.value)


# --- hashtags and aliases --------------------------------------------------


@pytest.mark.infra
async def test_a_product_cannot_carry_the_same_tag_twice(db: AsyncConnection) -> None:
    shop = await _make_shop(db, "A")
    product = await _make_product(db, shop)
    sql = text(
        "INSERT INTO product_hashtags (shop_id, product_id, hashtag_normalized) "
        "VALUES (:s, :p, 'atirgul')"
    )
    await db.execute(sql, {"s": shop, "p": product})
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await db.execute(sql, {"s": shop, "p": product})
    assert "uq_product_hashtags_product_id_hashtag_normalized" in str(excinfo.value)


@pytest.mark.infra
async def test_a_blank_hashtag_is_refused(db: AsyncConnection) -> None:
    """normalize_hashtag returns "" for a numeric tag; those must be dropped."""
    shop = await _make_shop(db, "A")
    product = await _make_product(db, shop)
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await db.execute(
                text(
                    "INSERT INTO product_hashtags (shop_id, product_id, hashtag_normalized) "
                    "VALUES (:s, :p, '')"
                ),
                {"s": shop, "p": product},
            )
    assert "ck_product_hashtags_hashtag_not_blank" in str(excinfo.value)


@pytest.mark.infra
async def test_an_alias_pointing_at_itself_is_refused(db: AsyncConnection) -> None:
    shop = await _make_shop(db, "A")
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await db.execute(
                text(
                    "INSERT INTO hashtag_aliases (shop_id, alias_normalized, canonical_hashtag) "
                    "VALUES (:s, 'roza', 'roza')"
                ),
                {"s": shop},
            )
    assert "ck_hashtag_aliases_alias_differs_from_canonical" in str(excinfo.value)


@pytest.mark.infra
async def test_one_alias_per_shop(db: AsyncConnection) -> None:
    shop = await _make_shop(db, "A")
    sql = text(
        "INSERT INTO hashtag_aliases (shop_id, alias_normalized, canonical_hashtag) "
        "VALUES (:s, 'roza', 'atirgul')"
    )
    await db.execute(sql, {"s": shop})
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await db.execute(sql, {"s": shop})
    assert "uq_hashtag_aliases_shop_id_alias_normalized" in str(excinfo.value)


# --- the seed --------------------------------------------------------------


@pytest.mark.infra
async def test_seeding_twice_changes_nothing_the_second_time(
    db: AsyncConnection, sessions: async_sessionmaker[AsyncSession]
) -> None:
    shop = await _make_shop(db, "A")

    async with sessions() as session:
        first = await seed_hashtag_aliases(session, shop_id=shop)
        await session.commit()
    async with sessions() as session:
        second = await seed_hashtag_aliases(session, shop_id=shop)
        await session.commit()

    assert first.inserted == len(normalized_pairs())
    assert (second.inserted, second.updated) == (0, 0)
    assert second.unchanged == first.inserted

    total = (
        await db.execute(
            text("SELECT count(*) FROM hashtag_aliases WHERE shop_id = :s"), {"s": shop}
        )
    ).scalar_one()
    assert total == first.inserted


@pytest.mark.infra
async def test_seeding_three_times_creates_no_duplicates(
    db: AsyncConnection, sessions: async_sessionmaker[AsyncSession]
) -> None:
    shop = await _make_shop(db, "A")
    for _ in range(3):
        async with sessions() as session:
            await seed_hashtag_aliases(session, shop_id=shop)
            await session.commit()

    duplicates = (
        await db.execute(
            text(
                "SELECT count(*) FROM (SELECT shop_id, alias_normalized FROM hashtag_aliases "
                "WHERE shop_id = :s GROUP BY 1, 2 HAVING count(*) > 1) d"
            ),
            {"s": shop},
        )
    ).scalar_one()
    assert duplicates == 0


@pytest.mark.infra
async def test_the_seed_does_not_overrule_a_hand_edited_row(
    db: AsyncConnection, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """A row with no fixture_version was added by a human. Leave it alone."""
    shop = await _make_shop(db, "A")
    await db.execute(
        text(
            "INSERT INTO hashtag_aliases (shop_id, alias_normalized, canonical_hashtag) "
            "VALUES (:s, 'roza', 'something_the_shop_chose')"
        ),
        {"s": shop},
    )

    async with sessions() as session:
        await seed_hashtag_aliases(session, shop_id=shop)
        await session.commit()

    kept = (
        await db.execute(
            text(
                "SELECT canonical_hashtag FROM hashtag_aliases "
                "WHERE shop_id = :s AND alias_normalized = 'roza'"
            ),
            {"s": shop},
        )
    ).scalar_one()
    assert kept == "something_the_shop_chose"


@pytest.mark.infra
async def test_the_seed_records_which_fixture_version_wrote_each_row(
    db: AsyncConnection, sessions: async_sessionmaker[AsyncSession]
) -> None:
    shop = await _make_shop(db, "A")
    async with sessions() as session:
        await seed_hashtag_aliases(session, shop_id=shop)
        await session.commit()
    versions = (
        await db.execute(
            text("SELECT DISTINCT fixture_version FROM hashtag_aliases WHERE shop_id = :s"),
            {"s": shop},
        )
    ).scalars()
    assert set(versions) == {FIXTURE_VERSION}


@pytest.mark.infra
async def test_aliases_resolve_across_scripts(
    db: AsyncConnection, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """The whole point of the table: роза and rose reach the same tag."""
    shop = await _make_shop(db, "A")
    async with sessions() as session:
        await seed_hashtag_aliases(session, shop_id=shop)
        await session.commit()

    async with sessions() as session:
        for written in ("роза", "Rose", "#ROZA", "roza"):
            assert await resolve_alias(session, shop_id=shop, tag=written) == "atirgul"


@pytest.mark.infra
async def test_an_unaliased_tag_resolves_to_itself(
    db: AsyncConnection, sessions: async_sessionmaker[AsyncSession]
) -> None:
    shop = await _make_shop(db, "A")
    async with sessions() as session:
        assert await resolve_alias(session, shop_id=shop, tag="#Nargis") == "nargis"


def test_the_fixture_holds_roughly_thirty_synonyms() -> None:
    assert len(ALIASES) >= 30, f"only {len(ALIASES)} aliases in the fixture"


def test_every_usable_fixture_pair_survives_normalisation() -> None:
    """Self-referential pairs are dropped, not crashed on.

    "8 mart" normalises to "8mart", which is also its canonical form -- that
    pair would violate the alias_differs_from_canonical CHECK, so the seeder
    drops it rather than failing mid-run.
    """
    pairs = normalized_pairs()
    assert pairs
    for alias, canonical in pairs:
        assert alias and canonical
        assert alias != canonical


# --- migration round-trip --------------------------------------------------


@pytest.mark.infra
def test_the_catalog_migration_round_trips(settings) -> None:
    """upgrade -> downgrade -> upgrade, on a throwaway database."""
    drop_database(settings, ROUNDTRIP_DB)
    create_database(settings, ROUNDTRIP_DB)
    url = settings.database_url(database=ROUNDTRIP_DB, driver="psycopg")
    try:
        with alembic_config_for(ROUNDTRIP_DB) as cfg:
            command.upgrade(cfg, "head")
            engine = create_engine(url)
            with engine.connect() as conn:
                tables = set(inspect(conn).get_table_names())
            engine.dispose()
            assert tables >= CATALOG_TABLES, tables

            command.downgrade(cfg, "-1")
            engine = create_engine(url)
            with engine.connect() as conn:
                tables = set(inspect(conn).get_table_names())
            engine.dispose()
            assert not (CATALOG_TABLES & tables), f"downgrade left tables: {tables}"

            command.upgrade(cfg, "head")
            engine = create_engine(url)
            with engine.connect() as conn:
                tables = set(inspect(conn).get_table_names())
            engine.dispose()
            assert tables >= CATALOG_TABLES, tables
    finally:
        drop_database(settings, ROUNDTRIP_DB)
