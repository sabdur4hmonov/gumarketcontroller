"""Taklifnoma Studio's way in (CP27.1): services/studio.py against real Postgres.

The /shop pattern (CP20) bound to one customer of one shop:

- a link is minted only for an entitled customer, at most LINK_RATE_LIMIT per
  window, and only its sha256 is stored;
- it expires after LINK_TTL (15 minutes) and is spent once, by compare-and-swap;
- entitlement (`studio.entitled`, the ONE place it is decided) is re-checked at
  minting, at spending and on every request: pausing the shop or removing the
  customer ends the session at once;
- a session is revoked by logout; the audit log cannot be rewritten;
- a link or session naming a customer of another shop is unrepresentable.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
from tests.bot_harness import bound_session_factory
from tests.test_share_pages_service import make_customer, make_shop

from gulbot.models.studio import StudioLink, StudioSession
from gulbot.services import studio

pytestmark = pytest.mark.infra

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


@pytest.fixture
async def session(db: AsyncConnection) -> AsyncSession:
    return bound_session_factory(db)()


async def _mint(session: AsyncSession, shop: int, customer: int, **kw: object) -> str:
    raw = await studio.mint_link(
        session, shop_id=shop, customer_id=customer, bot_username="lola_bot", **kw
    )  # type: ignore[arg-type]
    assert raw is not None
    return raw


async def test_a_link_is_stored_as_its_hash_only(
    db: AsyncConnection, session: AsyncSession
) -> None:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 801)
    raw = await _mint(session, shop, customer, now=NOW)
    row = await session.scalar(select(StudioLink).where(StudioLink.shop_id == shop))
    assert row is not None
    assert row.token_hash == hashlib.sha256(raw.encode()).hexdigest()
    dump = str(
        (await db.execute(text("SELECT * FROM studio_links WHERE shop_id = :s"), {"s": shop})).all()
    )
    assert raw not in dump
    assert row.expires_at - row.created_at == timedelta(minutes=15) == studio.LINK_TTL
    assert studio.TOKEN_RE.match(raw)


async def test_a_link_works_once_and_opens_a_session_for_its_customer(
    db: AsyncConnection, session: AsyncSession
) -> None:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 802)
    raw = await _mint(session, shop, customer, now=NOW)
    opened = await studio.consume_link(session, raw, now=NOW + timedelta(minutes=1))
    assert opened is not None and (opened.shop_id, opened.customer_id) == (shop, customer)
    assert await studio.consume_link(session, raw, now=NOW + timedelta(minutes=2)) is None
    creator = await studio.load_session(session, opened.token, now=NOW + timedelta(minutes=3))
    assert creator is not None and creator.customer_id == customer
    assert creator.bot_username == "lola_bot"
    stored = await session.scalar(select(StudioSession.token_hash))
    assert stored == hashlib.sha256(opened.token.encode()).hexdigest()


async def test_a_link_expires_after_fifteen_minutes(
    db: AsyncConnection, session: AsyncSession
) -> None:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 803)
    raw = await _mint(session, shop, customer, now=NOW)
    assert await studio.consume_link(session, raw, now=NOW + timedelta(minutes=15)) is None
    fresh = await _mint(session, shop, customer, now=NOW)
    assert await studio.consume_link(session, fresh, now=NOW + timedelta(minutes=14)) is not None


async def test_links_are_rate_limited_per_customer(
    db: AsyncConnection, session: AsyncSession
) -> None:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 804)
    for _ in range(studio.LINK_RATE_LIMIT):
        await _mint(session, shop, customer, now=NOW)
    refused = await studio.mint_link(
        session, shop_id=shop, customer_id=customer, bot_username=None, now=NOW
    )
    assert refused is None
    reasons = list(
        await session.scalars(
            text(
                "SELECT reason FROM studio_audit_log WHERE shop_id = :s AND action = 'link_refused'"
            ),
            {"s": shop},
        )
    )
    assert reasons == ["rate"]


async def test_no_link_for_a_customer_of_another_shop(
    db: AsyncConnection, session: AsyncSession
) -> None:
    a, b = await make_shop(db, "A"), await make_shop(db, "B")
    in_b = await make_customer(db, b, 805)
    assert await studio.mint_link(session, shop_id=a, customer_id=in_b, bot_username=None) is None


async def test_entitlement_is_rechecked_at_spending_and_on_every_request(
    db: AsyncConnection, session: AsyncSession
) -> None:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 806)
    raw = await _mint(session, shop, customer, now=NOW)
    opened = await studio.consume_link(session, raw, now=NOW)
    assert opened is not None
    assert await studio.load_session(session, opened.token, now=NOW) is not None

    await db.execute(text("UPDATE shops SET status = 'paused' WHERE id = :s"), {"s": shop})
    assert await studio.load_session(session, opened.token, now=NOW) is None, "paused shop"
    await db.execute(text("UPDATE shops SET status = 'active' WHERE id = :s"), {"s": shop})
    assert await studio.load_session(session, opened.token, now=NOW) is not None

    # A link minted while entitled, spent after the shop was paused.
    later = await _mint(session, shop, customer, now=NOW)
    await db.execute(text("UPDATE shops SET status = 'paused' WHERE id = :s"), {"s": shop})
    assert await studio.consume_link(session, later, now=NOW) is None
    refusals = await session.scalar(
        text(
            "SELECT count(*) FROM studio_audit_log WHERE action = 'login_refused' AND shop_id = :s"
        ),
        {"s": shop},
    )
    assert refusals == 1


async def test_a_session_ends_with_its_customer_and_at_logout(
    db: AsyncConnection, session: AsyncSession
) -> None:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 807)
    opened = await studio.consume_link(session, await _mint(session, shop, customer), now=None)
    assert opened is not None
    creator = await studio.load_session(session, opened.token)
    assert creator is not None
    await studio.end_session(session, creator)
    assert await studio.load_session(session, opened.token) is None

    again = await studio.consume_link(session, await _mint(session, shop, customer))
    assert again is not None
    await db.execute(text("DELETE FROM customers WHERE id = :c"), {"c": customer})
    assert await studio.load_session(session, again.token) is None


async def test_a_session_expires(db: AsyncConnection, session: AsyncSession) -> None:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 808)
    opened = await studio.consume_link(
        session, await _mint(session, shop, customer, now=NOW), now=NOW
    )
    assert opened is not None
    assert await studio.load_session(session, opened.token, now=NOW + studio.SESSION_TTL) is None


def test_csrf_compares_exactly() -> None:
    creator = studio.Creator(shop_id=1, customer_id=1, csrf="abc", session_id=1, bot_username=None)
    assert studio.csrf_ok(creator, "abc")
    assert not studio.csrf_ok(creator, "abd") and not studio.csrf_ok(creator, None)


async def test_the_audit_log_cannot_be_rewritten(
    db: AsyncConnection, session: AsyncSession
) -> None:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 809)
    await _mint(session, shop, customer)
    await session.flush()
    for statement in (
        "UPDATE studio_audit_log SET action = 'x'",
        "DELETE FROM studio_audit_log",
        "TRUNCATE studio_audit_log",
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            async with db.begin_nested():
                await db.execute(text(statement))


async def test_a_link_naming_another_shops_customer_is_unrepresentable(db: AsyncConnection) -> None:
    a, b = await make_shop(db, "A"), await make_shop(db, "B")
    in_b = await make_customer(db, b, 810)
    for table in ("studio_links", "studio_sessions"):
        extra = ", csrf_token" if table == "studio_sessions" else ""
        value = ", 'c'" if table == "studio_sessions" else ""
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                await db.execute(
                    text(
                        f"INSERT INTO {table} "
                        f"(shop_id, customer_id, token_hash, expires_at{extra}) "
                        f"VALUES (:a, :c, :h, now() + interval '1 minute'{value})"
                    ),
                    {"a": a, "c": in_b, "h": "0" * 64},
                )
