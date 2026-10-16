"""Taklifnoma Studio, under /studio on the page server (CP27.1).

    GET  /studio/enter/<token>   the link from the SHOP's bot: a "Kirish" button
    POST /studio/enter           spends the link, opens a session for its customer
    POST /studio/logout
    GET  /studio                 the whole taklifnoma on ONE form, every design
    POST /studio/create          "Joy qo'shish" / "O'chirish" (the form again) or create
    POST /studio/preview         the page with the creator's own data, never saved
    GET  /studio/done/<page_id>  the new page's link, to send in the bot

ONE GATE FOR EVERY ROUTE (`studio_gate`), as for /admin and /shop: a live
session or 401, every POST carries the session's CSRF token, and entitlement
(services/studio.entitled) is re-checked on every request. tests walk the
router, so a route added later cannot be forgotten.

NO ROUTE TAKES A SHOP OR A CUSTOMER. Every write uses request[KEY_CREATOR],
which only the bot that minted the link can set; /studio/done/<page_id> shows
a page only if it is this creator's own in this shop.

THE RULES ARE THE BOT'S. A page is made by share_pages.create_page -- the same
validation, premium wall and limits as the bot's wizard -- and the preview
renders the real template from share_pages.checked_draft inside a savepoint
that is always rolled back.

No JavaScript is needed: adding and removing a place round-trips the form.
studio.js only adds the copy button. Cookie: HttpOnly, SameSite=Lax, Path=/studio,
Secure whenever the site is https.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Final

from aiohttp import web
from multidict import MultiDictProxy
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gulbot.config import TASHKENT
from gulbot.models.share_page import (
    EVENT_TYPES,
    MESSAGE_MAX,
    NAME_MAX,
    PAGE_LANGUAGES,
    VENUE_ADDRESS_MAX,
    VENUE_KINDS,
    VENUE_NAME_MAX,
    VENUES_MAX,
    SharePage,
)
from gulbot.services import premium, share_pages, studio
from gulbot.services.share_pages import (
    InvalidDraft,
    InviteDraft,
    PageLimitReached,
    VenueDraft,
    event_window,
)
from gulbot.web import links, render, strings

log = logging.getLogger("gulbot.web.studio")

PREFIX: Final = "/studio"
COOKIE: Final = "gb_studio"
PUBLIC_ROUTES: Final = frozenset({("GET", "/studio/enter/{token}"), ("POST", "/studio/enter")})

KEY_STUDIO_SESSIONS: Final[web.AppKey[async_sessionmaker[AsyncSession]]] = web.AppKey(
    "studio_sessions"
)
KEY_CREATOR: Final[web.RequestKey[studio.Creator]] = web.RequestKey(
    "studio_creator", studio.Creator
)

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]

#: The page languages, as the form names them.
LANGUAGE_NAMES: Final = {"uz": "O‘zbekcha", "uz_cyrl": "Ўзбекча", "ru": "Русский", "en": "English"}
#: What the creator sees for each kind of place (the page shows strings.VENUE_LABELS).
VENUE_CHIPS: Final = {
    "toyxona": "To‘yxona",
    "restoran": "Restoran",
    "kafe": "Kafe",
    "bog": "Bog‘",
    "uy": "Uy",
    "boshqa": "Boshqa",
}
#: The time a fresh form proposes.
DEFAULT_TIME: Final = "18:00"


def is_studio_path(path: str) -> bool:
    return path == PREFIX or path.startswith(PREFIX + "/")


def _html(body: str, status: int = 200) -> web.Response:
    return web.Response(status=status, text=body, content_type="text/html", charset="utf-8")


def _ip(request: web.Request) -> str:
    from gulbot.web.app import client_address

    return client_address(request)


def _route_key(request: web.Request) -> tuple[str, str | None]:
    resource = request.match_info.route.resource
    return request.method, (resource.canonical if resource is not None else None)


def _denied(status: int = 401) -> web.Response:
    return _html(render.render("studio/denied.html", {}), status=status)


@web.middleware
async def studio_gate(request: web.Request, handler: Handler) -> web.StreamResponse:
    if not is_studio_path(request.path):
        return await handler(request)
    if KEY_STUDIO_SESSIONS not in request.app:
        raise web.HTTPNotFound()  # the studio is not configured in this app
    if _route_key(request) in PUBLIC_ROUTES:
        return await handler(request)
    async with request.app[KEY_STUDIO_SESSIONS]() as session:
        creator = await studio.load_session(session, request.cookies.get(COOKIE))
        if creator is None:
            if request.method == "GET":
                return _denied()
            raise web.HTTPForbidden(text="Forbidden")
        if request.method != "GET":
            form = await request.post()
            submitted = form.get("csrf")
            if not studio.csrf_ok(creator, submitted if isinstance(submitted, str) else None):
                await studio.audit(
                    session,
                    shop_id=creator.shop_id,
                    action="csrf_refused",
                    customer_id=creator.customer_id,
                    reason=request.path,
                    ip=_ip(request),
                )
                await session.commit()
                raise web.HTTPForbidden(text="Forbidden")
    request[KEY_CREATOR] = creator
    return await handler(request)


# --- getting in and out -------------------------------------------------------


async def enter_page(request: web.Request) -> web.Response:
    """The link itself. A GET never spends it: Telegram's link-preview fetcher
    and any other robot reading the link must not burn the creator's way in."""
    from gulbot.web.app import limit

    limit(request, "studio_login")
    token = request.match_info["token"]
    if not studio.TOKEN_RE.match(token):
        return _denied()
    return _html(render.render("studio/enter.html", {"token": token}))


