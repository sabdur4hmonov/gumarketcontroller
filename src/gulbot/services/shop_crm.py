"""What a shop owner sees in their own panel, /shop (CP20).

EVERY QUERY TAKES `shop_id` AND FILTERS ON IT FIRST. The panel passes the
session's shop and nothing else (gulbot.web.shop_panel), and each function
here scopes every table it reads to that shop, so a mistake in one would show
an empty screen rather than another shop's customers.

These are the shop's OWN customers, so phones are shown in full -- unlike the
platform admin's screens, which mask them. Saved dates are shown by the label
the customer gave and the date: nothing else about the person is stored.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.scheduling.occurrences import TASHKENT, occurrence_date_for

#: Rows per page on the customers and orders screens.
PAGE_SIZE = 100
#: How far ahead the upcoming-dates screen looks.
UPCOMING_DAYS = 30
#: An export is capped so one click cannot build an unbounded file in memory.
EXPORT_LIMIT = 20_000

#: Where an order came from, as the shop reads it. NULL = placed before CP18.
SOURCE_LABELS: dict[str | None, str] = {
    "reminder": "eslatmadan",
    "holiday": "bayram tabrigidan",
    "direct": "o‘zi kirib",
    "page": "sahifadan",
    None: "—",
}
STATUS_LABELS: dict[str, str] = {
    "placed": "kutilmoqda",
    "confirmed": "tasdiqlangan",
    "delivered": "yetkazilgan",
    "rejected": "rad etilgan",
    "cancelled": "bekor qilingan",
}


async def shop_name(session: AsyncSession, *, shop_id: int) -> str:
    name = await session.scalar(text("SELECT name FROM shops WHERE id = :shop"), {"shop": shop_id})
    return str(name or "")


@dataclass(frozen=True)
class CustomerRow:
    id: int
    phone: str | None
    since: datetime
    saved_dates: int
    orders: int
    last_order_at: datetime | None


@dataclass(frozen=True)
class CustomerPage:
    rows: list[CustomerRow]
    total: int
    page: int
    pages: int


_CUSTOMERS = """
    SELECT c.id, c.phone, c.created_at AS since,
           (SELECT count(*) FROM occasions o
              JOIN recipients r ON r.id = o.recipient_id AND r.shop_id = :shop
             WHERE o.shop_id = :shop AND o.customer_id = c.id
               AND o.active AND r.active) AS saved_dates,
           (SELECT count(*) FROM orders x
             WHERE x.shop_id = :shop AND x.customer_id = c.id) AS orders,
           (SELECT max(x.created_at) FROM orders x
             WHERE x.shop_id = :shop AND x.customer_id = c.id) AS last_order_at
      FROM customers c
     WHERE c.shop_id = :shop
     ORDER BY last_order_at DESC NULLS LAST, c.id DESC
