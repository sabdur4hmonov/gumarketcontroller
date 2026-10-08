"""The admin panel's screens (CP18). Every route here is behind
`gulbot.web.admin.admin_gate`: by the time a handler runs, the session is live
and, for a POST, its CSRF token matched.

    GET  /admin       the landing screen
"""

from __future__ import annotations

from aiohttp import web

from gulbot.web import render


def _html(body: str, status: int = 200) -> web.Response:
    return web.Response(status=status, text=body, content_type="text/html", charset="utf-8")


def _view(request: web.Request, nav: str, **values: object) -> dict[str, object]:
    from gulbot.web.admin import KEY_ADMIN

    admin = request[KEY_ADMIN]
    return {"admin": admin.telegram_id, "csrf": admin.csrf, "nav": nav, **values}


async def home(request: web.Request) -> web.Response:
    return _html(render.render("admin/home.html", _view(request, "shops")))


def add_routes(app: web.Application) -> None:
    app.router.add_get("/admin", home)
