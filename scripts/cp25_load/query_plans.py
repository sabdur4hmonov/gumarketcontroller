"""Capture actual hot SELECT plans on the owned small synthetic fixture only."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from gulbot.config import get_settings
from gulbot.sending.dispatcher import select_due_rows
from gulbot.sending.order_pings import load_card
from gulbot.services import admin_panel, bouquets, shop_crm

from .load_seed import DATABASE, OWNER_MARKER
from .resources import available_mib


async def capture() -> dict[str, Any]:
    engine = create_async_engine(get_settings().database_url(database=DATABASE), pool_size=1)
    statements: list[tuple[str, str, Any]] = []
    label = ""

    def record(
        conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool
    ) -> None:
        if label and statement.lstrip().upper().startswith("SELECT"):
            statements.append((label, statement, parameters))

    try:
        async with engine.connect() as conn:
            marker = await conn.scalar(
                text(
                    "SELECT shobj_description(oid, 'pg_database') FROM pg_database "
                    "WHERE datname = current_database()"
                )
            )
            if marker != OWNER_MARKER:
                raise RuntimeError("Only the owned capacity fixture may be explained")
            shops = int(await conn.scalar(text("SELECT count(*) FROM shops")) or 0)
            if not 0 < shops <= 50:
                raise RuntimeError("EXPLAIN requires a small synthetic fixture")
            await conn.execute(text("SET LOCAL statement_timeout = '10s'"))
            await conn.execute(
                text(
                    "INSERT INTO products (id, shop_id, name, telegram_file_id, source, "
                    "finalized_at, indexed_at) SELECT 100000+i, 1, 'Plan fixture', "
                    "'CP25_PLAN_FILE', 'manual', now(), now()-i*interval '1 minute' "
                    "FROM generate_series(1,1000) i"
                )
            )
            await conn.execute(text("ANALYZE products"))
            event.listen(engine.sync_engine, "before_cursor_execute", record)
            async with AsyncSession(bind=conn) as session:
                label = "catalog_keyset"
                await bouquets.list_bouquets(session, shop_id=1)
                label = "catalog_choice"
                await bouquets.choose_bouquet(session, shop_id=1)
                label = "shop_customers"
                await shop_crm.customers(session, shop_id=1)
                label = "shop_orders"
                await shop_crm.orders(session, shop_id=1, flt=shop_crm.OrderFilter())
                label = "admin_shops"
                await admin_panel.shops_overview(session)
                label = "order_card"
                await load_card(session, order_id=1)
                label = "reminder_selection"
                # Sent fixtures still exercise the real locking query; no rows reset.
                await select_due_rows(session, now_utc=datetime(2027, 3, 8, tzinfo=UTC))
                label = ""
                plans = []
                for name, sql, params in statements:
                    result = await conn.exec_driver_sql(
                        "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql, params
                    )
                    plans.append({"name": name, "sql": sql, "plan": result.scalar_one()})
            await conn.rollback()  # release locks, no fixture writes
        return {
            "kind": "measured",
            "shops": shops,
            "temporary_catalog_rows": 1000,
            "database": DATABASE,
            "captured_at": datetime.now(UTC).isoformat(),
            "queries": plans,
            "limitations": "Small synthetic fixture; sent reminders; not production capacity.",
        }
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", choices=("before-index", "after-index"), required=True)
    args = parser.parse_args()
    if available_mib() < 768:
        raise SystemExit("Waiting for RAM: small EXPLAIN needs 768 MiB; no retry")
    result = asyncio.run(capture())
    path = Path(f"docs/capacity/cp25-query-plans-{args.label}.json")
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for query in result["queries"]:
        plan = query["plan"][0]
        print(query["name"], plan["Execution Time"], "ms", plan["Plan"]["Node Type"])


if __name__ == "__main__":
    main()
