"""Taklifnoma Studio, under /studio on the page server (CP27).

    GET  /studio/enter/<token>         the link from the SHOP's bot: a "Kirish" button
    POST /studio/enter                 spends the link, opens a session for its customer
    POST /studio/logout
    GET  /studio[?kind=...]            ONE form for a taklifnoma, Ha/Yo'q or Uzrnoma
    POST /studio/create                "Joy qo'shish" / "O'chirish" (the form again) or create
    POST /studio/design                the design picker, its own screen (CP27.1b)
    POST /studio/preview               the page with the creator's own data, never saved
    GET  /studio/done/<page_id>        the new page's link, and its photos (CP27.2)
    POST /studio/page/<id>/photo       add a photo (premium; multipart, CSRF in the query)
    POST /studio/page/<id>/photos/clear

ONE GATE FOR EVERY ROUTE (`studio_gate`), as for /admin and /shop: a live
session or 401, every POST carries the session's CSRF token, and entitlement
(services/studio.entitled) is re-checked on every request. tests walk the
router, so a route added later cannot be forgotten. A photo upload is the one
multipart POST: the gate must not read its body (the app caps bodies at 4 KB),
so its token travels in the query string of the form's own action, which is
same-origin and never sent as a Referer (Referrer-Policy: no-referrer).

NO ROUTE TAKES A SHOP OR A CUSTOMER. Every write uses request[KEY_CREATOR],
which only the bot that minted the link can set; a page id in a path is only
ever looked up as this creator's own page in this shop.

THE RULES ARE THE BOT'S. A page is made by share_pages.create_page -- the same
validation (checked_draft), premium wall and limits as the bot's wizard -- the
preview renders the real template inside a savepoint that is always rolled
back, and a photo goes through share_page_photos.store_photo (premium, size,
re-encoding, the per-kind limit) after its size is checked BEFORE it is read.

No JavaScript is needed. studio.js only adds the copy button. Cookie:
HttpOnly, SameSite=Lax, Path=/studio, Secure whenever the site is https.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from typing import Any, Final
from zoneinfo import ZoneInfo

from aiohttp import BodyPartReader, web
from multidict import MultiDictProxy
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gulbot.config import TASHKENT
from gulbot.models.share_page import (
    EVENT_TYPES,
    MUSIC_TRACKS,
    QUESTION_PRESETS,
    VENUES_MAX,
    PageKind,
    SharePage,
)
from gulbot.services import premium, share_page_photos, share_pages, studio
from gulbot.services.share_pages import InvalidDraft, PageLimitReached, event_window
from gulbot.web import links, render, strings, studio_designs
from gulbot.web.studio_form import (
    KINDS,
    PLAN_ROWS,
    FormState,
    VenueRow,
    fresh_state,
    preview_draft,
    read_form,
    text_of,
    to_draft,
)

log = logging.getLogger("gulbot.web.studio")

PREFIX: Final = "/studio"
COOKIE: Final = "gb_studio"
PUBLIC_ROUTES: Final = frozenset({("GET", "/studio/enter/{token}"), ("POST", "/studio/enter")})
#: The one route whose body is multipart: its CSRF token is in the query string.
UPLOAD_ROUTES: Final = frozenset({("POST", "/studio/page/{page_id}/photo")})
#: A photo upload's whole body: the photo's own cap plus room for the form.
UPLOAD_MAX_BYTES: Final = share_page_photos.MAX_INPUT_BYTES + 64 * 1024

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
FIX_FIELDS: Final = "Belgilangan joylarni to‘g‘rilang."


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


async def _submitted_csrf(request: web.Request) -> str | None:
    if _route_key(request) in UPLOAD_ROUTES:
        token = request.query.get("csrf")
    else:
        token = (await request.post()).get("csrf")  # type: ignore[assignment]
    return token if isinstance(token, str) else None


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
        if request.method != "GET" and not studio.csrf_ok(creator, await _submitted_csrf(request)):
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


def strings_locked() -> str:
    """The existing "how to unlock" wording (CP18), not a new one."""
    from gulbot.i18n import t

    return t("premium.locked", "uz")


def _track_names() -> dict[str, str]:
    from gulbot.i18n import t

    return {track: t(f"pages.track_{track}", "uz") for track in MUSIC_TRACKS}


async def _form_view(
    request: web.Request, session: AsyncSession, state: FormState, **extra: Any
) -> dict[str, Any]:
    creator = request[KEY_CREATOR]
    first, last = event_window(_today())
    designs = await _designs(session, creator)
    chosen = next((d for d in designs if d["key"] == state.template), None)
    unlocked = await premium.unlocked(
        session, shop_id=creator.shop_id, customer_id=creator.customer_id
    )
    return {
        "creator": creator,
        "csrf": creator.csrf,
        "state": state,
        "kinds": KINDS,
        # CP27.1b: the form carries ONE design card; the forty live on /studio/design.
        "chosen": chosen,
        "languages": LANGUAGE_NAMES,
        "events": {key: strings.event_label(key, "uz") for key in EVENT_TYPES},
        "questions": {
            key: (strings.question(key, "uz") if key != "custom" else "O‘z savolim")
            for key in QUESTION_PRESETS
        },
        "tracks": _track_names(),
        "premium_open": unlocked,
        "chips": VENUE_CHIPS,
        "venues_max": VENUES_MAX,
        "plan_rows": PLAN_ROWS,
        "date_min": first.isoformat(),
        "date_max": last.isoformat(),
        "locked_text": strings_locked(),
        **extra,
    }


async def _form(
    request: web.Request, session: AsyncSession, state: FormState, status: int = 200, **extra: Any
) -> web.Response:
    view = await _form_view(request, session, state, **extra)
    return _html(render.render("studio/form.html", view), status=status)


async def form_screen(request: web.Request) -> web.Response:
    async with request.app[KEY_STUDIO_SESSIONS]() as session:
        return await _form(request, session, fresh_state(request.query.get("kind", "")))


def _choice(form: MultiDictProxy[Any], key: str, current: str, allowed: dict[str, str]) -> str:
    """A filter value: the pressed button's, else the one already shown."""
    value = text_of(form, key, 16) or text_of(form, f"cur_{key}", 16)
    return value if value in allowed else current


