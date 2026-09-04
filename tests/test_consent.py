"""Consent is append-only and versioned.

The version exists so that a later rewording cannot silently rewrite what past
customers agreed to. The hash test below is what makes that real: edit the text
without bumping the version and the build fails.
"""

from __future__ import annotations

import hashlib

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker
from tests.bot_harness import bound_session_factory
from tests.test_tenancy import _make_customer, _make_shop

from gulbot.i18n.catalog import CATALOG
from gulbot.models.consent import STORE_DATES_TEXT_VERSION, ConsentSource, ConsentType
from gulbot.services.occasions import create_occasion, record_store_dates_consent
from gulbot.services.recipients import create_recipient

# Recomputed from the catalog. Bump BOTH this and STORE_DATES_TEXT_VERSION when
# the wording changes -- that is the point.
CONSENT_TEXT_FINGERPRINT = "ec81442eceb0cc17"


def _fingerprint() -> str:
    entry = CATALOG["occasions.consent"]
    joined = "\x1f".join(f"{lang}={entry[lang]}" for lang in sorted(entry))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def test_consent_text_matches_its_recorded_version() -> None:
    assert _fingerprint() == CONSENT_TEXT_FINGERPRINT, (
        "The consent wording changed. Bump STORE_DATES_TEXT_VERSION and update "
        f"CONSENT_TEXT_FINGERPRINT to {_fingerprint()!r}, so existing rows keep "
        "meaning what was actually on screen when those customers agreed."
    )


def test_version_is_a_stable_identifier() -> None:
    assert STORE_DATES_TEXT_VERSION == "store_dates.v2"


def test_consent_text_exists_in_both_languages() -> None:
    entry = CATALOG["occasions.consent"]
    assert entry["uz"].strip() and entry["ru"].strip()


@pytest_asyncio.fixture
async def sessions(db: AsyncConnection) -> async_sessionmaker:
    return bound_session_factory(db)


@pytest.mark.infra
async def test_consent_is_written_once_with_the_version(
    db: AsyncConnection, sessions: async_sessionmaker
) -> None:
    shop = await _make_shop(db, "S")
    customer = await _make_customer(db, shop, tg_id=1)

    async with sessions() as session:
        written = await record_store_dates_consent(session, shop_id=shop, customer_id=customer)
        await session.commit()
    assert written is True

    row = (
        await db.execute(
            text(
                "SELECT type, granted, source, text_version "
                "FROM consent_events WHERE customer_id = :c"
            ),
            {"c": customer},
        )
    ).one()
    assert row.type == ConsentType.STORE_DATES.value
    assert row.granted is True
    assert row.source == ConsentSource.FIRST_OCCASION.value
    assert row.text_version == STORE_DATES_TEXT_VERSION


@pytest.mark.infra
async def test_second_occasion_does_not_write_a_second_consent_row(
    db: AsyncConnection, sessions: async_sessionmaker
) -> None:
    shop = await _make_shop(db, "S")
    customer = await _make_customer(db, shop, tg_id=1)

    async with sessions() as session:
        assert await record_store_dates_consent(session, shop_id=shop, customer_id=customer)
        assert not await record_store_dates_consent(session, shop_id=shop, customer_id=customer)
        await session.commit()

    count = (
        await db.execute(
            text("SELECT count(*) FROM consent_events WHERE customer_id = :c"),
            {"c": customer},
        )
    ).scalar_one()
    assert count == 1


@pytest.mark.infra
async def test_consent_row_is_written_alongside_the_first_occasion(
    db: AsyncConnection, sessions: async_sessionmaker
) -> None:
    shop = await _make_shop(db, "S")
    customer = await _make_customer(db, shop, tg_id=1)

    async with sessions() as session:
        recipient = await create_recipient(
            session, shop_id=shop, customer_id=customer, label="Onam", type_="mother"
        )
        await create_occasion(
            session,
            shop_id=shop,
            customer_id=customer,
            recipient_id=recipient.id,
            type_="mother",
            kind="birthday",
            label="Onam",
            month=3,
            day=8,
            year=None,
        )
        await record_store_dates_consent(session, shop_id=shop, customer_id=customer)
        await session.commit()

    occasions = (
        await db.execute(
            text("SELECT count(*) FROM occasions WHERE customer_id = :c"), {"c": customer}
        )
    ).scalar_one()
    consents = (
        await db.execute(
            text("SELECT count(*) FROM consent_events WHERE customer_id = :c"),
            {"c": customer},
        )
    ).scalar_one()
    assert (occasions, consents) == (1, 1)


@pytest.mark.infra
async def test_consent_cannot_reference_another_shops_customer(
    db: AsyncConnection,
) -> None:
    """Composite FK again: consent rows are tenant-scoped too."""
    import pytest as _pytest
    from sqlalchemy.exc import IntegrityError

    shop_a = await _make_shop(db, "A")
    shop_b = await _make_shop(db, "B")
    customer_a = await _make_customer(db, shop_a, tg_id=1)

    with _pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await db.execute(
                text(
                    "INSERT INTO consent_events "
                    "(shop_id, customer_id, type, granted, source, text_version) "
                    "VALUES (:s, :c, 'store_dates', true, 'first_occasion', 'v1')"
                ),
                {"s": shop_b, "c": customer_a},
            )
    assert "fk_consent_events_customer_id_shop_id_customers" in str(excinfo.value)
