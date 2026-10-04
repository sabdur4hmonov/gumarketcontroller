"""The public web service: every Ha/Yo'q page and every taklifnoma, by link.

    GET  /p/<token>             the page (410 once deleted or expired)
    POST /p/<token>/yes         Ha was pressed
    POST /p/<token>/rsvp        an invitation's Kelaman / Kela olmayman
    POST /p/<token>/choose      after Ha: the place and time from the date plan
    GET  /p/<token>/go          a tap on the shop's link: counted, then t.me
    GET  /p/<token>/event.ics   the invitation as a calendar entry
    GET  /demo[/<kind>[/<theme>]]  the designs, with sample text
    GET  /static/...            CSS, JS, fonts -- this origin only
    GET  /robots.txt, /healthz

SECURITY, in one place (`secure_headers`): a Content-Security-Policy that
allows scripts, styles, fonts and images from this origin and nothing else --
no inline script, no inline style, no third party -- plus noindex on every
response, no referrer, no framing. User text is escaped by the templates.

A POST must carry `X-Requested-With: gulbot` and a JSON body. A cross-site
<form> can send neither, and a cross-site fetch() that sets that header needs a
CORS preflight this server never answers, so only the page itself can answer.
Every POST is rate-limited per client address.

NO PHONE NUMBER IS EVER ON A PAGE: nothing here reads customers.phone or
shops.owner_phone, and `tests/test_web_pages.py` greps the rendered HTML.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import time as clock
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable
from typing import Final

from aiohttp import web
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gulbot.models.share_page import (
    MAX_GUESTS,
    PAGE_LANGUAGES,
    PAGE_TEMPLATES,
    PageKind,
    SharePage,
)
from gulbot.services import share_pages
from gulbot.web import render, strings

log = logging.getLogger("gulbot.web")

TOKEN_RE: Final = re.compile(r"^[A-Za-z0-9_-]{20,32}$")
VOTER_RE: Final = re.compile(r"^[A-Za-z0-9_-]{22}$")
BOT_USERNAME_RE: Final = re.compile(r"^[A-Za-z0-9_]{5,32}$")
RSVP_COOKIE: Final = "gb_rsvp"

CSP: Final = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; form-action 'none'; base-uri 'none'; "
    "frame-ancestors 'none'"
)

#: Notify = "a creator may want telling about this page, now or `delay`
#: seconds from now": the task is queued, and the claim in the database
#: decides whether anything is sent.
Notify = Callable[[int, float], Awaitable[None] | None]

#: The second look after a Ha on a page with a date plan: a little after
#: CHOICE_WAIT, so the "nothing chosen yet" message is due when it runs.
CHOICE_CHECK_DELAY: Final = share_pages.CHOICE_WAIT.total_seconds() + 30

KEY_SESSIONS: Final[web.AppKey[async_sessionmaker[AsyncSession]]] = web.AppKey("sessions")
KEY_NOTIFY: Final[web.AppKey[Notify]] = web.AppKey("notify")


class RateLimiter:
    """At most `limit` events per `window` seconds per key, in memory.

    Per process, which is enough for one web process; the bounded map keeps a
    flood of addresses from growing it without limit.
    """

    def __init__(
        self,
        *,
        limit: int,
        window: float,
        max_keys: int = 20_000,
        now: Callable[[], float] = clock.monotonic,
    ) -> None:
        self.limit, self.window, self.max_keys, self._now = limit, window, max_keys, now
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()

    def allow(self, key: str) -> bool:
        now = self._now()
        hits = self._hits.pop(key, None) or deque()
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        allowed = len(hits) < self.limit
        if allowed:
            hits.append(now)
        self._hits[key] = hits
        while len(self._hits) > self.max_keys:
            self._hits.popitem(last=False)
        return allowed


class WebSettings:
    def __init__(self, *, public_base_url: str, trust_proxy: bool) -> None:
        self.public_base_url = public_base_url.rstrip("/")
        self.secure = self.public_base_url.startswith("https://")
        self.trust_proxy = trust_proxy


KEY_LIMITER: Final[web.AppKey[dict[str, RateLimiter]]] = web.AppKey("limiter")
KEY_SETTINGS: Final[web.AppKey[WebSettings]] = web.AppKey("web_settings")


@web.middleware
async def secure_headers(
    request: web.Request, handler: Callable[[web.Request], Awaitable[web.StreamResponse]]
) -> web.StreamResponse:
    try:
        response = await handler(request)
    except web.HTTPException as http:
        _harden(request, http)
        raise
    except Exception:
        log.exception("unhandled error on %s", request.method)
        response = web.Response(status=500, text="Server error")
    _harden(request, response)
    return response


def _harden(request: web.Request, response: web.StreamResponse) -> None:
    settings = request.app[KEY_SETTINGS]
    headers = response.headers
    headers["Content-Security-Policy"] = CSP
    headers["X-Content-Type-Options"] = "nosniff"
    headers["Referrer-Policy"] = "no-referrer"
    headers["X-Frame-Options"] = "DENY"
    headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
    headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=(), payment=()"
    headers["Cross-Origin-Opener-Policy"] = "same-origin"
    headers["Cross-Origin-Resource-Policy"] = "same-origin"
    if settings.secure:
        headers["Strict-Transport-Security"] = "max-age=31536000"
    if request.path.startswith("/static/"):
        headers["Cache-Control"] = "public, max-age=31536000, immutable"
    else:
        headers.setdefault("Cache-Control", "no-store")


def _client(request: web.Request) -> str:
    settings = request.app[KEY_SETTINGS]
    if settings.trust_proxy:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.remote or "?"


def _limit(request: web.Request, bucket: str) -> None:
    limiter = request.app[KEY_LIMITER]
    if not limiter[bucket].allow(f"{bucket}:{_client(request)}"):
        raise web.HTTPTooManyRequests(text="Too many requests")


def _token(request: web.Request) -> str:
    token = request.match_info["token"]
    if not TOKEN_RE.match(token):
        raise web.HTTPNotFound()
    return token


def _html(body: str, status: int = 200) -> web.Response:
    return web.Response(status=status, text=body, content_type="text/html", charset="utf-8")


def _gone(
    theme: str = "minimal", lang: str = "uz", shop: str = "Gulbot", status: int = 410
) -> web.Response:
    view = render.gone_view(theme, lang, render.Branding(shop_name=shop, cta_url=None))
    return _html(render.render("gone.html", view), status=status)


def _check_post(request: web.Request) -> None:
    """Only the page's own script may answer: see the module docstring."""
    if request.headers.get("X-Requested-With") != "gulbot":
        raise web.HTTPForbidden(text="Forbidden")
    if request.content_type != "application/json":
        raise web.HTTPUnsupportedMediaType(text="JSON only")
    origin = request.headers.get("Origin")
    settings = request.app[KEY_SETTINGS]
    if origin is not None and origin.rstrip("/") not in (
        settings.public_base_url,
        _own_origin(request),
    ):
        raise web.HTTPForbidden(text="Forbidden")


