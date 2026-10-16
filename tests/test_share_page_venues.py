"""A taklifnoma's places (CP27.1): share_page_venues through the shared service.

- Map links: https to Google, Yandex or 2GIS only, never fetched; a point is
  read from the link itself when it carries one.
- Places: up to VENUES_MAX, a known kind, a name; venue 1 fills the page's own
  `venue` and `location`, so every design and the bot keep working.
- Scrubbed with the page (delete, expiry); a place can never hang under
  another shop's page (composite FK).
- The public page lists the places; a page without any renders as before.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import pytest
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
from tests.bot_harness import bound_session_factory
from tests.test_share_pages_service import NOW, create, invite, make_customer, make_shop

from gulbot.models.share_page import VENUES_MAX, SharePageVenue
from gulbot.services import share_pages
from gulbot.services.share_pages import InvalidDraft, VenueDraft, clean_map_url, point_of_map_url
from gulbot.web.app import build_app

pytestmark = pytest.mark.infra

HALL = VenueDraft(
    kind="toyxona",
    name="Navro‘z to‘yxonasi",
    address="Toshkent, Chilonzor 5",
    map_url="https://www.google.com/maps/place/X/@41.311081,69.240562,17z",
    starts_at=time(18, 0),
)
HOME = VenueDraft(kind="uy", name="Kelin tomon", map_url="https://maps.app.goo.gl/abc123")


@pytest.fixture
async def session(db: AsyncConnection) -> AsyncSession:
    return bound_session_factory(db)()


@pytest.mark.parametrize(
    "url",
    [
        "https://maps.app.goo.gl/abc123",
        "https://www.google.com/maps/place/X/@41.3,69.2,17z",
        "https://goo.gl/maps/xyz",
        "https://yandex.uz/maps/?ll=69.24,41.31&z=16",
        "https://maps.yandex.ru/-/CDabc",
        "https://2gis.uz/tashkent/firm/123?m=69.24,41.31/16",
        "https://go.2gis.com/abc",
        "HTTPS://MAPS.APP.GOO.GL/abc123",
    ],
)
def test_a_map_link_from_a_map_service_is_kept(url: str) -> None:
    cleaned = clean_map_url(url)
    assert cleaned is not None and cleaned.startswith("https://")


@pytest.mark.parametrize(
    "url",
    [
        "http://maps.app.goo.gl/abc",  # not https
        "javascript:alert(1)",
        "https://evil.example/maps",
        "https://www.google.com/search?q=x",  # google, but not maps
        "https://yandex.uz/search/?text=x",
        "https://user:pw@maps.app.goo.gl/abc",
        "https://maps.app.goo.gl:8443/abc",
        "https://maps.app.goo.gl/a b",
        "https://maps.google.com.evil.example/x",
        "https://maps.app.goo.gl/" + "a" * 300,
        "//maps.app.goo.gl/abc",
    ],
)
def test_anything_else_is_refused(url: str) -> None:
    with pytest.raises(InvalidDraft):
        clean_map_url(url)


def test_a_fragment_is_dropped_and_empty_is_none() -> None:
    assert clean_map_url("https://maps.app.goo.gl/abc#frag") == "https://maps.app.goo.gl/abc"
    assert clean_map_url("   ") is None and clean_map_url(None) is None


@pytest.mark.parametrize(
    ("url", "point"),
    [
        (
            "https://www.google.com/maps/place/X/@41.311081,69.240562,17z",
            ("41.311081", "69.240562"),
        ),
        ("https://www.google.com/maps/search/?api=1&query=41.3,69.2", ("41.300000", "69.200000")),
        ("https://yandex.uz/maps/?ll=69.240562,41.311081&z=16", ("41.311081", "69.240562")),
        ("https://2gis.uz/tashkent?m=69.24,41.31/16", ("41.310000", "69.240000")),
        ("https://maps.app.goo.gl/abc123", None),
        ("https://www.google.com/maps/place/X/@99.0,69.2,17z", None),
    ],
)
def test_a_point_is_read_from_the_link_itself(url: str, point: tuple[str, str] | None) -> None:
    found = point_of_map_url(url)
    expected = (Decimal(point[0]), Decimal(point[1])) if point else None
    assert found == expected


async def test_places_are_stored_in_order_and_fill_the_pages_own_venue(
    db: AsyncConnection, session: AsyncSession
) -> None:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 901)
    page = await create(
        session, shop, customer, invite(venue="", location=None, venues=(HALL, HOME))
    )
    rows = await share_pages.venues_of(session, page_id=page.id)
    assert [(r.position, r.kind, r.name) for r in rows] == [
        (1, "toyxona", "Navro‘z to‘yxonasi"),
        (2, "uy", "Kelin tomon"),
    ]
    assert rows[0].starts_at == time(18, 0) and rows[1].map_url == "https://maps.app.goo.gl/abc123"
    assert page.venue == "Navro‘z to‘yxonasi, Toshkent, Chilonzor 5"
    assert (page.location_lat, page.location_lon) == (Decimal("41.311081"), Decimal("69.240562"))


async def test_a_typed_venue_and_location_win_over_place_one(
    db: AsyncConnection, session: AsyncSession
) -> None:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 902)
    page = await create(session, shop, customer, invite(venues=(HOME,)))
    assert page.venue == "Toshkent, Navro'z to'yxonasi"
    assert page.location_lat == Decimal("41.311081")


@pytest.mark.parametrize(
    "venues",
    [
        tuple(VenueDraft(kind="kafe", name=f"Kafe {n}") for n in range(VENUES_MAX + 1)),
        (VenueDraft(kind="saroy", name="Saroy"),),
        (VenueDraft(kind="kafe", name="   "),),
        (VenueDraft(kind="kafe", name="Kafe", map_url="https://evil.example/maps"),),
    ],
)
async def test_places_the_form_could_not_produce_are_refused(
    db: AsyncConnection, session: AsyncSession, venues: tuple[VenueDraft, ...]
) -> None:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 903)
    # The service refuses it, not the database's CHECK behind it.
    with pytest.raises(Exception) as refused:  # noqa: B017
        async with session.begin_nested():
            await create(session, shop, customer, invite(venues=venues))
    assert isinstance(refused.value, InvalidDraft), repr(refused.value)
    assert await session.scalar(select(func.count()).select_from(SharePageVenue)) == 0


async def test_an_invitation_with_no_venue_at_all_is_refused(
    db: AsyncConnection, session: AsyncSession
) -> None:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 904)
    with pytest.raises(InvalidDraft):
        await create(session, shop, customer, invite(venue="", venues=()))


async def test_places_go_with_the_page_on_delete_and_on_expiry(
    db: AsyncConnection, session: AsyncSession
) -> None:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 905)
    deleted = await create(session, shop, customer, invite(venues=(HALL,)))
    expiring = await create(session, shop, customer, invite(venues=(HOME,)))
    assert await share_pages.delete_page(
        session, shop_id=shop, customer_id=customer, page_id=deleted.id, now=NOW
    )
    assert await share_pages.venues_of(session, page_id=deleted.id) == []
    await share_pages.scrub_expired(session, now=expiring.expires_at + timedelta(seconds=1))
    assert await share_pages.venues_of(session, page_id=expiring.id) == []


async def test_a_place_cannot_hang_under_another_shops_page(
    db: AsyncConnection, session: AsyncSession
) -> None:
    a, b = await make_shop(db, "A"), await make_shop(db, "B")
    page = await create(session, a, await make_customer(db, a, 906), invite())
    await session.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(
                text(
                    "INSERT INTO share_page_venues (shop_id, page_id, position, kind, name) "
                    "VALUES (:b, :p, 1, 'kafe', 'x')"
                ),
                {"b": b, "p": page.id},
            )


async def test_the_public_page_lists_the_places(db: AsyncConnection, session: AsyncSession) -> None:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 907)
    listed = await create(
        session,
        shop,
        customer,
        invite(venue="", location=None, venues=(HALL, HOME)),
        now=datetime.now(UTC),
    )
    plain = await create(session, shop, customer, invite(), now=datetime.now(UTC))
    await session.commit()
    app = build_app(
        session_factory=bound_session_factory(db),
        notify=lambda page_id, delay: None,
        public_base_url="http://127.0.0.1:8088",
    )
    async with TestClient(TestServer(app)) as client:
        with_places = await (await client.get(f"/p/{listed.token}")).text()
        without = await (await client.get(f"/p/{plain.token}")).text()
    assert 'class="venue-list"' in with_places
    assert "Kelin tomon" in with_places and "yxona · 18:00" in with_places
    assert 'href="https://maps.app.goo.gl/abc123"' in with_places
    assert 'class="venue-list"' not in without and "Navro" in without
