"""CP18: the nightly scrub drops the photo FILES of expired pages; the rows stay.

A photo is the only heavy thing a page holds (up to 1.5 MB, six per
invitation), and it is personal. Once a page has expired nobody can see it,
so its bytes go at 03:30 with the rest of the page's text; the row -- size,
dimensions, when -- stays, so the shop's counts and the admin panel's disk
figures stay true. A live page's photos are never touched.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from PIL import Image
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import bound_session_factory
from tests.share_pages_harness import every_customer_has_the_gift
from tests.test_share_pages_service import invite, make_customer, make_shop

from gulbot.services import share_page_photos, share_pages

pytestmark = pytest.mark.infra


@pytest.fixture(autouse=True)
def _gift(monkeypatch: pytest.MonkeyPatch) -> None:
    every_customer_has_the_gift(monkeypatch)


def a_jpeg(shade: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (60, 40), (shade, 100, 150)).save(out, "JPEG")
    return out.getvalue()


async def page_with_photos(db: AsyncConnection, shop: int, user: int, n: int) -> Any:
    customer = await make_customer(db, shop, user)
    async with bound_session_factory(db)() as session:
        page = await share_pages.create_page(
            session, shop_id=shop, customer_id=customer, bot_username="b", draft=invite()
        )
        await session.flush()
        for i in range(n):
            await share_page_photos.store_photo(
                session, shop_id=shop, customer_id=customer, page_id=page.id, raw=a_jpeg(40 * i)
            )
        await session.commit()
    return page


async def photos(db: AsyncConnection, page_id: int) -> list[tuple[Any, ...]]:
    return [
        tuple(r)
        for r in (
            await db.execute(
                text(
                    "SELECT data IS NOT NULL, purged_at IS NOT NULL, size_bytes > 0 "
                    "FROM share_page_photos WHERE page_id = :p ORDER BY position"
                ),
                {"p": page_id},
            )
        ).all()
    ]


async def test_the_scrub_drops_an_expired_pages_photo_files_and_keeps_the_rows(
    db: AsyncConnection,
) -> None:
    shop = await make_shop(db, "Purge")
    expired = await page_with_photos(db, shop, 990_601, 2)
    live = await page_with_photos(db, shop, 990_602, 1)
    await db.execute(
        text("UPDATE share_pages SET expires_at = now() - interval '1 day' WHERE id = :p"),
        {"p": expired.id},
    )
    async with bound_session_factory(db)() as session:
        scrubbed = await share_pages.scrub_expired(session, now=datetime.now(UTC))
        await session.commit()
    assert scrubbed == 1
    assert await photos(db, expired.id) == [(False, True, True), (False, True, True)]
    assert await photos(db, live.id) == [(True, False, True)], "a live page's photo was touched"


async def test_purging_reports_the_bytes_freed_and_runs_once(db: AsyncConnection) -> None:
    shop = await make_shop(db, "Purge bytes")
    page = await page_with_photos(db, shop, 990_603, 2)
    stored = await db.scalar(
        text("SELECT sum(size_bytes) FROM share_page_photos WHERE page_id = :p"), {"p": page.id}
    )
    async with bound_session_factory(db)() as session:
        freed = await share_pages.purge_photos(session, [page.id], now=datetime.now(UTC))
        again = await share_pages.purge_photos(
            session, [page.id], now=datetime.now(UTC) + timedelta(days=1)
        )
        await session.commit()
    assert freed == stored and again == 0


async def test_the_database_holds_a_photo_purged_or_not_never_half(db: AsyncConnection) -> None:
    shop = await make_shop(db, "Purge check")
    page = await page_with_photos(db, shop, 990_604, 1)
    for statement in (
        "UPDATE share_page_photos SET data = NULL WHERE page_id = :p",
        "UPDATE share_page_photos SET purged_at = now() WHERE page_id = :p",
    ):
        try:
            async with db.begin_nested():
                await db.execute(text(statement), {"p": page.id})
        except Exception as error:  # noqa: BLE001 - the constraint's name is the assertion
            message = str(error)
        else:
            message = ""
        assert "ck_share_page_photos_purged_has_no_data" in message, (statement, message)
