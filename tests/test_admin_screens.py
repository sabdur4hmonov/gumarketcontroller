"""CP18: the admin panel's screens and actions, through the real page server.

- Every screen renders for a logged-in admin (found by walking the router).
- Counts before personal data: no customer's phone or name, no owner's full
  phone, and no page token (a page's secret) appears on ANY screen.
- Every action works over HTTP with the session's CSRF token, changes what
  it says, and lands in the audit log.
- The figures are right: orders by status and by source, reminders, the
  gift, disk usage per shop, and the alerts.
"""

from __future__ import annotations

import io
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import bound_session_factory
from tests.share_pages_harness import every_customer_has_the_gift
from tests.test_admin_auth import app_for, logged_in
from tests.test_share_pages_service import invite

from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.services import admin_panel, share_page_photos, share_page_wishes, share_pages

pytestmark = pytest.mark.infra

OWNER_PHONE = "+998901112233"
CUSTOMER_PHONE = "+998935556677"
CUSTOMER_NAME = "Dilfuza Qodirova"


@pytest.fixture
async def world(db: AsyncConnection, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    every_customer_has_the_gift(monkeypatch)
    shop = (
        await db.execute(
            text(
                "INSERT INTO shops (name, working_hours, owner_phone, group_chat_id, channel_id) "
                "VALUES ('Lola Panel', CAST(:wh AS jsonb), :ph, -100700, -100701) RETURNING id"
            ),
            {"wh": json.dumps(DEFAULT_WORKING_HOURS), "ph": OWNER_PHONE},
        )
    ).scalar_one()
    customer = (
        await db.execute(
            text(
                "INSERT INTO customers (shop_id, telegram_user_id, phone) "
                "VALUES (:s, 700700, :ph) RETURNING id"
            ),
            {"s": shop, "ph": CUSTOMER_PHONE},
        )
    ).scalar_one()
    product = (
        await db.execute(
            text(
                "INSERT INTO products (shop_id, name, telegram_file_id, source, "
                " channel_message_id, price_uzs, price_confidence, finalized_at) "
                "VALUES (:s, 'Atirgul', 'f', 'channel', 5, 100000, 'high', now()) RETURNING id"
            ),
            {"s": shop},
        )
    ).scalar_one()
    for token, status, source, age in (
        ("o1", "placed", "reminder", timedelta(hours=2)),  # unanswered for 2 h: an alert
        ("o2", "confirmed", "direct", timedelta(hours=3)),
        ("o3", "rejected", None, timedelta(hours=4)),
    ):
        await db.execute(
            text(
                "INSERT INTO orders (shop_id, customer_id, product_id, product_name_snapshot, "
                " price_uzs_snapshot, telegram_file_id_snapshot, delivery_date, delivery_hour, "
                " delivery_location_text, landmark, recipient_name, status, submit_token, source, "
                " created_at) VALUES (:s, :c, :p, 'Atirgul', 100000, 'f', '2027-03-08', '14:00', "
                " 'Chilonzor', 'eshik', :who, :st, :t, :src, :at)"
            ),
            {
                "s": shop,
                "c": customer,
                "p": product,
                "st": status,
                "t": token,
                "src": source,
                "at": datetime.now(UTC) - age,
                "who": CUSTOMER_NAME,
            },
        )
    jpeg = io.BytesIO()
    Image.new("RGB", (50, 50), (10, 200, 90)).save(jpeg, "JPEG")
    async with bound_session_factory(db)() as session:
        page = await share_pages.create_page(
            session, shop_id=shop, customer_id=customer, bot_username="lola_bot", draft=invite()
        )
        await session.flush()
        await share_pages.update_page(
            session,
            shop_id=shop,
            customer_id=customer,
            page_id=page.id,
            changes={"wishes_enabled": True},
        )
        photo = await share_page_photos.store_photo(
            session, shop_id=shop, customer_id=customer, page_id=page.id, raw=jpeg.getvalue()
        )
        await share_page_wishes.leave_wish(
            session, page.token, voter_key="w" * 22, author="Mehmon", body="Tabriklar"
        )
        await session.commit()
    wish = await db.scalar(
        text("SELECT id FROM share_page_wishes WHERE page_id = :p"), {"p": page.id}
    )
    await db.execute(
        text(
            "INSERT INTO shop_health_snapshots (shop_id, checked_at, token_valid, bot_username, "
            " channel_ok, group_ok) VALUES (:s, now(), false, 'lola_bot', null, null)"
        ),
        {"s": shop},
    )
    return {
        "db": db,
        "shop": shop,
        "customer": customer,
        "page": page,
        "wish": wish,
        "photo_bytes": photo.size_bytes if photo is not None else 0,
    }


def _concrete(path: str, world: dict[str, Any]) -> str:
    return (
        path.replace("{shop_id}", str(world["shop"]))
        .replace("{page_id}", str(world["page"].id))
        .replace("{wish_id}", str(world["wish"]))
    )


async def test_every_screen_renders_and_shows_no_personal_data_or_page_secret(
    world: dict[str, Any],
) -> None:
    db = world["db"]
    app = app_for(db)
    screens = [
        route.resource.canonical
        for route in app.router.routes()
        if route.method == "GET"
        and route.resource is not None
        and route.resource.canonical.startswith("/admin")
        and route.resource.canonical != "/admin/login/{token}"
    ]
    assert len(screens) >= 6, screens
    async with TestClient(TestServer(app)) as client:
        await logged_in(client, db)
        bodies = {}
        for path in screens:
            response = await client.get(_concrete(path, world))
            assert response.status == 200, (path, response.status)
            bodies[path] = await response.text()
    everything = "\n".join(bodies.values())
    digits = re.sub(r"\D", "", everything)
    for secret in (CUSTOMER_PHONE, OWNER_PHONE):
        assert re.sub(r"\D", "", secret) not in digits, f"{secret} reached a screen"
    assert CUSTOMER_NAME not in everything and "Dilfuza" not in everything
    assert world["page"].token not in everything, "a page's secret token reached a screen"
    assert "+998 90 *** ** 33" in bodies["/admin/shops/{shop_id}"]


async def test_each_action_works_over_http_and_is_audited(world: dict[str, Any]) -> None:
    db = world["db"]
    shop, page, wish = world["shop"], world["page"].id, world["wish"]
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await logged_in(client, db)
        steps = [
            (f"/admin/shops/{shop}/pause", {"reason": "owner asked"}),
            (f"/admin/shops/{shop}/resume", {}),
            (
                f"/admin/shops/{shop}/paid",
                {"paid_until": "2027-01-31", "amount_uzs": "150 000", "method": "card_transfer"},
            ),
            (f"/admin/shops/{shop}/gift", {"on": "0"}),
            (f"/admin/pages/{page}/hide", {"reason": "abuse"}),
            (f"/admin/pages/{page}/unhide", {}),
            (f"/admin/wishes/{wish}/hide", {"reason": "rude"}),
        ]
        for path, form in steps:
            response = await client.post(path, data={"csrf": csrf, **form}, allow_redirects=False)
            assert response.status == 303, (path, response.status)
            assert response.headers["Location"].endswith("done=ok"), (
                path,
                response.headers["Location"],
            )
    actions = list(
        (await db.execute(text("SELECT action FROM admin_audit_log ORDER BY id"))).scalars()
    )
    assert actions[-7:] == [
        "shop_pause",
        "shop_resume",
        "subscription_paid",
        "gift_rule_off",
        "page_hide",
        "page_unhide",
        "wish_hide",
    ]
    row = (
        await db.execute(
            text(
                "SELECT status, subscription_status, paid_until, gift_premium_after_order "
                "FROM shops WHERE id = :s"
            ),
            {"s": shop},
        )
    ).one()
    assert (
        row.status,
        row.subscription_status,
        str(row.paid_until),
        row.gift_premium_after_order,
    ) == (
        "active",
        "paid",
        "2027-01-31",
        False,
    )
    amount = await db.scalar(
        text("SELECT amount_uzs FROM subscription_payments WHERE shop_id = :s"), {"s": shop}
    )
    assert amount == 150_000


async def test_a_refused_action_says_so_and_changes_nothing(world: dict[str, Any]) -> None:
    db = world["db"]
    async with TestClient(TestServer(app_for(db))) as client:
        csrf = await logged_in(client, db)
        response = await client.post(
            f"/admin/pages/{world['page'].id}/hide",
            data={"csrf": csrf, "reason": " "},
            allow_redirects=False,
        )
    assert response.status == 303 and response.headers["Location"].endswith("refused-reason")
    assert (
        await db.scalar(
            text("SELECT hidden_at FROM share_pages WHERE id = :p"), {"p": world["page"].id}
        )
        is None
    )


async def test_the_figures_are_counts_by_status_source_and_disk(world: dict[str, Any]) -> None:
    db = world["db"]
    # Another shop's order must not count here, and a PURGED photo's bytes
    # are no longer on disk, so they must not count either.
    other = (
        await db.execute(
            text(
                "INSERT INTO shops (name, working_hours) VALUES ('Other', CAST(:wh AS jsonb)) "
                "RETURNING id"
            ),
            {"wh": json.dumps(DEFAULT_WORKING_HOURS)},
        )
    ).scalar_one()
    stranger = (
        await db.execute(
            text("INSERT INTO customers (shop_id, telegram_user_id) VALUES (:s, 1) RETURNING id"),
            {"s": other},
        )
    ).scalar_one()
    await db.execute(
        text(
            "INSERT INTO orders (shop_id, customer_id, product_name_snapshot, "
            " telegram_file_id_snapshot, delivery_date, delivery_hour, delivery_location_text, "
            " landmark, recipient_name, status, submit_token, source) VALUES (:s, :c, 'X', 'f', "
            " '2027-03-08', '14:00', 'Y', 'Z', 'W', 'placed', 'other-1', 'direct')"
        ),
        {"s": other, "c": stranger},
    )
    await db.execute(
        text(
            "INSERT INTO share_page_photos (shop_id, page_id, position, data, width, height, "
            " size_bytes, purged_at) VALUES (:s, :p, 2, NULL, 10, 10, 999999, now())"
        ),
        {"s": world["shop"], "p": world["page"].id},
    )
    async with bound_session_factory(db)() as session:
        metrics = await admin_panel.shop_metrics(session, shop_id=world["shop"])
        (row,) = [r for r in await admin_panel.shops_overview(session) if r.id == world["shop"]]
    assert metrics.orders == {"placed": 1, "confirmed": 1, "rejected": 1}
    assert metrics.sources == {"reminder": 1, "direct": 1, "unknown": 1}
    assert metrics.customers_total == 1 and metrics.pages == {"invite": 1}
    assert row.photo_bytes == metrics.photo_bytes == world["photo_bytes"] > 0
    assert (row.health, row.health_reason) == ("bad", "token invalid")
    assert row.orders_30d == 3 and row.bouquets == 1


async def test_the_alerts_name_what_is_wrong(world: dict[str, Any]) -> None:
    db = world["db"]
    await db.execute(
        text("UPDATE orders SET status = 'confirmed' WHERE shop_id <> :s AND status = 'placed'"),
        {"s": world["shop"]},
    )
    async with bound_session_factory(db)() as session:
        found = await admin_panel.alerts(session)
    mine = {(a.kind, a.count) for a in found if a.shop_id == world["shop"]}
    assert ("unanswered_order", 1) in mine
    assert ("bot", 1) in mine
    await db.execute(
        text(
            "INSERT INTO shop_health_snapshots (shop_id, checked_at, detail) "
            "VALUES (:s, now() + interval '1 second', '{\"bot\": \"no usable bot\"}')"
        ),
        {"s": world["shop"]},
    )
    async with bound_session_factory(db)() as session:
        (row,) = [r for r in await admin_panel.shops_overview(session) if r.id == world["shop"]]
    assert (row.health, row.health_reason) == ("bad", "no usable bot (no token stored)")
    stalled = {a.detail.split(":")[0] for a in found if a.kind == "stalled_job"}
    assert "send_due_reminders" in stalled, "a job that never ran was not reported"


@pytest.mark.parametrize(
    ("phone", "shown"),
    [
        ("+998901112233", "+998 90 *** ** 33"),
        ("998 90 111 22 44", "+998 90 *** ** 44"),
        (None, "—"),
        ("123", "***"),
    ],
)
def test_a_phone_is_shown_masked(phone: str | None, shown: str) -> None:
    assert admin_panel.mask_phone(phone) == shown