async def enter(request: web.Request) -> web.Response:
    from gulbot.web.app import KEY_SETTINGS, limit

    limit(request, "studio_login")
    form = await request.post()
    token = form.get("token")
    if not isinstance(token, str) or not studio.TOKEN_RE.match(token):
        return _denied()
    async with request.app[KEY_STUDIO_SESSIONS]() as session:
        opened = await studio.consume_link(session, token, ip=_ip(request))
        await session.commit()
    if opened is None:
        return _denied()
    response = web.HTTPSeeOther(PREFIX)
    response.set_cookie(
        COOKIE,
        opened.token,
        path=PREFIX,
        max_age=int(studio.SESSION_TTL.total_seconds()),
        httponly=True,
        secure=request.app[KEY_SETTINGS].secure,
        samesite="Lax",
    )
    raise response


async def logout(request: web.Request) -> web.Response:
    async with request.app[KEY_STUDIO_SESSIONS]() as session:
        await studio.end_session(session, request[KEY_CREATOR], ip=_ip(request))
        await session.commit()
    response = _html(render.render("studio/bye.html", {}))
    response.del_cookie(COOKIE, path=PREFIX)
    return response


# --- the form -------------------------------------------------------------------


@dataclass
class VenueRow:
    kind: str = "toyxona"
    name: str = ""
    address: str = ""
    map_url: str = ""
    time: str = ""
    error: str | None = None


@dataclass
class FormState:
    """What the creator typed, kept as typed so the form can be shown again."""

    lang: str = "uz"
    event_type: str = "wedding"
    name_1: str = ""
    name_2: str = ""
    event_date: str = ""
    event_time: str = DEFAULT_TIME
    message: str = ""
    rsvp: bool = True
    template: str = "milliy"
    venues: list[VenueRow] = field(default_factory=lambda: [VenueRow()])
    errors: dict[str, str] = field(default_factory=dict)


def _text(form: MultiDictProxy[Any], key: str, limit: int = 400) -> str:
    value = form.get(key)
    return value[: limit * 2] if isinstance(value, str) else ""


