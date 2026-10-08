"""The platform admin panel, under /admin on the page server (CP18).

    GET  /admin/login/<token>   the link from the platform bot: a "Kirish" button
    POST /admin/login           spends the link, opens a session
    POST /admin/logout
    GET  /admin ...             the screens (gulbot.web.admin_screens)

ONE GATE FOR EVERY ROUTE (`admin_gate`). Everything under /admin needs a live
session, except the two routes in PUBLIC_ROUTES, and every POST needs the
session's CSRF token as well. The gate is a middleware, not a decorator, so a
new route is protected the moment it is added; tests/test_admin_auth.py walks
the router and fails if any /admin route answers without a session.

WHY A BUTTON AND NOT A BARE LINK. Telegram -- and any other link-preview
fetcher -- GETs a URL the moment it appears in a chat. If GET spent the link,
the preview would log in and the admin would find it already used. So GET
only shows a button, and spending is a POST from that page.

THE COOKIE: HttpOnly, Secure, SameSite=Strict, Path=/admin, one hour. Secure
works on http://127.0.0.1 in a browser (localhost is a secure context); on a
server the panel is only ever reached over the HTTPS proxy.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Final

from aiohttp import web
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gulbot.services import admin_auth
from gulbot.web import render

log = logging.getLogger("gulbot.web.admin")

PREFIX: Final = "/admin"
COOKIE: Final = "gb_admin"
#: The only /admin routes a browser may reach without a session.
PUBLIC_ROUTES: Final = frozenset({("GET", "/admin/login/{token}"), ("POST", "/admin/login")})
#: The panel's own CSP: the pages' policy, plus forms that post to this origin.
CSP: Final = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; form-action 'self'; base-uri 'none'; "
    "frame-ancestors 'none'"
)

KEY_ADMIN_SESSIONS: Final[web.AppKey[async_sessionmaker[AsyncSession]]] = web.AppKey(
    "admin_sessions"
)
KEY_ADMIN_IDS: Final[web.AppKey[Callable[[], frozenset[int]]]] = web.AppKey("admin_ids")
#: Who is making this request; set by admin_gate on every protected route.
KEY_ADMIN: Final[web.RequestKey[admin_auth.Admin]] = web.RequestKey("admin", admin_auth.Admin)

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


def _html(body: str, status: int = 200) -> web.Response:
    return web.Response(status=status, text=body, content_type="text/html", charset="utf-8")


def client_ip(request: web.Request) -> str:
    from gulbot.web.app import client_address

    return client_address(request)


def _route_key(request: web.Request) -> tuple[str, str | None]:
    resource = request.match_info.route.resource
    return request.method, (resource.canonical if resource is not None else None)


@web.middleware
async def admin_gate(request: web.Request, handler: Handler) -> web.StreamResponse:
    if request.path != PREFIX and not request.path.startswith(PREFIX + "/"):
        return await handler(request)
    if KEY_ADMIN_SESSIONS not in request.app:
        raise web.HTTPNotFound()  # the panel is not configured in this app
    if _route_key(request) in PUBLIC_ROUTES:
        return await handler(request)
    sessions = request.app[KEY_ADMIN_SESSIONS]
    async with sessions() as session:
        admin = await admin_auth.load_session(
            session, request.cookies.get(COOKIE), allowed=request.app[KEY_ADMIN_IDS]()
        )
        if admin is None:
            if request.method == "GET":
                return _html(render.render("admin/denied.html", {}), status=401)
            raise web.HTTPForbidden(text="Forbidden")
        if request.method != "GET":
            form = await request.post()
            submitted = form.get("csrf")
            if not admin_auth.csrf_ok(admin, submitted if isinstance(submitted, str) else None):
                await admin_auth.audit(
                    session,
                    action="csrf_refused",
                    admin=admin.telegram_id,
                    reason=request.path,
                    ip=client_ip(request),
                )
                await session.commit()
                raise web.HTTPForbidden(text="Forbidden")
    request[KEY_ADMIN] = admin
    return await handler(request)


async def login_page(request: web.Request) -> web.Response:
    from gulbot.web.app import limit

    limit(request, "admin_login")
    token = request.match_info["token"]
    if not admin_auth.TOKEN_RE.match(token):
        return _html(render.render("admin/denied.html", {}), status=401)
    return _html(render.render("admin/login.html", {"token": token}))


async def login(request: web.Request) -> web.Response:
    from gulbot.web.app import limit

    limit(request, "admin_login")
    form = await request.post()
    token = form.get("token")
    if not isinstance(token, str) or not admin_auth.TOKEN_RE.match(token):
        return _html(render.render("admin/denied.html", {}), status=401)
    sessions = request.app[KEY_ADMIN_SESSIONS]
    async with sessions() as session:
        opened = await admin_auth.consume_login_link(
            session, token, allowed=request.app[KEY_ADMIN_IDS](), ip=client_ip(request)
        )
        await session.commit()
    if opened is None:
        return _html(render.render("admin/denied.html", {}), status=401)
    response = web.HTTPSeeOther(PREFIX)
    response.set_cookie(
        COOKIE,
        opened.token,
        path=PREFIX,
        max_age=int(admin_auth.SESSION_TTL.total_seconds()),
        httponly=True,
        secure=True,
        samesite="Strict",
    )
    raise response


async def logout(request: web.Request) -> web.Response:
    sessions = request.app[KEY_ADMIN_SESSIONS]
    async with sessions() as session:
        await admin_auth.end_session(session, request[KEY_ADMIN], ip=client_ip(request))
        await session.commit()
    response = _html(render.render("admin/bye.html", {}))
    response.del_cookie(COOKIE, path=PREFIX)
    return response


def add_routes(
    app: web.Application,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    admin_ids: Callable[[], frozenset[int]],
) -> None:
    from gulbot.web import admin_screens

    app[KEY_ADMIN_SESSIONS] = session_factory
    app[KEY_ADMIN_IDS] = admin_ids
    app.router.add_get(PREFIX + "/login/{token}", login_page)
    app.router.add_post(PREFIX + "/login", login)
    app.router.add_post(PREFIX + "/logout", logout)
    admin_screens.add_routes(app)
