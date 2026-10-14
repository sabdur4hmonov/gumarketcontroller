"""Admin aggregates scan each tenant table once, with unchanged shop totals."""

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.services import admin_panel


async def test_admin_totals_do_not_rescan_products_for_every_shop(db):
    now = datetime.now(UTC)
    ids = []
    for name in ["CP25 plan A", "CP25 plan B", "CP25 empty"]:
        ids.append(
            await db.scalar(
                text(
                    "INSERT INTO shops(name,working_hours) "
                    "VALUES(:n,CAST(:w AS jsonb)) RETURNING id"
                ),
                {"n": name, "w": json.dumps(DEFAULT_WORKING_HOURS)},
            )
        )
    for shop, active, indexed in [
        (ids[0], True, now - timedelta(days=2)),
        (ids[0], False, now),
        (ids[1], True, now - timedelta(days=3)),
    ]:
        await db.execute(
            text(
                "INSERT INTO products(shop_id,name,telegram_file_id,source,active,"
                "finalized_at,indexed_at) VALUES(:s,'Plan','CP25_FILE','manual',:active,:at,:at)"
            ),
            {"s": shop, "active": active, "at": indexed},
        )
    overview = {r.id: r for r in await admin_panel.shops_overview(db, now=now)}
    assert [overview[s].bouquets for s in ids] == [1, 1, 0]
    assert overview[ids[0]].last_indexed_at == now, "Inactive finalized posts still count as newest"
    assert overview[ids[1]].last_indexed_at == now - timedelta(days=3), (
        "Aggregates remain tenant-scoped"
    )
    assert overview[ids[2]].customers == 0 and overview[ids[2]].orders_30d == 0
    result = await db.execute(
        text("EXPLAIN (ANALYZE, FORMAT JSON) " + admin_panel._SHOPS.text),
        {"since30": now - timedelta(days=30)},
    )
    root = result.scalar_one()[0]["Plan"]
    scans = []

    def walk(node):
        if node.get("Relation Name") in {"products", "customers", "orders", "share_page_photos"}:
            scans.append(node)
        for child in node.get("Plans", []):
            walk(child)

    walk(root)
    assert scans and all(n["Actual Loops"] <= 1 for n in scans), (
        "Admin tenant totals must not scan once per shop"
    )
