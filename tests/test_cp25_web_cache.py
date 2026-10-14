"""Cache validators preserve live-page checks; template I/O leaves the loop."""

import threading
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import text
from tests.bot_harness import bound_session_factory
from tests.share_pages_harness import every_customer_has_the_gift
from tests.test_share_page_photos import add, invitation

from gulbot.web import app as web_app
from gulbot.web import render


def app(factory=None):
    return web_app.build_app(
        session_factory=factory,
        notify=lambda *a: None,
        public_base_url="http://127.0.0.1:8088",
    )


async def test_only_current_fingerprinted_assets_are_immutable():
    async with TestClient(TestServer(app())) as client:
        plain = await client.get("/static/css/base.css")
        assert "immutable" not in plain.headers["Cache-Control"]
        assert "must-revalidate" in plain.headers["Cache-Control"]
        tagged = await client.get(render.static_url("css/base.css"))
        assert "immutable" in tagged.headers["Cache-Control"]
        stale = await client.get("/static/css/base.css?v=0000000000")
        assert "immutable" not in stale.headers["Cache-Control"]
        cached = await client.get(
            render.static_url("css/base.css"), headers={"If-None-Match": tagged.headers["ETag"]}
        )
        assert cached.status == 304 and await cached.read() == b""
        missing = await client.get("/static/css/absent.css")
        assert missing.status == 404 and missing.headers["Cache-Control"] == "no-store"


async def test_cold_template_and_static_hash_reads_are_off_loop(monkeypatch):
    thread = threading.get_ident()
    reads = []
    original = Path.read_bytes
    render.environment.cache_clear()
    render._static_version.cache_clear()

    def read(path):
        if render.STATIC in path.parents:
            reads.append(threading.get_ident())
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read)
    async with TestClient(TestServer(app())) as client:
        response = await client.get("/demo/invite/minimal")
        assert response.status == 200
        assert reads and all(t != thread for t in reads), (
            "Cold template asset hashes cannot block the web loop"
        )


async def test_photo_etag_never_bypasses_tenancy_or_hidden_page(db, monkeypatch):
    every_customer_has_the_gift(monkeypatch)
    session = bound_session_factory(db)()
    page, shop, customer = await invitation(session, db)
    image = await add(session, page, shop, customer)
    await session.commit()
    path = f"/p/{page.token}/photo/{image.id}.jpg"
    async with TestClient(TestServer(app(bound_session_factory(db)))) as client:
        original = await client.get(path)
        assert original.status == 200
        assert "ETag" in original.headers, "Photo bytes need a stable validator"
        etag = original.headers["ETag"]
        assert original.headers["Cache-Control"] == "private, max-age=0, must-revalidate"
        for validator in (etag, "W/" + etag, "*"):
            cached = await client.get(path, headers={"If-None-Match": validator})
            assert cached.status == 304 and await cached.read() == b""
        foreign = await client.get(
            "/p/" + "x" * 22 + f"/photo/{image.id}.jpg", headers={"If-None-Match": etag}
        )
        assert foreign.status == 404
        await db.execute(
            text(
                "UPDATE share_pages SET hidden_at=now(), hidden_by=99, "
                "hidden_reason='fixture' WHERE id=:id"
            ),
            {"id": page.id},
        )
        hidden = await client.get(path, headers={"If-None-Match": etag})
        assert hidden.status == 404, "Conditional request still checks moderation/liveness"