def read_form(form: MultiDictProxy[Any]) -> FormState:
    """The posted form as typed. Never raises: what cannot be read is kept as
    text and refused later, next to its field."""
    state = FormState(
        lang=_text(form, "lang", 8),
        event_type=_text(form, "event_type", 16),
        name_1=_text(form, "name_1", NAME_MAX),
        name_2=_text(form, "name_2", NAME_MAX),
        event_date=_text(form, "event_date", 10),
        event_time=_text(form, "event_time", 5),
        message=_text(form, "message", MESSAGE_MAX),
        rsvp=form.get("rsvp") == "1",
        template=_text(form, "template", 16),
        venues=[],
    )
    raw_count = _text(form, "venue_count", 2)
    count = min(int(raw_count), VENUES_MAX) if raw_count.isdigit() else 1
    for n in range(1, max(count, 1) + 1):
        state.venues.append(
            VenueRow(
                kind=_text(form, f"venue_kind_{n}", 16),
                name=_text(form, f"venue_name_{n}", VENUE_NAME_MAX),
                address=_text(form, f"venue_address_{n}", VENUE_ADDRESS_MAX),
                map_url=_text(form, f"venue_map_{n}", 300),
                time=_text(form, f"venue_time_{n}", 5),
            )
        )
    return state


def _parse_time(value: str) -> time | None:
    try:
        return time.fromisoformat(value) if value else None
    except ValueError:
        return None


def to_draft(state: FormState, *, today: date) -> InviteDraft | None:
    """The form as an InviteDraft, or None with `state.errors` / row errors
    filled in Uzbek, field by field. The service checks everything again."""
    errors = state.errors
    if state.lang not in PAGE_LANGUAGES:
        errors["lang"] = "Tilni tanlang."
    if state.event_type not in EVENT_TYPES:
        errors["event_type"] = "Tadbir turini tanlang."
    if not state.name_1.strip():
        errors["name_1"] = "Ismni yozing."
    first, last = event_window(today)
    try:
        event_date = date.fromisoformat(state.event_date)
        if not first <= event_date <= last:
            errors["event_date"] = "Sana bugundan boshlab 12 oy ichida bo‘lsin."
    except ValueError:
        event_date = first
        errors["event_date"] = "Sanani tanlang."
    event_time = _parse_time(state.event_time)
    if event_time is None:
        errors["event_time"] = "Vaqtni tanlang."
    if state.template not in render.THEME_NAMES:
        errors["template"] = "Dizaynni tanlang."
    venues: list[VenueDraft] = []
    for row in state.venues:
        if not (row.name.strip() or row.address.strip() or row.map_url.strip()):
            continue  # an empty row is not a place
        if row.kind not in VENUE_KINDS:
            row.error = "Joy turini tanlang."
        elif not row.name.strip():
            row.error = "Joy nomini yozing."
        elif row.time and _parse_time(row.time) is None:
            row.error = "Vaqtni tanlang."
        else:
            try:
                share_pages.clean_map_url(row.map_url)
            except InvalidDraft:
                row.error = "Xarita havolasi Google, Yandex yoki 2GIS dan bo‘lsin (https://…)."
        venues.append(
            VenueDraft(
                kind=row.kind,
                name=row.name,
                address=row.address or None,
                map_url=row.map_url or None,
                starts_at=_parse_time(row.time),
            )
        )
    if not venues:
        errors["venues"] = "Kamida bitta joy yozing."
    if errors or any(row.error for row in state.venues) or event_time is None:
        return None
    return InviteDraft(
        template=state.template,
        lang=state.lang,
        event_type=state.event_type,
        name_1=state.name_1,
        name_2=state.name_2 or None,
        event_date=event_date,
        event_time=event_time,
        venue="",
        location=None,
        message=state.message or None,
        rsvp_enabled=state.rsvp,
        venues=tuple(venues),
    )


