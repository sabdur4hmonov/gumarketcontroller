"""The admin panel's screens and actions (CP18). Every route here is behind
`gulbot.web.admin.admin_gate`: by the time a handler runs, the session is live
and, for a POST, its CSRF token matched.

    GET  /admin                          overview + all shops
    GET  /admin/shops/<id>               one shop: checklist, metrics, actions, activity
    POST /admin/shops/<id>/pause|resume  status (reason optional)
    POST /admin/shops/<id>/paid          mark the subscription paid
    POST /admin/shops/<id>/gift          the gift rule on or off
    GET  /admin/alerts                   platform alerts
    GET  /admin/pages                    share pages: counts first, then the list
    GET  /admin/pages/<id>               one page's moderation view (its wishes)
    POST /admin/pages/<id>/hide|unhide
    POST /admin/wishes/<id>/hide
    GET  /admin/audit                    the audit log

An action answers with 303 back to the screen it came from (POST-redirect-GET),
so a refresh never repeats it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from aiohttp import web
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.services import admin_auth, admin_panel, shop_admin
from gulbot.web import render

MAX_DAYS = 365


def _html(body: str, status: int = 200) -> web.Response:
    return web.Response(status=status, text=body, content_type="text/html", charset="utf-8")


def _admin(request: web.Request) -> admin_auth.Admin:
    from gulbot.web.admin import KEY_ADMIN

    return request[KEY_ADMIN]


def _view(request: web.Request, nav: str, **values: object) -> dict[str, object]:
    admin = _admin(request)
    return {"admin": admin.telegram_id, "csrf": admin.csrf, "nav": nav, **values}


def _sessions(request: web.Request):  # type: ignore[no-untyped-def]
    from gulbot.web.admin import KEY_ADMIN_SESSIONS

    return request.app[KEY_ADMIN_SESSIONS]


def _ip(request: web.Request) -> str:
    from gulbot.web.admin import client_ip

    return client_ip(request)


def _int(request: web.Request, key: str) -> int:
    try:
        return int(request.match_info[key])
    except (KeyError, ValueError):
        raise web.HTTPNotFound() from None


async def overview(request: web.Request) -> web.Response:
    now = datetime.now(UTC)
    async with _sessions(request)() as session:
        shops = await admin_panel.shops_overview(session, now=now)
        alerts = await admin_panel.alerts(session, now=now)
        tiles = await admin_panel.tiles(session, shops, alerts, now=now)
    attention = sorted(
        (s for s in shops if s.health in ("bad", "warn") or s.subscription == "overdue"),
        key=lambda s: (s.health != "bad", s.name),
    )[:10]
    return _html(
        render.render(
            "admin/overview.html",
            _view(request, "shops", shops=shops, tiles=tiles, attention=attention, now=now),
        )
    )


async def shop(request: web.Request) -> web.Response:
    shop_id = _int(request, "shop_id")
    try:
        days = max(1, min(MAX_DAYS, int(request.query.get("days", "30"))))
    except ValueError:
        days = 30
    now = datetime.now(UTC)
    async with _sessions(request)() as session:
        detail = await admin_panel.shop_detail(session, shop_id=shop_id, now=now)
        if detail is None:
            raise web.HTTPNotFound()
        row = next(
            (s for s in await admin_panel.shops_overview(session, now=now) if s.id == shop_id),
            None,
        )
        metrics = await admin_panel.shop_metrics(session, shop_id=shop_id, days=days, now=now)
        activity = await admin_panel.audit_entries(session, shop_id=shop_id, limit=30)
    return _html(
        render.render(
            "admin/shop.html",
            _view(
                request,
                "shops",
                d=detail,
                row=row,
                m=metrics,
                activity=activity,
                default_paid_until=_next_paid_until(detail.paid_until, now.date()),
                notice=request.query.get("done", ""),
            ),
        )
    )


def _next_paid_until(current: date | None, today: date) -> date:
    start = current if current is not None and current > today else today
    return start + timedelta(days=30)


async def _act(request: web.Request, shop_id: int, work) -> web.Response:  # type: ignore[no-untyped-def]
    async with _sessions(request)() as session:
        try:
            await work(session)
        except shop_admin.ActionRefused as refused:
            await session.rollback()
            raise web.HTTPSeeOther(
                f"/admin/shops/{shop_id}?done=refused-{refused.reason}"
            ) from None
        await session.commit()
    raise web.HTTPSeeOther(f"/admin/shops/{shop_id}?done=ok")


async def _form(request: web.Request) -> dict[str, str]:
    form = await request.post()
    return {k: v for k, v in form.items() if isinstance(v, str)}


def _status_action(status: str):  # type: ignore[no-untyped-def]
    async def handler(request: web.Request) -> web.Response:
        shop_id = _int(request, "shop_id")
        form = await _form(request)

        async def work(session: AsyncSession) -> None:
            await shop_admin.set_shop_status(
                session,
                admin=_admin(request),
                shop_id=shop_id,
                status=status,
                reason=form.get("reason"),
                ip=_ip(request),
            )

        return await _act(request, shop_id, work)

    return handler


async def paid(request: web.Request) -> web.Response:
    shop_id = _int(request, "shop_id")
    form = await _form(request)
    try:
        payment = shop_admin.Payment(
            paid_until=date.fromisoformat(form.get("paid_until", "")),
            amount_uzs=int(form.get("amount_uzs", "0").replace(" ", "")),
            method=form.get("method", ""),
            note=form.get("note"),
        )
    except ValueError:
        raise web.HTTPSeeOther(f"/admin/shops/{shop_id}?done=refused-payment") from None

    async def work(session: AsyncSession) -> None:
        await shop_admin.mark_paid(
            session, admin=_admin(request), shop_id=shop_id, payment=payment, ip=_ip(request)
        )

    return await _act(request, shop_id, work)


async def gift(request: web.Request) -> web.Response:
    shop_id = _int(request, "shop_id")
    form = await _form(request)

    async def work(session: AsyncSession) -> None:
        await shop_admin.set_gift_rule(
            session,
            admin=_admin(request),
            shop_id=shop_id,
            on=form.get("on") == "1",
            ip=_ip(request),
        )

    return await _act(request, shop_id, work)


async def alerts(request: web.Request) -> web.Response:
    async with _sessions(request)() as session:
        found = await admin_panel.alerts(session)
    counts: dict[str, int] = {}
    for alert in found:
        counts[alert.kind] = counts.get(alert.kind, 0) + 1
    return _html(
        render.render("admin/alerts.html", _view(request, "alerts", alerts=found, counts=counts))
    )


async def pages(request: web.Request) -> web.Response:
    try:
        shop_id: int | None = int(request.query["shop"]) if "shop" in request.query else None
    except ValueError:
        shop_id = None
    async with _sessions(request)() as session:
        summary = await admin_panel.pages_summary(session, shop_id=shop_id)
        rows = await admin_panel.recent_pages(session, shop_id=shop_id)
    return _html(
        render.render(
            "admin/pages.html", _view(request, "pages", summary=summary, rows=rows, shop_id=shop_id)
        )
    )


async def page(request: web.Request) -> web.Response:
    page_id = _int(request, "page_id")
    async with _sessions(request)() as session:
        row = await admin_panel.page_row(session, page_id=page_id)
        if row is None:
            raise web.HTTPNotFound()
        wishes = await admin_panel.page_wishes(session, page_id=page_id)
    return _html(
        render.render(
            "admin/page.html",
            _view(request, "pages", p=row, wishes=wishes, notice=request.query.get("done", "")),
        )
    )


def _page_action(hidden: bool):  # type: ignore[no-untyped-def]
    async def handler(request: web.Request) -> web.Response:
        page_id = _int(request, "page_id")
        form = await _form(request)
        async with _sessions(request)() as session:
            try:
                await shop_admin.set_page_hidden(
                    session,
                    admin=_admin(request),
                    page_id=page_id,
                    hidden=hidden,
                    reason=form.get("reason"),
                    ip=_ip(request),
                )
            except shop_admin.ActionRefused as refused:
                await session.rollback()
                raise web.HTTPSeeOther(
                    f"/admin/pages/{page_id}?done=refused-{refused.reason}"
                ) from None
            await session.commit()
        raise web.HTTPSeeOther(f"/admin/pages/{page_id}?done=ok")

    return handler


async def hide_wish(request: web.Request) -> web.Response:
    wish_id = _int(request, "wish_id")
    form = await _form(request)
    async with _sessions(request)() as session:
        try:
            after = await shop_admin.hide_wish(
                session,
                admin=_admin(request),
                wish_id=wish_id,
                reason=form.get("reason"),
                ip=_ip(request),
            )
        except shop_admin.ActionRefused as refused:
            await session.rollback()
            raise web.HTTPSeeOther(f"/admin/pages?done=refused-{refused.reason}") from None
        await session.commit()
    raise web.HTTPSeeOther(f"/admin/pages/{after['page_id']}?done=ok")


async def audit_log(request: web.Request) -> web.Response:
    try:
        shop_id: int | None = int(request.query["shop"]) if "shop" in request.query else None
    except ValueError:
        shop_id = None
    async with _sessions(request)() as session:
        entries = await admin_panel.audit_entries(session, shop_id=shop_id)
    return _html(
        render.render("admin/audit.html", _view(request, "audit", entries=entries, shop_id=shop_id))
    )


def add_routes(app: web.Application) -> None:
    r = app.router
    r.add_get("/admin", overview)
    r.add_get(r"/admin/shops/{shop_id:\d{1,18}}", shop)
    r.add_post(r"/admin/shops/{shop_id:\d{1,18}}/pause", _status_action("paused"))
    r.add_post(r"/admin/shops/{shop_id:\d{1,18}}/resume", _status_action("active"))
    r.add_post(r"/admin/shops/{shop_id:\d{1,18}}/paid", paid)
    r.add_post(r"/admin/shops/{shop_id:\d{1,18}}/gift", gift)
    r.add_get("/admin/alerts", alerts)
    r.add_get("/admin/pages", pages)
    r.add_get(r"/admin/pages/{page_id:\d{1,18}}", page)
    r.add_post(r"/admin/pages/{page_id:\d{1,18}}/hide", _page_action(True))
    r.add_post(r"/admin/pages/{page_id:\d{1,18}}/unhide", _page_action(False))
    r.add_post(r"/admin/wishes/{wish_id:\d{1,18}}/hide", hide_wish)
    r.add_get("/admin/audit", audit_log)