async def design(request: web.Request) -> web.Response:
    """The design picker, its own screen (CP27.1b). Everything typed so far
    rides along in hidden fields; "choose" goes back to the same form."""
    creator = request[KEY_CREATOR]
    form = await request.post()
    state = read_form(form)
    async with request.app[KEY_STUDIO_SESSIONS]() as session:
        designs = await _designs(session, creator)
        chosen = text_of(form, "choose", 16)
        if chosen or "back" in form:
            if chosen:
                card = next((d for d in designs if d["key"] == chosen), None)
                if card is None or card["locked"]:
                    problem = strings_locked() if card is not None else "Dizaynni tanlang."
                    view = await _picker_view(request, form, state, designs, problem=problem)
                    return _html(render.render("studio/picker.html", view), status=422)
                state.template = chosen
            return await _form(request, session, state)
        view = await _picker_view(request, form, state, designs)
    return _html(render.render("studio/picker.html", view))


def _opening_category(state: FormState) -> str:
    if state.kind == PageKind.INVITE:
        return studio_designs.category_for_event(state.event_type)
    return "all"


async def _picker_view(
    request: web.Request,
    form: MultiDictProxy[Any],
    state: FormState,
    designs: list[dict[str, Any]],
    **extra: Any,
) -> dict[str, Any]:
    creator = request[KEY_CREATOR]
    categories = {"all": "Hammasi", **studio_designs.CATEGORIES}
    cat = _choice(form, "cat", _opening_category(state), categories)
    tier = _choice(form, "tier", "all", studio_designs.TIERS)
    shown = [
        d
        for d in designs
        if (cat == "all" or cat in studio_designs.DESIGN_CATEGORIES[d["key"]])
        and (tier == "all" or (tier == "premium") == d["premium"])
    ]
    return {
        "creator": creator,
        "csrf": creator.csrf,
        "state": state,
        "designs": shown,
        "categories": categories,
        "tiers": studio_designs.TIERS,
        "cat": cat,
        "tier": tier,
        "locked_text": strings_locked(),
        "any_locked": any(d["locked"] for d in shown),
        **extra,
    }


async def _shop_tz(session: AsyncSession, shop_id: int) -> ZoneInfo:
    _name, tz_name = await share_pages.shop_brand(session, shop_id=shop_id)
    return ZoneInfo(tz_name)


