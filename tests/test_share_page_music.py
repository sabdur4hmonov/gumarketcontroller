"""A page's music (CP17).

OFF by default, and only ever one of our own tracks (their license is in
static/music/LICENSE.md); the page loads the player only when a track is set,
and tests/test_page_js.py proves the player stays silent until the visitor
taps.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
from tests.bot_harness import bound_session_factory
from tests.share_pages_harness import ShopBot
from tests.test_share_page_seal import app_for, konvert, refusal, soon
from tests.test_share_pages_service import invite, make_customer, make_shop, yesno

from gulbot.bot.callbacks import EditFieldCB, MusicCB
from gulbot.i18n.catalog import CATALOG
from gulbot.models.share_page import MUSIC_TRACKS
from gulbot.services import share_pages
from gulbot.web.render import STATIC

pytestmark = pytest.mark.infra


@pytest.fixture
async def session(db: AsyncConnection) -> AsyncSession:
    return bound_session_factory(db)()


def test_every_track_is_shipped_and_licensed() -> None:
    player = (STATIC / "js" / "music.js").read_text(encoding="utf-8")
    license_text = (STATIC / "music" / "LICENSE.md").read_text(encoding="utf-8")
    for track in MUSIC_TRACKS:
        assert re.search(rf"^\s+{track}: \{{", player, re.MULTILINE), track
        assert f"| `{track}`" in license_text, track
    assert "CC0" in license_text and "autoplay" not in player.replace("Never autoplay", "")


async def test_music_is_off_by_default_and_only_our_tracks(
    db: AsyncConnection, session: AsyncSession
) -> None:
    page, shop, customer = await konvert(session, db)
    assert page.music is None

    async def edit(**changes: object) -> Any:
        return await share_pages.update_page(
            session, shop_id=shop, customer_id=customer, page_id=page.id, changes=changes
        )

    assert (await edit(music="oqshom")).music == "oqshom"
    assert await refusal(edit(music="https://example.com/song.mp3")) == "invalid"
    assert (await edit(music=None)).music is None
    with pytest.raises(Exception, match="ck_share_pages_music_known"):
        async with db.begin_nested():
            await db.execute(
                text("UPDATE share_pages SET music = 'somesong' WHERE id = :i"), {"i": page.id}
            )


async def test_the_page_loads_the_player_only_with_a_track(
    db: AsyncConnection, session: AsyncSession
) -> None:
    quiet, _, _ = await konvert(session, db)
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 773)
    sung = await share_pages.create_page(
        session, shop_id=shop, customer_id=customer, bot_username="b", draft=yesno()
    )
    await share_pages.update_page(
        session, shop_id=shop, customer_id=customer, page_id=sung.id, changes={"music": "bahor"}
    )
    await session.commit()
    async with TestClient(TestServer(app_for(db))) as client:
        silent = await (await client.get(f"/p/{quiet.token}")).text()
        playing = await (await client.get(f"/p/{sung.token}")).text()
    assert "music.js" not in silent and 'id="music"' not in silent
    assert "/static/js/music.js" in playing or "js/music.js" in playing
    assert 'id="music" data-track="bahor" aria-pressed="false" hidden' in playing


async def test_music_is_picked_in_the_bot_and_not_by_another_shop(db: AsyncConnection) -> None:
    a = ShopBot(db, await make_shop(db, "A"), bot_id=770_002, username="a_bot")
    b = ShopBot(db, await make_shop(db, "B"), bot_id=770_003, username="b_bot")
    await a.say(CATALOG["btn.menu.help"]["uz"], user=774)
    customer = await db.scalar(
        text("SELECT id FROM customers WHERE shop_id = :s AND telegram_user_id = 774"),
        {"s": a.shop_id},
    )
    session = bound_session_factory(db)()
    page = await share_pages.create_page(
        session,
        shop_id=a.shop_id,
        customer_id=int(customer),
        bot_username="a_bot",
        draft=invite(event_date=soon()),
    )
    await session.commit()

    async def music() -> Any:
        return await db.scalar(text("SELECT music FROM share_pages WHERE id = :i"), {"i": page.id})

    await a.tap(MusicCB(track="tantana").pack(), user=774)  # the picker is not open
    assert await music() is None
    await a.tap(EditFieldCB(page_id=page.id, field="music").pack(), user=774)
    await a.tap(MusicCB(track="tantana").pack(), user=774)
    assert await music() == "tantana"
    await b.say(CATALOG["btn.menu.help"]["uz"], user=774)
    await b.tap(EditFieldCB(page_id=page.id, field="music").pack(), user=774)
    await b.tap(MusicCB(track="none").pack(), user=774)
    assert await music() == "tantana"
    await a.tap(EditFieldCB(page_id=page.id, field="music").pack(), user=774)
    await a.tap(MusicCB(track="none").pack(), user=774)
    assert await music() is None