def _own_origin(request: web.Request) -> str:
    return f"{request.scheme}://{request.host}"


async def page(request: web.Request) -> web.Response:
    token = request.match_info["token"]
    if not TOKEN_RE.match(token):
        return _gone(status=404)
    sessions = request.app[KEY_SESSIONS]
    async with sessions() as session:
        found = await share_pages.load_public_page(session, token)
        if found is None:
            return _gone(status=404)
        p = found.page
        if not found.live:
            return _gone(p.template, p.lang, found.shop_name)
        # Telegram's link-preview fetcher reads the page to draw the preview in
        # the chat; that is not a person opening it.
        if "TelegramBot" not in request.headers.get("User-Agent", ""):
            await share_pages.record_view(session, page_id=p.id)
            await session.commit()
        cta = f"/p/{token}/go" if p.bot_username else None
        plan = None
        if p.kind == PageKind.YESNO:
            places, slots = await share_pages.plan_of(session, page_id=p.id)
            plan = render.Plan(
                places=[(o.id, o.place or "") for o in places],
                slots=[
                    (o.id, strings.slot_text(o.slot_at, p.lang, found.shop_timezone))
                    for o in slots
                    if o.slot_at is not None
                ],
            )
        body = render.page_html(
            p,
            render.Branding(shop_name=found.shop_name, cta_url=cta),
            tz_name=found.shop_timezone,
            base=f"/p/{token}",
            plan=plan,
        )
    return _html(body)