async def create(request: web.Request) -> web.Response:
    creator = request[KEY_CREATOR]
    form = await request.post()
    state = read_form(form)
    action = text_of(form, "action", 16)
    async with request.app[KEY_STUDIO_SESSIONS]() as session:
        if action == "add_venue":
            if len(state.venues) < VENUES_MAX:
                state.venues.append(VenueRow())
            return await _form(request, session, state)
        if action.startswith("remove_") and action[7:].isdigit():
            index = int(action[7:]) - 1
            if 0 <= index < len(state.venues) and len(state.venues) > 1:
                del state.venues[index]
            return await _form(request, session, state)
        tz = await _shop_tz(session, creator.shop_id)
        draft = to_draft(state, today=_today(), tz=tz, now=datetime.now(UTC))
        if draft is None:
            return await _form(request, session, state, 422, problem=FIX_FIELDS)
        try:
            page = await share_pages.create_page(
                session,
                shop_id=creator.shop_id,
                customer_id=creator.customer_id,
                bot_username=creator.bot_username,
                draft=draft,
            )
        except premium.PremiumLocked:
            await session.rollback()
            key = "music" if draft.music is not None else "template"
            state.errors[key] = strings_locked()
            return await _form(request, session, state, 422, problem=strings_locked())
        except PageLimitReached as reached:
            await session.rollback()
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
            return await _form(request, session, state, 422, problem=problem)
        except InvalidDraft:
            await session.rollback()
            return await _form(request, session, state, 422, problem=FIX_FIELDS)
        await studio.audit(
            session,
            shop_id=creator.shop_id,
            action="page_created",
            customer_id=creator.customer_id,
            detail={"page_id": page.id, "kind": page.kind, "template": page.template},
            ip=_ip(request),
        )
        await session.commit()
        page_id = page.id
    raise web.HTTPSeeOther(f"{PREFIX}/done/{page_id}")


async def preview(request: web.Request) -> web.Response:
    """The real page template with the creator's own data. Written inside a
    savepoint and ALWAYS rolled back: nothing is saved, nothing is counted
    against the limits, no link exists. Premium designs may be looked at."""
    creator = request[KEY_CREATOR]
    form = await request.post()
    state = read_form(form)
    chosen = text_of(form, "preview_template", 16)
    if chosen:
        state.template = chosen
    async with request.app[KEY_STUDIO_SESSIONS]() as session:
        shop_name, tz_name = await share_pages.shop_brand(session, shop_id=creator.shop_id)
        now = datetime.now(UTC)
        draft = preview_draft(state, today=_today(), tz=ZoneInfo(tz_name), now=now)
        if draft is None:
            problem = "Ko‘rish uchun belgilangan joylarni to‘g‘rilang."
            return await _form(request, session, state, 422, problem=problem)
        try:
            checked = await share_pages.checked_draft(
                session,
                shop_id=creator.shop_id,
                customer_id=creator.customer_id,
                bot_username=None,
                draft=draft,
                now=now,
            )
        except InvalidDraft:
            problem = "Ko‘rish uchun belgilangan joylarni to‘g‘rilang."
            return await _form(request, session, state, 422, problem=problem)
        savepoint = await session.begin_nested()
        try:
            page = SharePage(token=share_pages.new_token(), **checked.values)
            session.add(page)
            await session.flush()
            await session.refresh(page)
            places, slots = checked.plan
            plan = (
                render.Plan(
                    places=list(enumerate(places, start=1)),
                    slots=[
                        (n, strings.slot_text(slot, page.lang, tz_name))
                        for n, slot in enumerate(slots, start=1)
                    ],
                )
                if page.kind == PageKind.YESNO
                else None
            )
            body = render.page_html(
                page,
                render.Branding(shop_name=shop_name, cta_url=None),
                tz_name=tz_name,
                base=f"{PREFIX}/preview",
                plan=plan,
                venues=render.venue_lines(checked.venues, page.lang),
            )
        finally:
            await savepoint.rollback()
            await session.rollback()
    return _html(body)


# --- a made page: its link and its photos (CP27.2) ----------------------------------


def _page_id(request: web.Request) -> int:
    raw = request.match_info["page_id"]
    if not raw.isdigit() or len(raw) > 18:
        raise web.HTTPNotFound()
    return int(raw)


async def _done(
    request: web.Request,
    session: AsyncSession,
    page_id: int,
    status: int = 200,
    **extra: Any,
) -> web.Response:
    creator = request[KEY_CREATOR]
    page = await share_pages.get_own_page(
        session, shop_id=creator.shop_id, customer_id=creator.customer_id, page_id=page_id
    )
    if page is None:
        raise web.HTTPNotFound()
    view = {
        "csrf": creator.csrf,
        "creator": creator,
        "page_id": page.id,
        "kind": KINDS.get(page.kind, ""),
        "url": links.page_url(page.token),
        "photos": await share_page_photos.photo_count(session, page_id=page.id),
        "photo_limit": share_page_photos.photo_limit(page),
        "premium_open": await premium.unlocked(
            session, shop_id=creator.shop_id, customer_id=creator.customer_id
        ),
        "locked_text": strings_locked(),
        "max_mb": share_page_photos.MAX_INPUT_BYTES // (1024 * 1024),
        **extra,
    }
    return _html(render.render("studio/done.html", view), status=status)


