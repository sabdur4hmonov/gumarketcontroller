"""The shop owner's own panel, under /shop on the page server (CP20).

    GET  /shop/login/<token>        the link from the SHOP's bot: a "Kirish" button
    POST /shop/login                spends the link, opens a session for its shop
    POST /shop/logout
    GET  /shop                      customers
    GET  /shop/dates                saved dates in the next 30 days
    GET  /shop/orders               orders, filtered, with where each came from
    GET  /shop/export/customers.csv
    GET  /shop/export/orders.csv    the same filters as the screen
    GET  /shop/instagram            CP23: the shop's Instagram account (connect / disconnect)

ONE GATE FOR EVERY ROUTE (`shop_gate`), as for /admin: a live session or 401,
and every POST needs the session's CSRF token. tests/test_shop_panel.py walks
the router, so a route added later cannot be forgotten.

NO ROUTE TAKES A SHOP. Not in the path, not in the query string: every screen
reads `request[KEY_OWNER].shop_id`, which only the bot that minted the login
link can set. The same test walks every route as an owner of shop A with shop
B's data planted, and greps for B.

Same cookie rules as /admin, under its own name and path: HttpOnly, Secure,
SameSite=Strict, Path=/shop, one hour.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Final

from aiohttp import web
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gulbot.holidays import BY_KEY, HOLIDAYS
from gulbot.i18n import t
from gulbot.models.instagram import InstagramConnection, InstagramStoryUpload
from gulbot.scheduling.occurrences import TASHKENT
from gulbot.services import holiday_campaigns, instagram, shop_auth, shop_crm
from gulbot.web import render

log = logging.getLogger("gulbot.web.shop_panel")

PREFIX: Final = "/shop"
COOKIE: Final = "gb_shop"
PUBLIC_ROUTES: Final = frozenset({("GET", "/shop/login/{token}"), ("POST", "/shop/login")})

KEY_SHOP_SESSIONS: Final[web.AppKey[async_sessionmaker[AsyncSession]]] = web.AppKey("shop_sessions")
KEY_OWNER: Final[web.RequestKey[shop_auth.ShopOwner]] = web.RequestKey(
    "shop_owner", shop_auth.ShopOwner
)

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


def is_panel_path(path: str) -> bool:
    return path == PREFIX or path.startswith(PREFIX + "/")


def _html(body: str, status: int = 200) -> web.Response:
    return web.Response(status=status, text=body, content_type="text/html", charset="utf-8")


def _ip(request: web.Request) -> str:
    from gulbot.web.app import client_address

    return client_address(request)


def _route_key(request: web.Request) -> tuple[str, str | None]:
    resource = request.match_info.route.resource
    return request.method, (resource.canonical if resource is not None else None)


@web.middleware
async def shop_gate(request: web.Request, handler: Handler) -> web.StreamResponse:
    if not is_panel_path(request.path):
        return await handler(request)
    if KEY_SHOP_SESSIONS not in request.app:
        raise web.HTTPNotFound()  # the panel is not configured in this app
    if _route_key(request) in PUBLIC_ROUTES:
        return await handler(request)
    async with request.app[KEY_SHOP_SESSIONS]() as session:
        owner = await shop_auth.load_session(session, request.cookies.get(COOKIE))
        if owner is None:
            if request.method == "GET":
                return _html(await render.render_async("shop/denied.html", {}), status=401)
            raise web.HTTPForbidden(text="Forbidden")
        if request.method != "GET":
            form = await request.post()
            submitted = form.get("csrf")
            if not shop_auth.csrf_ok(owner, submitted if isinstance(submitted, str) else None):
                await shop_auth.audit(
                    session,
                    shop_id=owner.shop_id,
                    action="csrf_refused",
                    owner=owner.telegram_id,
                    reason=request.path,
                    ip=_ip(request),
                )
                await session.commit()
                raise web.HTTPForbidden(text="Forbidden")
    request[KEY_OWNER] = owner
    return await handler(request)


# --- getting in and out -------------------------------------------------------


async def login_page(request: web.Request) -> web.Response:
    from gulbot.web.app import limit

    limit(request, "shop_login")
    token = request.match_info["token"]
    if not shop_auth.TOKEN_RE.match(token):
        return _html(await render.render_async("shop/denied.html", {}), status=401)
    return _html(await render.render_async("shop/login.html", {"token": token}))


async def login(request: web.Request) -> web.Response:
    from gulbot.web.app import limit

    limit(request, "shop_login")
    form = await request.post()
    token = form.get("token")
    if not isinstance(token, str) or not shop_auth.TOKEN_RE.match(token):
        return _html(await render.render_async("shop/denied.html", {}), status=401)
    async with request.app[KEY_SHOP_SESSIONS]() as session:
        opened = await shop_auth.consume_login_link(session, token, ip=_ip(request))
        await session.commit()
    if opened is None:
        return _html(await render.render_async("shop/denied.html", {}), status=401)
    response = web.HTTPSeeOther(PREFIX)
    response.set_cookie(
        COOKIE,
        opened.token,
        path=PREFIX,
        max_age=int(shop_auth.SESSION_TTL.total_seconds()),
        httponly=True,
        secure=True,
        samesite="Strict",
    )
    raise response


async def logout(request: web.Request) -> web.Response:
    async with request.app[KEY_SHOP_SESSIONS]() as session:
        await shop_auth.end_session(session, request[KEY_OWNER], ip=_ip(request))
        await session.commit()
    response = _html(await render.render_async("shop/bye.html", {}))
    response.del_cookie(COOKIE, path=PREFIX)
    return response


# --- the screens ----------------------------------------------------------------


def local(moment: datetime | None) -> str:
    return moment.astimezone(TASHKENT).strftime("%Y-%m-%d %H:%M") if moment else "—"


async def _view(
    request: web.Request, session: AsyncSession, nav: str, **extra: Any
) -> dict[str, Any]:
    owner = request[KEY_OWNER]
    return {
        "owner": owner,
        "csrf": owner.csrf,
        "nav": nav,
        "shop_name": await shop_crm.shop_name(session, shop_id=owner.shop_id),
        "local": local,
        "sources": shop_crm.SOURCE_LABELS,
        "statuses": shop_crm.STATUS_LABELS,
        **extra,
    }


def _page_number(request: web.Request) -> int:
    raw = request.query.get("page", "1")
    return int(raw) if raw.isdigit() and len(raw) < 7 else 1


async def customers_screen(request: web.Request) -> web.Response:
    shop_id = request[KEY_OWNER].shop_id
    async with request.app[KEY_SHOP_SESSIONS]() as session:
        found = await shop_crm.customers(session, shop_id=shop_id, page=_page_number(request))
        view = await _view(request, session, "customers", page=found)
    return _html(await render.render_async("shop/customers.html", view))


async def dates_screen(request: web.Request) -> web.Response:
    shop_id = request[KEY_OWNER].shop_id
    today = datetime.now(UTC).astimezone(TASHKENT).date()
    async with request.app[KEY_SHOP_SESSIONS]() as session:
        found = await shop_crm.upcoming_dates(session, shop_id=shop_id, today=today)
        view = await _view(
            request, session, "dates", dates=found, days=shop_crm.UPCOMING_DAYS, today=today
        )
    return _html(await render.render_async("shop/dates.html", view))


async def orders_screen(request: web.Request) -> web.Response:
    shop_id = request[KEY_OWNER].shop_id
    flt = shop_crm.OrderFilter.parse(request.query)
    async with request.app[KEY_SHOP_SESSIONS]() as session:
        found = await shop_crm.orders(session, shop_id=shop_id, flt=flt)
        counts = await shop_crm.order_source_counts(session, shop_id=shop_id)
        view = await _view(
            request,
            session,
            "orders",
            orders=found,
            flt=flt,
            counts=counts,
            query=request.query_string,
        )
    return _html(await render.render_async("shop/orders.html", view))


def _csv_response(body: str, name: str) -> web.Response:
    stamp = datetime.now(UTC).astimezone(TASHKENT).strftime("%Y%m%d-%H%M")
    response = web.Response(body=body.encode("utf-8"), content_type="text/csv", charset="utf-8")
    response.headers["Content-Disposition"] = f'attachment; filename="{name}-{stamp}.csv"'
    return response


async def export_customers(request: web.Request) -> web.Response:
    owner = request[KEY_OWNER]
    async with request.app[KEY_SHOP_SESSIONS]() as session:
        body, count = await shop_crm.customers_csv(session, shop_id=owner.shop_id)
        await shop_auth.audit(
            session,
            shop_id=owner.shop_id,
            action="export_customers",
            owner=owner.telegram_id,
            detail={"rows": count},
            ip=_ip(request),
        )
        await session.commit()
    return _csv_response(body, "mijozlar")


async def export_orders(request: web.Request) -> web.Response:
    owner = request[KEY_OWNER]
    flt = shop_crm.OrderFilter.parse(request.query)
    async with request.app[KEY_SHOP_SESSIONS]() as session:
        body, count = await shop_crm.orders_csv(session, shop_id=owner.shop_id, flt=flt)
        await shop_auth.audit(
            session,
            shop_id=owner.shop_id,
            action="export_orders",
            owner=owner.telegram_id,
            detail={
                "rows": count,
                "status": flt.status,
                "source": flt.source,
                "since": flt.since.isoformat() if flt.since else None,
                "until": flt.until.isoformat() if flt.until else None,
            },
            ip=_ip(request),
        )
        await session.commit()
    return _csv_response(body, "buyurtmalar")


# --- holiday campaigns (CP20) ---------------------------------------------------


async def holidays_screen(request: web.Request) -> web.Response:
    shop_id = request[KEY_OWNER].shop_id
    today = datetime.now(UTC).astimezone(TASHKENT).date()
    async with request.app[KEY_SHOP_SESSIONS]() as session:
        enabled = await holiday_campaigns.enabled_holidays(session, shop_id=shop_id)
        lunar = await holiday_campaigns.lunar_dates(session)
        listeners = len(await holiday_campaigns.opted_in_customers(session, shop_id=shop_id))
        view = await _view(
            request,
            session,
            "holidays",
            holidays=HOLIDAYS,
            names={h.key: t(f"holiday.{h.key}", "uz") for h in HOLIDAYS},
            enabled=enabled,
            lunar={key: [d for d in dates if d >= today][:1] for key, dates in lunar.items()},
            listeners=listeners,
            notice=request.query.get("done", ""),
        )
    return _html(await render.render_async("shop/holidays.html", view))


async def switch_holiday(request: web.Request) -> web.Response:
    owner = request[KEY_OWNER]
    form = await request.post()
    holiday, choice = form.get("holiday"), form.get("on")
    if not isinstance(holiday, str) or holiday not in BY_KEY or choice not in ("1", "0"):
        raise web.HTTPSeeOther(PREFIX + "/holidays?done=refused")
    async with request.app[KEY_SHOP_SESSIONS]() as session:
        changed = await holiday_campaigns.set_shop_holiday(
            session,
            shop_id=owner.shop_id,
            holiday=holiday,
            on=choice == "1",
            owner_id=owner.telegram_id,
        )
        if changed:
            await shop_auth.audit(
                session,
                shop_id=owner.shop_id,
                action="holiday_on" if choice == "1" else "holiday_off",
                owner=owner.telegram_id,
                detail={"holiday": holiday},
                ip=_ip(request),
            )
        await session.commit()
    raise web.HTTPSeeOther(PREFIX + "/holidays?done=ok")


# --- CP23: the shop's Instagram account -----------------------------------------

UPLOAD_LABELS: Final = {
    "queued": "navbatda",
    "container": "yuborilmoqda",
    "published": "joylandi",
    "failed": "xato",
    "expired": "muddati o‘tdi",
}


async def instagram_screen(request: web.Request) -> web.Response:
    shop_id = request[KEY_OWNER].shop_id
    async with request.app[KEY_SHOP_SESSIONS]() as session:
        connection = await session.get(InstagramConnection, shop_id)
        uploads = (
            await session.scalars(
                select(InstagramStoryUpload)
                .where(InstagramStoryUpload.shop_id == shop_id)
                .order_by(InstagramStoryUpload.created_at.desc())
                .limit(10)
            )
        ).all()
        view = await _view(
            request,
            session,
            "instagram",
            enabled=instagram.enabled(),
            connection=connection,
            uploads=uploads,
            upload_labels=UPLOAD_LABELS,
            notice=request.query.get("done", ""),
        )
    return _html(await render.render_async("shop/instagram.html", view))


async def instagram_connect(request: web.Request) -> web.Response:
    """A fresh one-time state, then a LINK to Instagram (not a redirect: the
    panel's CSP lets a form go only to this origin)."""
    owner = request[KEY_OWNER]
    async with request.app[KEY_SHOP_SESSIONS]() as session:
        try:
            link = await instagram.start_connect(
                session, shop_id=owner.shop_id, owner_id=owner.telegram_id
            )
        except instagram.InstagramRefused as refused:
            raise web.HTTPSeeOther(PREFIX + "/instagram?done=" + refused.code) from None
        await shop_auth.audit(
            session,
            shop_id=owner.shop_id,
            action="instagram_connect_started",
            owner=owner.telegram_id,
            ip=_ip(request),
        )
        view = await _view(request, session, "instagram", link=link)
        await session.commit()
    return _html(await render.render_async("shop/instagram_go.html", view))


async def instagram_disconnect(request: web.Request) -> web.Response:
    owner = request[KEY_OWNER]
    async with request.app[KEY_SHOP_SESSIONS]() as session:
        if await instagram.disconnect(session, shop_id=owner.shop_id, owner_id=owner.telegram_id):
            await shop_auth.audit(
                session,
                shop_id=owner.shop_id,
                action="instagram_disconnected",
                owner=owner.telegram_id,
                ip=_ip(request),
            )
        await session.commit()
    raise web.HTTPSeeOther(PREFIX + "/instagram?done=disconnected")


def add_routes(app: web.Application, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
    app[KEY_SHOP_SESSIONS] = session_factory
    app.router.add_get(PREFIX + "/login/{token}", login_page)
    app.router.add_post(PREFIX + "/login", login)
    app.router.add_post(PREFIX + "/logout", logout)
    app.router.add_get(PREFIX, customers_screen)
    app.router.add_get(PREFIX + "/dates", dates_screen)
    app.router.add_get(PREFIX + "/orders", orders_screen)
    app.router.add_get(PREFIX + "/export/customers.csv", export_customers)
    app.router.add_get(PREFIX + "/export/orders.csv", export_orders)
    app.router.add_get(PREFIX + "/holidays", holidays_screen)
    app.router.add_post(PREFIX + "/holidays", switch_holiday)
    app.router.add_get(PREFIX + "/instagram", instagram_screen)
    app.router.add_post(PREFIX + "/instagram/connect", instagram_connect)
    app.router.add_post(PREFIX + "/instagram/disconnect", instagram_disconnect)
