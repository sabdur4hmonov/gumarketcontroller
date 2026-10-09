"""What the platform admin panel reads (CP18). Read-only; the actions are in
gulbot.services.shop_admin.

COUNTS BEFORE PERSONAL DATA. Every screen is aggregates. Nothing here selects a
customer's name or phone; a shop owner's phone is returned only masked
(`mask_phone`), and a page is shown by its internal id, never its token -- the
token IS the page's secret.

READ ON PAGE LOAD, from stored state: the panel never calls Telegram. A shop's
bot health is the last snapshot the worker wrote (gulbot.services.shop_health).
The queries are plain aggregates over indexed columns; at the platform's scale
(hundreds of shops) that is milliseconds. A pre-aggregated daily table, as the
spec suggests for later, can replace any of them without changing a screen.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: A catalogue with no new post for longer than this is flagged.
STALE_CATALOGUE = timedelta(days=14)
#: An order nobody confirmed or rejected for this long is an alert.
UNANSWERED_ORDER = timedelta(minutes=30)


def mask_phone(phone: str | None) -> str:
    """+998 90 *** ** 12 -- at most the first 6 and the last 2 digits."""
    if not phone:
        return "—"
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) < 8:
        return "***"
    head, tail = digits[:5], digits[-2:]
    return f"+{head[:3]} {head[3:5]} *** ** {tail}"


def subscription_badge(status: str, paid_until: date | None, today: date) -> str:
    """The badge to show. 'paid' past its date reads 'overdue' -- a badge only:
    nothing is paused automatically in the MVP."""
    if status == "paid" and paid_until is not None and paid_until < today:
        return "overdue"
    return status


@dataclass(frozen=True)
class ShopRow:
    id: int
    name: str
    status: str
    bot_username: str | None
    health: str  # ok / warn / bad / unknown
    health_reason: str
    token_valid: bool | None
    channel_ok: bool | None
    group_ok: bool | None
    checked_at: datetime | None
    last_indexed_at: datetime | None
    catalogue_stale: bool
    bouquets: int
    subscription: str
    paid_until: date | None
    customers: int
    orders_30d: int
    created_at: datetime
    photo_bytes: int
    gift_rule: bool


_SHOPS = text(
    """
    SELECT s.id, s.name, s.status, s.created_at, s.subscription_status, s.paid_until,
           s.gift_premium_after_order, s.group_chat_id, s.channel_id,
           h.bot_username, h.token_valid, h.channel_ok, h.group_ok, h.checked_at,
           (SELECT max(p.indexed_at) FROM products p
             WHERE p.shop_id = s.id AND p.finalized_at IS NOT NULL) AS last_indexed_at,
           (SELECT count(*) FROM products p
             WHERE p.shop_id = s.id AND p.finalized_at IS NOT NULL
               AND p.active AND p.deleted_at IS NULL) AS bouquets,
           (SELECT count(*) FROM customers c WHERE c.shop_id = s.id) AS customers,
           (SELECT count(*) FROM orders o
             WHERE o.shop_id = s.id AND o.created_at > :since30) AS orders_30d,
           (SELECT coalesce(sum(ph.size_bytes), 0) FROM share_page_photos ph
             WHERE ph.shop_id = s.id AND ph.data IS NOT NULL) AS photo_bytes
      FROM shops s
      LEFT JOIN LATERAL (
            SELECT bot_username, token_valid, channel_ok, group_ok, checked_at
              FROM shop_health_snapshots x
             WHERE x.shop_id = s.id
             ORDER BY x.checked_at DESC
             LIMIT 1) h ON true
     ORDER BY s.name, s.id
    """
)


def _health(row: Any, now: datetime) -> tuple[str, str, bool]:
    stale = row.last_indexed_at is None or row.last_indexed_at < now - STALE_CATALOGUE
    if row.checked_at is None:
        return "unknown", "not checked yet", stale
    if row.token_valid is False:
        return "bad", "token invalid", stale
    if row.group_chat_id is not None and row.group_ok is False:
        return "bad", "bot cannot work in the admin group", stale
    if row.channel_id is not None and row.channel_ok is False:
        return "warn", "bot is not an admin of the channel", stale
    if row.group_chat_id is None:
        return "warn", "no admin group", stale
    if stale:
        return "warn", "no new bouquet for 14 days", stale
    return "ok", "", stale


async def shops_overview(session: AsyncSession, *, now: datetime | None = None) -> list[ShopRow]:
    now = now or datetime.now(UTC)
    rows = (await session.execute(_SHOPS, {"since30": now - timedelta(days=30)})).all()
    out = []
    for r in rows:
        health, reason, stale = _health(r, now)
        out.append(
            ShopRow(
                id=r.id,
                name=r.name,
                status=r.status,
                bot_username=r.bot_username,
                health=health,
                health_reason=reason,
                token_valid=r.token_valid,
                channel_ok=r.channel_ok,
                group_ok=r.group_ok,
                checked_at=r.checked_at,
                last_indexed_at=r.last_indexed_at,
                catalogue_stale=stale,
                bouquets=int(r.bouquets),
                subscription=subscription_badge(r.subscription_status, r.paid_until, now.date()),
                paid_until=r.paid_until,
                customers=int(r.customers),
                orders_30d=int(r.orders_30d),
                created_at=r.created_at,
                photo_bytes=int(r.photo_bytes),
                gift_rule=bool(r.gift_premium_after_order),
            )
        )
    return out


@dataclass(frozen=True)
class Tiles:
    by_status: dict[str, int]
    with_problems: int
    open_alerts: int
    orders_today: int
    orders_7d: int
    reminders_sent_today: int
    reminders_failed_today: int


async def tiles(
    session: AsyncSession, shops: list[ShopRow], alerts: list[Alert], *, now: datetime
) -> Tiles:
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    row = (
        await session.execute(
            text(
                """
                SELECT
                  (SELECT count(*) FROM orders WHERE created_at >= :today) AS orders_today,
                  (SELECT count(*) FROM orders WHERE created_at >= :week) AS orders_7d,
                  (SELECT count(*) FROM scheduled_notifications
                    WHERE state = 'sent' AND sent_at >= :today) AS sent_today,
                  (SELECT count(*) FROM scheduled_notifications
                    WHERE state IN ('failed', 'dead_letter') AND due_at_utc >= :today)
                    AS failed_today
                """
            ),
            {"today": today, "week": now - timedelta(days=7)},
        )
    ).one()
    by_status: dict[str, int] = {"onboarding": 0, "active": 0, "paused": 0}
    for shop in shops:
        by_status[shop.status] = by_status.get(shop.status, 0) + 1
    return Tiles(
        by_status=by_status,
        with_problems=sum(1 for s in shops if s.health == "bad"),
        open_alerts=len(alerts),
        orders_today=int(row.orders_today),
        orders_7d=int(row.orders_7d),
        reminders_sent_today=int(row.sent_today),
        reminders_failed_today=int(row.failed_today),
    )


@dataclass(frozen=True)
class ShopMetrics:
    days: int
    customers_total: int
    customers_new: int
    dates_total: int
    dates_new: int
    reminders: dict[str, int]
    orders: dict[str, int]
    sources: dict[str, int]
    unlocks_total: int
    unlocks_new: int
    pages: dict[str, int]
    photo_bytes: int
    photo_bytes_purged: int


async def shop_metrics(
    session: AsyncSession, *, shop_id: int, days: int = 30, now: datetime | None = None
) -> ShopMetrics:
    now = now or datetime.now(UTC)
    since = now - timedelta(days=days)
    p = {"s": shop_id, "since": since}
    one = (
        await session.execute(
            text(
                """
                SELECT
                  (SELECT count(*) FROM customers WHERE shop_id = :s) AS c_total,
                  (SELECT count(*) FROM customers WHERE shop_id = :s AND created_at >= :since)
                    AS c_new,
                  (SELECT count(*) FROM occasions WHERE shop_id = :s AND active) AS d_total,
                  (SELECT count(*) FROM occasions
                    WHERE shop_id = :s AND active AND created_at >= :since) AS d_new,
                  (SELECT count(*) FROM premium_unlocks WHERE shop_id = :s) AS u_total,
                  (SELECT count(*) FROM premium_unlocks
                    WHERE shop_id = :s AND granted_at >= :since) AS u_new,
                  (SELECT coalesce(sum(size_bytes), 0) FROM share_page_photos
                    WHERE shop_id = :s AND data IS NOT NULL) AS b_kept,
                  (SELECT coalesce(sum(size_bytes), 0) FROM share_page_photos
                    WHERE shop_id = :s AND data IS NULL) AS b_purged
                """
            ),
            p,
        )
    ).one()
    reminders: dict[Any, Any] = dict(
        (
            await session.execute(
                text(
                    """
                    SELECT state, count(*) FROM scheduled_notifications
                     WHERE shop_id = :s AND due_at_utc >= :since AND due_at_utc <= now()
                     GROUP BY state
                    """
                ),
                p,
            )
        ).all()
    )
    orders: dict[Any, Any] = dict(
        (
            await session.execute(
                text(
                    "SELECT status, count(*) FROM orders "
                    "WHERE shop_id = :s AND created_at >= :since GROUP BY status"
                ),
                p,
            )
        ).all()
    )
    sources: dict[Any, Any] = dict(
        (
            await session.execute(
                text(
                    """
                    SELECT CASE
                             WHEN o.source = 'page' THEN 'page_' || coalesce(sp.kind, 'unknown')
                             ELSE coalesce(o.source, 'unknown')
                           END AS src,
                           count(*)
                      FROM orders o
                      LEFT JOIN share_pages sp
                        ON sp.id = o.source_page_id AND sp.shop_id = o.shop_id
                     WHERE o.shop_id = :s AND o.created_at >= :since
                     GROUP BY src
                    """
                ),
                p,
            )
        ).all()
    )
    pages: dict[Any, Any] = dict(
        (
            await session.execute(
                text(
                    "SELECT kind, count(*) FROM share_pages "
                    "WHERE shop_id = :s AND created_at >= :since GROUP BY kind"
                ),
                p,
            )
        ).all()
    )
    return ShopMetrics(
        days=days,
        customers_total=int(one.c_total),
        customers_new=int(one.c_new),
        dates_total=int(one.d_total),
        dates_new=int(one.d_new),
        reminders={str(k): int(v) for k, v in reminders.items()},
        orders={str(k): int(v) for k, v in orders.items()},
        sources={str(k): int(v) for k, v in sources.items()},
        unlocks_total=int(one.u_total),
        unlocks_new=int(one.u_new),
        pages={str(k): int(v) for k, v in pages.items()},
        photo_bytes=int(one.b_kept),
        photo_bytes_purged=int(one.b_purged),
    )


@dataclass(frozen=True)
class ShopDetail:
    id: int
    name: str
    status: str
    status_changed_at: datetime | None
    lang: str
    timezone: str
    channel_id: int | None
    group_chat_id: int | None
    owner_count: int
    owner_phone_masked: str
    subscription: str
    paid_until: date | None
    gift_rule: bool
    reminder_offsets: list[int]
    created_at: datetime


async def shop_detail(session: AsyncSession, *, shop_id: int, now: datetime) -> ShopDetail | None:
    r = (
        await session.execute(
            text(
                """
                SELECT id, name, status, status_changed_at, lang, timezone, channel_id,
                       group_chat_id, cardinality(owner_telegram_ids) AS owners, owner_phone,
                       subscription_status, paid_until, gift_premium_after_order,
                       reminder_offsets, created_at
                  FROM shops WHERE id = :s
                """
            ),
            {"s": shop_id},
        )
    ).one_or_none()
    if r is None:
        return None
    return ShopDetail(
        id=r.id,
        name=r.name,
        status=r.status,
        status_changed_at=r.status_changed_at,
        lang=r.lang,
        timezone=r.timezone,
        channel_id=r.channel_id,
        group_chat_id=r.group_chat_id,
        owner_count=int(r.owners or 0),
        owner_phone_masked=mask_phone(r.owner_phone),
        subscription=subscription_badge(r.subscription_status, r.paid_until, now.date()),
        paid_until=r.paid_until,
        gift_rule=bool(r.gift_premium_after_order),
        reminder_offsets=list(r.reminder_offsets or []),
        created_at=r.created_at,
    )


# --- alerts --------------------------------------------------------------------------


@dataclass(frozen=True)
class Alert:
    kind: str  # dead_letter / stalled_job / bot / unanswered_order
    severity: str  # bad / warn
    shop_id: int | None
    shop_name: str
    detail: str
    count: int
    since: datetime | None


#: How often each periodic job is expected to finish; stalled past twice this.
JOB_INTERVALS: dict[str, timedelta] = {
    "send_due_reminders": timedelta(minutes=1),
    "send_order_pings": timedelta(minutes=1),
    "check_health": timedelta(minutes=5),
    "snapshot_shop_health": timedelta(minutes=10),
    "materialize_all_shops": timedelta(days=1),
    "scrub_expired_pages": timedelta(days=1),
    "send_daily_summary": timedelta(days=1),
}


async def alerts(session: AsyncSession, *, now: datetime | None = None) -> list[Alert]:
    now = now or datetime.now(UTC)
    out: list[Alert] = []
    for r in (
        await session.execute(
            text(
                """
                SELECT s.id, s.name, d.n, d.oldest FROM shops s JOIN (
                  SELECT shop_id, sum(n) AS n, min(oldest) AS oldest FROM (
                    SELECT shop_id, count(*) AS n, min(due_at_utc) AS oldest
                      FROM scheduled_notifications WHERE state = 'dead_letter' GROUP BY shop_id
                    UNION ALL
                    SELECT shop_id, count(*), min(due_at_utc)
                      FROM order_reminders WHERE state = 'dead_letter' GROUP BY shop_id
                  ) u GROUP BY shop_id
                ) d ON d.shop_id = s.id ORDER BY d.n DESC
                """
            )
        )
    ).all():
        out.append(
            Alert("dead_letter", "bad", r.id, r.name, "sends that gave up", int(r.n), r.oldest)
        )
    runs = {
        r.name: r
        for r in (
            await session.execute(text("SELECT name, last_finished_at, last_ok FROM job_runs"))
        ).all()
    }
    for job, interval in JOB_INTERVALS.items():
        run = runs.get(job)
        finished = run.last_finished_at if run is not None else None
        if finished is None or finished < now - 2 * interval:
            out.append(
                Alert(
                    "stalled_job",
                    "bad",
                    None,
                    "platform",
                    f"{job}: no finished run since "
                    + (finished.strftime("%Y-%m-%d %H:%M UTC") if finished else "ever"),
                    1,
                    finished,
                )
            )
        elif run is not None and run.last_ok is False:
            out.append(
                Alert(
                    "stalled_job", "warn", None, "platform", f"{job}: last run failed", 1, finished
                )
            )
    for row in await shops_overview(session, now=now):
        if row.health == "bad":
            out.append(Alert("bot", "bad", row.id, row.name, row.health_reason, 1, row.checked_at))
    for r in (
        await session.execute(
            text(
                """
                SELECT s.id, s.name, count(*) AS n, min(o.created_at) AS oldest
                  FROM orders o JOIN shops s ON s.id = o.shop_id
                 WHERE o.status = 'placed' AND o.created_at < :cutoff
                 GROUP BY s.id, s.name ORDER BY n DESC
                """
            ),
            {"cutoff": now - UNANSWERED_ORDER},
        )
    ).all():
        out.append(
            Alert(
                "unanswered_order",
                "warn",
                r.id,
                r.name,
                "orders not confirmed or rejected for 30+ minutes",
                int(r.n),
                r.oldest,
            )
        )
    return out


# --- share pages -------------------------------------------------------------------------


@dataclass(frozen=True)
class PagesSummary:
    by_kind: dict[str, int]
    live: int
    hidden: int
    expired_or_deleted: int
    views: int
    cta_clicks: int
    rsvps: int
    wishes: int
    wishes_hidden: int
    orders_attributed: int


async def pages_summary(session: AsyncSession, *, shop_id: int | None = None) -> PagesSummary:
    p = {"s": shop_id}
    r = (
        await session.execute(
            text(
                """
                SELECT
                  count(*) FILTER (WHERE deleted_at IS NULL AND expires_at > now()
                                     AND hidden_at IS NULL) AS live,
                  count(*) FILTER (WHERE hidden_at IS NOT NULL) AS hidden,
                  count(*) FILTER (WHERE deleted_at IS NOT NULL OR expires_at <= now())
                    AS gone,
                  coalesce(sum(view_count), 0) AS views,
                  coalesce(sum(cta_click_count), 0) AS clicks
                  FROM share_pages WHERE (CAST(:s AS bigint) IS NULL OR shop_id = :s)
                """
            ),
            p,
        )
    ).one()
    by_kind: dict[Any, Any] = dict(
        (
            await session.execute(
                text(
                    "SELECT kind, count(*) FROM share_pages "
                    "WHERE (CAST(:s AS bigint) IS NULL OR shop_id = :s) GROUP BY kind"
                ),
                p,
            )
        ).all()
    )
    extra = (
        await session.execute(
            text(
                """
                SELECT
                  (SELECT count(*) FROM share_page_rsvps
                    WHERE (CAST(:s AS bigint) IS NULL OR shop_id = :s)) AS rsvps,
                  (SELECT count(*) FROM share_page_wishes
                    WHERE (CAST(:s AS bigint) IS NULL OR shop_id = :s)) AS wishes,
                  (SELECT count(*) FROM share_page_wishes
                    WHERE (CAST(:s AS bigint) IS NULL OR shop_id = :s)
                      AND admin_hidden_at IS NOT NULL) AS wishes_hidden,
                  (SELECT count(*) FROM orders
                    WHERE (CAST(:s AS bigint) IS NULL OR shop_id = :s) AND source = 'page')
                    AS orders_attributed
                """
            ),
            p,
        )
    ).one()
    return PagesSummary(
        by_kind={str(k): int(v) for k, v in by_kind.items()},
        live=int(r.live),
        hidden=int(r.hidden),
        expired_or_deleted=int(r.gone),
        views=int(r.views),
        cta_clicks=int(r.clicks),
        rsvps=int(extra.rsvps),
        wishes=int(extra.wishes),
        wishes_hidden=int(extra.wishes_hidden),
        orders_attributed=int(extra.orders_attributed),
    )


@dataclass(frozen=True)
class PageRow:
    id: int
    shop_id: int
    shop_name: str
    kind: str
    template: str
    created_at: datetime
    creator_ref: str  # the customer's internal id, never a name or phone
    views: int
    rsvps: int
    wishes: int
    state: str  # live / hidden / gone
    hidden_reason: str | None


async def page_row(session: AsyncSession, *, page_id: int) -> PageRow | None:
    rows = await recent_pages(session, page_id=page_id, limit=1)
    return rows[0] if rows else None


async def recent_pages(
    session: AsyncSession,
    *,
    shop_id: int | None = None,
    page_id: int | None = None,
    limit: int = 50,
) -> list[PageRow]:
    rows = (
        await session.execute(
            text(
                """
                SELECT sp.id, sp.shop_id, s.name AS shop_name, sp.kind, sp.template,
                       sp.created_at, sp.customer_id, sp.view_count,
                       sp.deleted_at, sp.expires_at, sp.hidden_at, sp.hidden_reason,
                       (SELECT count(*) FROM share_page_rsvps r WHERE r.page_id = sp.id) AS rsvps,
                       (SELECT count(*) FROM share_page_wishes w WHERE w.page_id = sp.id) AS wishes
                  FROM share_pages sp JOIN shops s ON s.id = sp.shop_id
                 WHERE (CAST(:s AS bigint) IS NULL OR sp.shop_id = :s)
                   AND (CAST(:p AS bigint) IS NULL OR sp.id = :p)
                 ORDER BY sp.id DESC
                 LIMIT :n
                """
            ),
            {"s": shop_id, "p": page_id, "n": limit},
        )
    ).all()
    now = datetime.now(UTC)
    out = []
    for r in rows:
        if r.hidden_at is not None:
            state = "hidden"
        elif r.deleted_at is not None or r.expires_at <= now:
            state = "gone"
        else:
            state = "live"
        out.append(
            PageRow(
                id=r.id,
                shop_id=r.shop_id,
                shop_name=r.shop_name,
                kind=r.kind,
                template=r.template,
                created_at=r.created_at,
                creator_ref=f"#{r.customer_id}",
                views=int(r.view_count),
                rsvps=int(r.rsvps),
                wishes=int(r.wishes),
                state=state,
                hidden_reason=r.hidden_reason,
            )
        )
    return out


@dataclass(frozen=True)
class WishRow:
    id: int
    page_id: int
    author: str
    body: str
    created_at: datetime
    hidden_by_creator: bool
    hidden_by_admin: bool


async def page_wishes(session: AsyncSession, *, page_id: int) -> list[WishRow]:
    """A page's wishes -- typed by GUESTS on a public page, so moderation needs
    to read them. Shown escaped, like everything else."""
    rows = (
        await session.execute(
            text(
                "SELECT id, page_id, author, body, created_at, hidden, admin_hidden_at "
                "FROM share_page_wishes WHERE page_id = :p ORDER BY id"
            ),
            {"p": page_id},
        )
    ).all()
    return [
        WishRow(
            r.id, r.page_id, r.author, r.body, r.created_at, r.hidden, r.admin_hidden_at is not None
        )
        for r in rows
    ]


@dataclass(frozen=True)
class AuditRow:
    at: datetime
    admin: int | None
    action: str
    shop_id: int | None
    target: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    reason: str | None
    ip: str | None


async def audit_entries(
    session: AsyncSession, *, shop_id: int | None = None, limit: int = 200
) -> list[AuditRow]:
    rows = (
        await session.execute(
            text(
                """
                SELECT at, admin_telegram_id, action, shop_id, target_type, target_id,
                       before, after, reason, ip
                  FROM admin_audit_log
                 WHERE (CAST(:s AS bigint) IS NULL OR shop_id = :s)
                 ORDER BY id DESC LIMIT :n
                """
            ),
            {"s": shop_id, "n": limit},
        )
    ).all()
    return [
        AuditRow(
            at=r.at,
            admin=r.admin_telegram_id,
            action=r.action,
            shop_id=r.shop_id,
            target=f"{r.target_type} {r.target_id}" if r.target_type else "",
            before=r.before,
            after=r.after,
            reason=r.reason,
            ip=r.ip,
        )
        for r in rows
    ]