async def done(request: web.Request) -> web.Response:
    page_id = _page_id(request)
    async with request.app[KEY_STUDIO_SESSIONS]() as session:
        return await _done(request, session, page_id)


async def _read_photo(request: web.Request) -> bytes | None:
    """The "photo" part, read at most MAX_INPUT_BYTES + 1 bytes: an oversize
    file is refused without being read to its end."""
    reader = await request.multipart()
    while True:
        part = await reader.next()
        if part is None:
            return None
        if not isinstance(part, BodyPartReader) or part.name != "photo":
            await part.release()
            continue
        chunks, total = [], 0
        while chunk := await part.read_chunk(64 * 1024):
            total += len(chunk)
            if total > share_page_photos.MAX_INPUT_BYTES:
                raise share_page_photos.PhotoRefused("size")
            chunks.append(chunk)
        return b"".join(chunks)


async def add_photo(request: web.Request) -> web.Response:
    creator = request[KEY_CREATOR]
    page_id = _page_id(request)
    async with request.app[KEY_STUDIO_SESSIONS]() as session:
        # SIZE BEFORE READ: the declared body is checked before a byte is read.
        length = request.content_length
        if length is None or length > UPLOAD_MAX_BYTES:
            problem = f"Surat {share_page_photos.MAX_INPUT_BYTES // (1024 * 1024)} MB dan oshmasin."
            return await _done(request, session, page_id, 413, problem=problem)
        try:
            raw = await _read_photo(request)
            if raw is None:
                return await _done(request, session, page_id, 422, problem="Suratni tanlang.")
            stored = await share_page_photos.store_photo(
                session,
                shop_id=creator.shop_id,
                customer_id=creator.customer_id,
                page_id=page_id,
                raw=raw,
            )
        except premium.PremiumLocked:
            await session.rollback()
            return await _done(request, session, page_id, 422, problem=strings_locked())
        except share_page_photos.GalleryFull:
            await session.rollback()
            problem = "Suratlar soni chegarasiga yetdi."
            return await _done(request, session, page_id, 422, problem=problem)
        except share_page_photos.PhotoRefused:
            await session.rollback()
            problem = "Bu faylni surat sifatida o‘qib bo‘lmadi yoki u juda katta."
            return await _done(request, session, page_id, 422, problem=problem)
        if stored is None:
            raise web.HTTPNotFound()
        await studio.audit(
            session,
            shop_id=creator.shop_id,
            action="photo_added",
            customer_id=creator.customer_id,
            detail={"page_id": page_id, "bytes": stored.size_bytes},
            ip=_ip(request),
        )
        await session.commit()
    raise web.HTTPSeeOther(f"{PREFIX}/done/{page_id}")


async def clear_photos(request: web.Request) -> web.Response:
    creator = request[KEY_CREATOR]
    page_id = _page_id(request)
    async with request.app[KEY_STUDIO_SESSIONS]() as session:
        cleared = await share_page_photos.clear_photos(
            session, shop_id=creator.shop_id, customer_id=creator.customer_id, page_id=page_id
        )
        if not cleared:
            raise web.HTTPNotFound()
        await session.commit()
    raise web.HTTPSeeOther(f"{PREFIX}/done/{page_id}")


def add_routes(app: web.Application, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
    app[KEY_STUDIO_SESSIONS] = session_factory
    app.router.add_get(PREFIX + "/enter/{token}", enter_page)
    app.router.add_post(PREFIX + "/enter", enter)
    app.router.add_post(PREFIX + "/logout", logout)
    app.router.add_get(PREFIX, form_screen)
    app.router.add_post(PREFIX + "/create", create)
    app.router.add_post(PREFIX + "/preview", preview)
    app.router.add_post(PREFIX + "/design", design)
    app.router.add_get(PREFIX + "/done/{page_id}", done)
    app.router.add_post(PREFIX + "/page/{page_id}/photo", add_photo)
    app.router.add_post(PREFIX + "/page/{page_id}/photos/clear", clear_photos)