async def answer_yes(request: web.Request) -> web.Response:
    _check_post(request)
    _limit(request, "yes")
    token = _token(request)
    sessions = request.app[KEY_SESSIONS]
    async with sessions() as session:
        outcome = await share_pages.answer_yes(session, token)
        await session.commit()
    if outcome is None:
        raise web.HTTPNotFound(text="Not found")
    if outcome.first and outcome.notify:
        await _queue(request, outcome.page_id, 0)
        if outcome.has_plan:
            # If they close the page without choosing, this is what tells the
            # creator "Ha -- but nothing chosen yet".
            await _queue(request, outcome.page_id, CHOICE_CHECK_DELAY)
    return web.json_response({"ok": True})


async def _queue(request: web.Request, page_id: int, delay: float) -> None:
    notify = request.app[KEY_NOTIFY]
    try:
        pending = notify(page_id, delay)
        if pending is not None:
            await pending
    except Exception:
        # The answer is recorded; only the creator's message is at stake, and
        # its claim stays unclaimed for a later attempt.
        log.exception("page %s: could not queue the creator's message", page_id)


def _option_id(value: object) -> int:
    """An option id from the page's JSON: a plain integer, nothing else
    (``true`` is an int to Python, not to us)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise web.HTTPBadRequest(text="Bad values")
    return value


async def choose(request: web.Request) -> web.Response:
    """After Ha, the recipient's place and time. The first pick is kept."""
    _check_post(request)
    _limit(request, "yes")
    token = _token(request)
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise web.HTTPBadRequest(text="Bad JSON") from None
    place = _option_id(body.get("place") if isinstance(body, dict) else None)
    slot = _option_id(body.get("slot") if isinstance(body, dict) else None)
    sessions = request.app[KEY_SESSIONS]
    async with sessions() as session:
        try:
            outcome = await share_pages.choose(session, token, place_id=place, slot_id=slot)
        except share_pages.ChoiceRefused as refused:
            await session.rollback()
            if refused.reason == "page":
                raise web.HTTPNotFound(text="Not found") from None
            raise web.HTTPBadRequest(text="Bad values") from None
        lang = await session.scalar(select(SharePage.lang).where(SharePage.id == outcome.page_id))
        await session.commit()
    if outcome.first:
        await _queue(request, outcome.page_id, 0)
    line = strings.text("plan_chosen", str(lang)).format(
        place=outcome.place,
        when=strings.slot_text(outcome.slot_at, str(lang), outcome.shop_timezone),
    )
    return web.json_response({"ok": True, "line": line})


async def rsvp(request: web.Request) -> web.Response:
    _check_post(request)
    _limit(request, "rsvp")
    token = _token(request)
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise web.HTTPBadRequest(text="Bad JSON") from None
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="Bad JSON")
    answer, guests, name = body.get("answer"), body.get("guests", 0), body.get("name")
    if (
        not isinstance(answer, str)
        or isinstance(guests, bool)
        or not isinstance(guests, int)
        or not (name is None or isinstance(name, str))
        or not 0 <= guests <= MAX_GUESTS
    ):
        raise web.HTTPBadRequest(text="Bad values")

    voter = request.cookies.get(RSVP_COOKIE, "")
    if not VOTER_RE.match(voter):
        voter = secrets.token_urlsafe(16)
    sessions = request.app[KEY_SESSIONS]
    async with sessions() as session:
        try:
            await share_pages.submit_rsvp(
                session, token, voter_key=voter, answer=answer, guests=guests, guest_name=name
            )
        except share_pages.RsvpRefused as refused:
            await session.rollback()
            reason = str(refused)
            if reason == "page":
                raise web.HTTPNotFound(text="Not found") from None
            if reason == "full":
                raise web.HTTPTooManyRequests(text="Full") from None
            raise web.HTTPBadRequest(text="Bad values") from None
        await session.commit()
    settings = request.app[KEY_SETTINGS]
    response = web.json_response({"ok": True})
    response.set_cookie(
        RSVP_COOKIE,
        voter,
        path=f"/p/{token}",
        max_age=180 * 24 * 3600,
        httponly=True,
        samesite="Strict",
        secure=settings.secure,
    )
    return response