async def _designs(session: AsyncSession, creator: studio.Creator) -> list[dict[str, Any]]:
    """Every design, as the picker shows it: free ones first, premium marked,
    and locked unless THIS customer has the CP18 gift at THIS shop."""
    unlocked = await premium.unlocked(
        session, shop_id=creator.shop_id, customer_id=creator.customer_id
    )
    cards = [
        {
            "key": key,
            "name": name,
            "premium": premium.is_premium_template(key),
            "locked": premium.is_premium_template(key) and not unlocked,
            "thumb": f"studio/thumbs/{key}.webp",
        }
        for key, name in render.THEME_NAMES.items()
    ]
    return sorted(cards, key=lambda card: card["premium"])


def _today() -> date:
    return datetime.now(UTC).astimezone(TASHKENT).date()


async def _form_view(
    request: web.Request, session: AsyncSession, state: FormState, **extra: Any
) -> dict[str, Any]:
    creator = request[KEY_CREATOR]
    first, last = event_window(_today())
    return {
        "creator": creator,
        "csrf": creator.csrf,
        "state": state,
        "designs": await _designs(session, creator),
        "languages": LANGUAGE_NAMES,
        "events": {key: strings.event_label(key, "uz") for key in EVENT_TYPES},
        "chips": VENUE_CHIPS,
        "venues_max": VENUES_MAX,
        "date_min": first.isoformat(),
        "date_max": last.isoformat(),
        "locked_text": strings_locked(),
        **extra,
    }


def strings_locked() -> str:
    """The existing "how to unlock" wording (CP18), not a new one."""
    from gulbot.i18n import t

    return t("premium.locked", "uz")


async def form_screen(request: web.Request) -> web.Response:
    async with request.app[KEY_STUDIO_SESSIONS]() as session:
        view = await _form_view(request, session, FormState())
    return _html(render.render("studio/form.html", view))


async def create(request: web.Request) -> web.Response:
    creator = request[KEY_CREATOR]
    form = await request.post()
    state = read_form(form)
    action = _text(form, "action", 16)
    async with request.app[KEY_STUDIO_SESSIONS]() as session:
        if action == "add_venue":
            if len(state.venues) < VENUES_MAX:
                state.venues.append(VenueRow())
            return _html(
                render.render("studio/form.html", await _form_view(request, session, state))
            )
        if action.startswith("remove_") and action[7:].isdigit():
            index = int(action[7:]) - 1
            if 0 <= index < len(state.venues) and len(state.venues) > 1:
                del state.venues[index]
            return _html(
                render.render("studio/form.html", await _form_view(request, session, state))
            )
        draft = to_draft(state, today=_today())
        if draft is None:
            view = await _form_view(
                request, session, state, problem="Belgilangan joylarni to‘g‘rilang."
            )
            return _html(render.render("studio/form.html", view), status=422)
        try:
            page = await share_pages.create_page(
                session,
                shop_id=creator.shop_id,
                customer_id=creator.customer_id,
                bot_username=creator.bot_username,
                draft=draft,
            )
        except premium.PremiumLocked:
            state.errors["template"] = strings_locked()
            view = await _form_view(request, session, state, problem=strings_locked())
            return _html(render.render("studio/form.html", view), status=422)
        except PageLimitReached as reached:
            n = (
                share_pages.CREATE_PER_DAY
                if reached.which == "daily"
                else share_pages.LIVE_PER_CUSTOMER
            )
            problem = (
                f"Bugun {n} ta sahifa yaratildi — ertaga yana urinib ko‘ring."
                if reached.which == "daily"
                else f"Bir vaqtda {n} tagacha sahifa bo‘ladi — avval eskisini o‘chiring."
            )
            view = await _form_view(request, session, state, problem=problem)
            return _html(render.render("studio/form.html", view), status=422)
        except InvalidDraft:
            view = await _form_view(
                request, session, state, problem="Belgilangan joylarni to‘g‘rilang."
            )
            return _html(render.render("studio/form.html", view), status=422)
        await studio.audit(
            session,
            shop_id=creator.shop_id,
            action="page_created",
            customer_id=creator.customer_id,
            detail={"page_id": page.id, "template": page.template},
            ip=_ip(request),
        )
        await session.commit()
        page_id = page.id
    raise web.HTTPSeeOther(f"{PREFIX}/done/{page_id}")