"""


def _customer(row: Any) -> CustomerRow:
    return CustomerRow(
        id=int(row.id),
        phone=row.phone,
        since=row.since,
        saved_dates=int(row.saved_dates),
        orders=int(row.orders),
        last_order_at=row.last_order_at,
    )


async def customers(session: AsyncSession, *, shop_id: int, page: int = 1) -> CustomerPage:
    total = int(
        await session.scalar(
            text("SELECT count(*) FROM customers WHERE shop_id = :shop"), {"shop": shop_id}
        )
        or 0
    )
    pages = max(1, -(-total // PAGE_SIZE))
    page = min(max(1, page), pages)
    rows = await session.execute(
        text(_CUSTOMERS + " LIMIT :limit OFFSET :offset"),
        {"shop": shop_id, "limit": PAGE_SIZE, "offset": (page - 1) * PAGE_SIZE},
    )
    return CustomerPage([_customer(r) for r in rows], total, page, pages)


@dataclass(frozen=True)
class UpcomingDate:
    on: date
    days: int
    label: str
    kind: str
    customer_id: int
    phone: str | None


async def upcoming_dates(
    session: AsyncSession, *, shop_id: int, today: date, days: int = UPCOMING_DAYS
) -> list[UpcomingDate]:
    """Every active saved date falling in [today, today + days], soonest first."""
    rows = await session.execute(
        text(
            """
            SELECT o.month, o.day, o.kind, r.label, c.id AS customer_id, c.phone
              FROM occasions o
              JOIN recipients r ON r.id = o.recipient_id AND r.shop_id = :shop
              JOIN customers c ON c.id = o.customer_id AND c.shop_id = :shop
             WHERE o.shop_id = :shop AND o.active AND r.active
            """
        ),
        {"shop": shop_id},
    )
    end = today + timedelta(days=days)
    found: list[UpcomingDate] = []
    for row in rows:
        for year in (today.year, today.year + 1):
            on = occurrence_date_for(int(row.month), int(row.day), year)
            if today <= on <= end:
                found.append(
                    UpcomingDate(
                        on=on,
                        days=(on - today).days,
                        label=str(row.label),
                        kind=str(row.kind),
                        customer_id=int(row.customer_id),
                        phone=row.phone,
                    )
                )
                break
    found.sort(key=lambda u: (u.on, u.customer_id, u.label))
    return found


@dataclass(frozen=True)
class OrderFilter:
    status: str | None = None
    source: str | None = None
    since: date | None = None
    until: date | None = None

    @classmethod
    def parse(cls, query: Any) -> OrderFilter:
        """From the request's query string; anything unknown is dropped, never
        passed to SQL."""
        status = query.get("status")
        source = query.get("source")
        return cls(
            status=status if status in STATUS_LABELS else None,
            source=source if source in SOURCE_LABELS and source is not None else None,
            since=_date(query.get("since")),
            until=_date(query.get("until")),
        )


def _date(raw: str | None) -> date | None:
    try:
        return date.fromisoformat(raw) if raw else None
    except ValueError:
        return None


@dataclass(frozen=True)
class OrderRow:
    id: int
    created_at: datetime
    delivery_date: date
    product: str
    price_uzs: int | None
    status: str
    source: str | None
    phone: str | None


def _orders_sql(f: OrderFilter) -> tuple[str, dict[str, Any]]:
    where = ["x.shop_id = :shop"]
    params: dict[str, Any] = {}
    if f.status:
        where.append("x.status = :status")
        params["status"] = f.status
    if f.source:
        where.append("x.source = :source")
        params["source"] = f.source
    if f.since:
        where.append("x.created_at >= :since")
        params["since"] = datetime.combine(f.since, time(), tzinfo=TASHKENT)
    if f.until:
        where.append("x.created_at < :until")
        params["until"] = datetime.combine(f.until + timedelta(days=1), time(), tzinfo=TASHKENT)
    sql = f"""
        SELECT x.id, x.created_at, x.delivery_date, x.product_name_snapshot AS product,
               x.price_uzs_snapshot AS price_uzs, x.status, x.source, c.phone
          FROM orders x
          JOIN customers c ON c.id = x.customer_id AND c.shop_id = :shop
         WHERE {" AND ".join(where)}
         ORDER BY x.created_at DESC, x.id DESC
    """
    return sql, params


def _order(row: Any) -> OrderRow:
    return OrderRow(
        id=int(row.id),
        created_at=row.created_at,
        delivery_date=row.delivery_date,
        product=str(row.product),
        price_uzs=row.price_uzs,
        status=str(row.status),
        source=row.source,
        phone=row.phone,
    )


async def orders(
    session: AsyncSession, *, shop_id: int, flt: OrderFilter, limit: int = PAGE_SIZE
) -> list[OrderRow]:
    sql, params = _orders_sql(flt)
    rows = await session.execute(
        text(sql + " LIMIT :limit"), {"shop": shop_id, "limit": limit, **params}
    )
    return [_order(r) for r in rows]


async def order_source_counts(session: AsyncSession, *, shop_id: int) -> dict[str | None, int]:
    rows = await session.execute(
        text("SELECT source, count(*) FROM orders WHERE shop_id = :shop GROUP BY source"),
        {"shop": shop_id},
    )
    return {row[0]: int(row[1]) for row in rows}


# --- CSV --------------------------------------------------------------------

#: A cell starting with one of these is a formula to a spreadsheet; such a cell
#: is prefixed with a quote so it is shown, never run (CSV injection).
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    shown = str(value)
    if shown.startswith(_FORMULA_START) and not shown.lstrip("+").isdigit():
        return "'" + shown
    return shown


def _csv(header: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    out = io.StringIO()
    # A BOM so Excel opens Uzbek and Russian text as UTF-8.
    out.write("﻿")
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow([_cell(v) for v in row])
    return out.getvalue()


async def customers_csv(session: AsyncSession, *, shop_id: int) -> tuple[str, int]:
    rows = [
        _customer(r)
        for r in await session.execute(
            text(_CUSTOMERS + " LIMIT :limit"), {"shop": shop_id, "limit": EXPORT_LIMIT}
        )
    ]
    body = _csv(
        ("id", "telefon", "qo‘shilgan", "saqlangan sanalar", "buyurtmalar", "oxirgi buyurtma"),
        ((r.id, r.phone, r.since, r.saved_dates, r.orders, r.last_order_at) for r in rows),
    )
    return body, len(rows)


async def orders_csv(session: AsyncSession, *, shop_id: int, flt: OrderFilter) -> tuple[str, int]:
    found = await orders(session, shop_id=shop_id, flt=flt, limit=EXPORT_LIMIT)
    body = _csv(
        ("id", "vaqt", "yetkazish", "buket", "narx", "holat", "qayerdan", "telefon"),
        (
            (
                r.id,
                r.created_at,
                r.delivery_date.isoformat(),
                r.product,
                r.price_uzs,
                STATUS_LABELS.get(r.status, r.status),
                SOURCE_LABELS.get(r.source, r.source or "—"),
                r.phone,
            )
            for r in found
        ),
    )
    return body, len(found)