async def go(request: web.Request) -> web.Response:
    token = _token(request)
    sessions = request.app[KEY_SESSIONS]
    async with sessions() as session:
        found = await share_pages.record_cta(session, token)
        await session.commit()
    if found is None:
        raise web.HTTPNotFound()
    username, live = found
    if live and username and BOT_USERNAME_RE.match(username):
        raise web.HTTPFound(f"https://t.me/{username}?start=pg_{token}")
    raise web.HTTPFound(f"/p/{token}")


async def event_ics(request: web.Request) -> web.Response:
    token = _token(request)
    sessions = request.app[KEY_SESSIONS]
    async with sessions() as session:
        found = await share_pages.load_public_page(session, token)
    if found is None or not found.live or found.page.kind != PageKind.INVITE:
        raise web.HTTPNotFound()
    settings = request.app[KEY_SETTINGS]
    body = render.ics(
        found.page, tz_name=found.shop_timezone, page_url=f"{settings.public_base_url}/p/{token}"
    )
    return web.Response(
        body=body.encode(),
        content_type="text/calendar",
        charset="utf-8",
        headers={"Content-Disposition": 'attachment; filename="taklifnoma.ics"'},
    )


def _demo_lang(request: web.Request) -> str:
    lang = request.query.get("lang", "uz")
    return lang if lang in PAGE_LANGUAGES else "uz"


async def demo_page(request: web.Request) -> web.Response:
    kind, theme = request.match_info["kind"], request.match_info["theme"]
    if kind not in tuple(PageKind) or theme not in PAGE_TEMPLATES:
        raise web.HTTPNotFound()
    event = request.query.get("event", "wedding")
    if event not in strings.EVENT_LABELS:
        event = "wedding"
    lang = _demo_lang(request)
    sample = render.sample_page(kind, theme, lang, event_type=event)
    branding = render.Branding(shop_name=render.SAMPLE_SHOP, cta_url=None)
    plan = render.sample_plan(lang) if request.query.get("plan") == "1" else None
    # The sample's own endpoints do not exist; pressing Ha only celebrates.
    return _html(
        render.page_html(sample, branding, tz_name="Asia/Tashkent", base="/demo/none", plan=plan)
    )


async def demo_index(request: web.Request) -> web.Response:
    kind = request.match_info.get("kind", "yesno")
    if kind not in tuple(PageKind):
        raise web.HTTPNotFound()
    lang = _demo_lang(request)
    view = render.gallery_view(kind, lang)
    return _html(render.render("gallery.html", view))


async def robots(_request: web.Request) -> web.Response:
    return web.Response(text="User-agent: *\nDisallow: /\n", content_type="text/plain")


async def healthz(_request: web.Request) -> web.Response:
    return web.Response(text="ok", content_type="text/plain")


def build_app(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    notify: Notify,
    public_base_url: str,
    trust_proxy: bool = False,
    yes_limit: int = 30,
    rsvp_limit: int = 12,
) -> web.Application:
    app = web.Application(middlewares=[secure_headers], client_max_size=4096)
    app[KEY_SESSIONS] = session_factory
    app[KEY_NOTIFY] = notify
    app[KEY_SETTINGS] = WebSettings(public_base_url=public_base_url, trust_proxy=trust_proxy)
    app[KEY_LIMITER] = {
        "yes": RateLimiter(limit=yes_limit, window=60.0),
        "rsvp": RateLimiter(limit=rsvp_limit, window=60.0),
    }
    app.router.add_get("/p/{token}", page)
    app.router.add_post("/p/{token}/yes", answer_yes)
    app.router.add_post("/p/{token}/rsvp", rsvp)
    app.router.add_post("/p/{token}/choose", choose)
    app.router.add_get("/p/{token}/go", go)
    app.router.add_get("/p/{token}/event.ics", event_ics)
    app.router.add_get("/demo", demo_index)
    app.router.add_get("/demo/{kind}", demo_index)
    app.router.add_get("/demo/{kind}/{theme}", demo_page)
    app.router.add_get("/robots.txt", robots)
    app.router.add_get("/healthz", healthz)
    app.router.add_static("/static/", render.STATIC, show_index=False, follow_symlinks=False)
    return app