def _preview_draft(state: FormState, today: date) -> InviteDraft | None:
    """For "Ko'rish": the creator's data, with sample text standing in for
    what is not written yet, so every design can be seen before the end."""
    filled = FormState(
        lang=state.lang if state.lang in PAGE_LANGUAGES else "uz",
        event_type=state.event_type if state.event_type in EVENT_TYPES else "wedding",
        name_1=state.name_1.strip() or "Aziz",
        name_2=state.name_2 if state.name_1.strip() else "Malika",
        event_date=state.event_date or (today + timedelta(days=30)).isoformat(),
        event_time=state.event_time or DEFAULT_TIME,
        message=state.message,
        rsvp=state.rsvp,
        template=state.template,
        venues=[row for row in state.venues if row.name.strip()] or [VenueRow(name="To‘yxona")],
    )
    return to_draft(filled, today=today)


async def preview(request: web.Request) -> web.Response:
    """The real page template with the creator's own data. Written inside a
    savepoint and ALWAYS rolled back: nothing is saved, nothing is counted
    against the limits, no link exists. Premium designs may be looked at."""
    creator = request[KEY_CREATOR]
    form = await request.post()
    state = read_form(form)
    chosen = _text(form, "preview_template", 16)
    if chosen:
        state.template = chosen
    draft = _preview_draft(state, _today())
    async with request.app[KEY_STUDIO_SESSIONS]() as session:
        if draft is None:
            view = await _form_view(
                request, session, state, problem="Ko‘rish uchun belgilangan joylarni to‘g‘rilang."
            )
            return _html(render.render("studio/form.html", view), status=422)
        try:
            checked = await share_pages.checked_draft(
                session,
                shop_id=creator.shop_id,
                customer_id=creator.customer_id,
                bot_username=None,
                draft=draft,
                now=datetime.now(UTC),
            )
        except InvalidDraft:
            view = await _form_view(
                request, session, state, problem="Ko‘rish uchun belgilangan joylarni to‘g‘rilang."
            )
            return _html(render.render("studio/form.html", view), status=422)
        shop_name, tz_name = await share_pages.shop_brand(session, shop_id=creator.shop_id)
        savepoint = await session.begin_nested()
        try:
            page = SharePage(token=share_pages.new_token(), **checked.values)
            session.add(page)
            await session.flush()
            await session.refresh(page)
            body = render.page_html(
                page,
                render.Branding(shop_name=shop_name, cta_url=None),
                tz_name=tz_name,
                base=f"{PREFIX}/preview",
                venues=render.venue_lines(checked.venues, page.lang),
            )
        finally:
            await savepoint.rollback()
            await session.rollback()
    return _html(body)


async def done(request: web.Request) -> web.Response:
    creator = request[KEY_CREATOR]
    raw = request.match_info["page_id"]
    if not raw.isdigit() or len(raw) > 18:
        raise web.HTTPNotFound()
    async with request.app[KEY_STUDIO_SESSIONS]() as session:
        page = await share_pages.get_own_page(
            session, shop_id=creator.shop_id, customer_id=creator.customer_id, page_id=int(raw)
        )
        if page is None:
            raise web.HTTPNotFound()
        view = {"csrf": creator.csrf, "creator": creator, "url": links.page_url(page.token)}
    return _html(render.render("studio/done.html", view))


def add_routes(app: web.Application, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
    app[KEY_STUDIO_SESSIONS] = session_factory
    app.router.add_get(PREFIX + "/enter/{token}", enter_page)
    app.router.add_post(PREFIX + "/enter", enter)
    app.router.add_post(PREFIX + "/logout", logout)
    app.router.add_get(PREFIX, form_screen)
    app.router.add_post(PREFIX + "/create", create)
    app.router.add_post(PREFIX + "/preview", preview)
    app.router.add_get(PREFIX + "/done/{page_id}", done)
