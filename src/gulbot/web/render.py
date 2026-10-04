"""Page HTML, from a page row to the dict the templates read as `v`.

AUTOESCAPE IS ON for every template and nothing is marked safe, so a name
like `<script>` is printed as text. The JSON that carries the Yo'q button's
lines sits inside an attribute and is escaped there as well. The only strings
that reach a template without coming from our own tables are what customers
typed, and they go through exactly the same `{{ }}` as everything else.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any, Final
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from gulbot.models.share_page import PageKind, SharePage
from gulbot.web import strings

WEB_ROOT: Final = Path(__file__).resolve().parent
TEMPLATES: Final = WEB_ROOT / "templates"
STATIC: Final = WEB_ROOT / "static"

#: <meta name="theme-color"> per design: the browser chrome around the page.
THEME_COLORS: Final = {
    "milliy": "#f6efe2",
    "atlas": "#1f2f6b",
    "minimal": "#f4f1ec",
    "bog": "#c9d8c0",
    "romantik": "#fde6ea",
    "oltin": "#f6efe2",
    "quvnoq": "#ffe9f2",
    "tungi": "#0b1026",
    "pastel": "#f1edfb",
    "konvert": "#e9e1f2",
    "foto": "#f4ebe6",
    "bold": "#efede6",
    "geometrik": "#f6f2e8",
    "akvarel": "#fdfbf7",
    "vintaj": "#e9dcc0",
    "oqqora": "#ffffff",
    "bolalar": "#dff3ff",
    "suzani": "#f3e8d4",
    "neon": "#0b0b12",
    "deco": "#0f3b3a",
}

#: Display names, for the gallery and the bot's picker.
THEME_NAMES: Final = {
    "milliy": "Milliy naqsh",
    "atlas": "Atlas",
    "minimal": "Minimal",
    "bog": "Bog'",
    "romantik": "Romantik",
    "oltin": "Oltin",
    "quvnoq": "Quvnoq",
    "tungi": "Tungi",
    "pastel": "Pastel",
    "konvert": "Konvert",
    "foto": "Foto",
    "bold": "Bold",
    "geometrik": "Geometrik",
    "akvarel": "Akvarel",
    "vintaj": "Vintaj",
    "oqqora": "Oq-qora",
    "bolalar": "Bolalar",
    "suzani": "Suzani",
    "neon": "Neon",
    "deco": "Deco",
}


@cache
def _static_version(relative: str) -> str:
    """A content hash, so a changed file gets a new URL and the old one can
    be cached for a year."""
    return hashlib.sha256((STATIC / relative).read_bytes()).hexdigest()[:10]


def static_url(relative: str) -> str:
    return f"/static/{relative}?v={_static_version(relative)}"


@cache
def environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html"], default=True, default_for_string=True),
        undefined=StrictUndefined,
        trim_blocks=False,
        lstrip_blocks=False,
    )
    env.globals["static"] = static_url
    return env


def render(template: str, v: dict[str, Any]) -> str:
    return environment().get_template(template).render(v=v)


def _initial(name: str) -> str:
    for ch in name:
        if ch.isalnum():
            return ch.upper()
    return "G"


@dataclass(frozen=True)
class Branding:
    """Whose page this is. `cta_url` None means no link back (a demo, or a
    shop whose bot username is not known)."""

    shop_name: str
    cta_url: str | None


def _common(theme: str, lang: str, branding: Branding) -> dict[str, Any]:
    s = strings.all_text(lang)
    return {
        "html_lang": strings.HTML_LANG[lang],
        "theme": theme,
        "theme_color": THEME_COLORS[theme],
        "s": s,
        "shop": {"name": branding.shop_name, "initial": _initial(branding.shop_name)},
        "cta_url": branding.cta_url,
        "made_with": s["made_with"].format(shop=branding.shop_name),
        "seal_letter": None,
        "photo_url": None,
        #: The Foto design without a photo: a heart on a Ha/Yo'q page, the
        #: couple's initials on an invitation (invite_view) -- never the
        #: shop's letter, which would put the florist in the frame.
        "monogram": "♥",
    }


@dataclass(frozen=True)
class Plan:
    """A Ha/Yo'q page's date plan, ready to render: (id, label) pairs."""

    places: list[tuple[int, str]]
    slots: list[tuple[int, str]]


def chosen_line(page: SharePage, tz_name: str) -> str | None:
    if page.chosen_place is None or page.chosen_slot_at is None:
        return None
    return strings.text("plan_chosen", page.lang).format(
        place=page.chosen_place, when=strings.slot_text(page.chosen_slot_at, page.lang, tz_name)
    )


def yesno_view(
    page: SharePage,
    branding: Branding,
    *,
    yes_url: str,
    choose_url: str = "",
    plan: Plan | None = None,
    tz_name: str = "Asia/Tashkent",
) -> dict[str, Any]:
    lang = page.lang
    v = _common(page.template, lang, branding)
    question = page.question or ""
    v |= {
        "title": v["s"]["og_yesno"],
        "og_title": v["s"]["og_yesno"],
        # The preview Telegram draws in the chat must not give the question away.
        "og_description": v["s"]["og_yesno_desc"],
        "question": question,
        "yes_url": yes_url,
        "no_lines_json": json.dumps(list(strings.NO_LINES[lang]), ensure_ascii=False),
        "celebration": strings.celebration(page.question_preset or "custom", lang),
        "plan": plan if plan is not None and plan.places and plan.slots else None,
        "choose_url": choose_url,
        "chosen": chosen_line(page, tz_name),
    }
    return v


def event_instant(event_date: date, event_time: time, tz_name: str) -> datetime:
    return datetime.combine(event_date, event_time, tzinfo=ZoneInfo(tz_name))


def map_links(lat: Decimal | None, lon: Decimal | None) -> dict[str, str] | None:
    if lat is None or lon is None:
        return None
    la, lo = f"{float(lat):.6f}", f"{float(lon):.6f}"
    return {
        "google": f"https://www.google.com/maps/search/?api=1&query={la},{lo}",
        "yandex": f"https://yandex.uz/maps/?pt={lo},{la}&z=16&l=map",
    }


def invite_view(
    page: SharePage, branding: Branding, *, tz_name: str, rsvp_url: str, ics_url: str
) -> dict[str, Any]:
    lang = page.lang
    v = _common(page.template, lang, branding)
    assert page.event_type and page.event_date and page.event_time
    when = event_instant(page.event_date, page.event_time, tz_name)
    names = page.name_1 or ""
    if page.name_2:
        names = f"{names} & {page.name_2}"
    label = page.title or strings.event_label(page.event_type, lang)
    month_year = f"{strings.MONTHS[lang][when.month - 1]} {when.year}"
    v |= {
        "title": f"{label} · {names}",
        "og_title": f"{label} · {names}",
        "og_description": f"{strings.text('og_invite_desc', lang)} · {when.day} {month_year}",
        "event_label": label,
        "name_1": page.name_1 or "",
        "name_2": page.name_2,
        "message": page.message or strings.event_message(page.event_type, lang),
        "weekday": strings.WEEKDAYS[lang][when.weekday()],
        "day": when.day,
        "time": when.strftime("%H:%M"),
        "month_year": month_year,
        "iso": when.isoformat(),
        "venue": page.venue or "",
        "map": map_links(page.location_lat, page.location_lon),
        "ics_url": ics_url,
        "rsvp": page.rsvp_enabled,
        "rsvp_url": rsvp_url,
        "details": [
            {"label": v["s"][field], "text": value}
            for field, value in (
                ("dress_code", page.dress_code),
                ("program", page.program),
                ("contact", page.contact),
            )
            if value
        ],
        "closing": page.closing or strings.event_closing(page.event_type, lang),
        "seal_letter": _initial(page.name_1 or ""),
        "monogram": _initial(page.name_1 or "")
        + (f"&{_initial(page.name_2)}" if page.name_2 else ""),
    }
    return v


def gone_view(theme: str, lang: str, branding: Branding) -> dict[str, Any]:
    v = _common(theme, lang, branding)
    v |= {
        "title": v["s"]["gone_title"],
        "og_title": v["s"]["gone_title"],
        "og_description": v["s"]["gone_text"],
    }
    return v


def gallery_view(kind: str, lang: str) -> dict[str, Any]:
    v = _common("minimal", lang, Branding(shop_name=SAMPLE_SHOP, cta_url=None))
    title = {"uz": "Dizaynlar", "uz_cyrl": "Дизайнлар", "ru": "Дизайны", "en": "Designs"}[lang]
    kind_label = {
        "yesno": {"uz": "Ha / Yo'q", "uz_cyrl": "Ҳа / Йўқ", "ru": "Да / Нет", "en": "Yes / No"},
        "invite": {
            "uz": "Taklifnoma",
            "uz_cyrl": "Таклифнома",
            "ru": "Приглашение",
            "en": "Invitation",
        },
    }[kind][lang]
    v |= {
        "title": f"{kind_label} · {title}",
        "og_title": f"{kind_label} · {title}",
        "og_description": title,
        "gallery_kind": kind_label,
        "gallery_title": title,
        "entries": [
            {"href": f"/demo/{kind}/{theme}?lang={lang}", "name": THEME_NAMES[theme]}
            for theme in THEME_NAMES
        ],
    }
    return v


def page_html(
    page: SharePage, branding: Branding, *, tz_name: str, base: str, plan: Plan | None = None
) -> str:
    """The live page. `base` is "/p/<token>", the root of its own endpoints."""
    if page.kind == PageKind.YESNO:
        view = yesno_view(
            page,
            branding,
            yes_url=f"{base}/yes",
            choose_url=f"{base}/choose",
            plan=plan,
            tz_name=tz_name,
        )
        return render("yesno.html", view)
    return render(
        "invite.html",
        invite_view(
            page, branding, tz_name=tz_name, rsvp_url=f"{base}/rsvp", ics_url=f"{base}/event.ics"
        ),
    )


# --- calendar file ------------------------------------------------------------


def _ics_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """RFC 5545: lines over 75 octets continue on the next line after a space."""
    out, current = [], b""
    for ch in line:
        encoded = ch.encode()
        if len(current) + len(encoded) > 75:
            out.append(current.decode())
            current = b" "
        current += encoded
    out.append(current.decode())
    return "\r\n".join(out)


def ics(page: SharePage, *, tz_name: str, page_url: str, now: datetime | None = None) -> str:
    assert page.event_type and page.event_date and page.event_time
    now = now or datetime.now(UTC)
    start = event_instant(page.event_date, page.event_time, tz_name).astimezone(UTC)
    end = start + timedelta(hours=4)
    fmt = "%Y%m%dT%H%M%SZ"
    lang = page.lang
    names = page.name_1 or ""
    if page.name_2:
        names = f"{names} & {page.name_2}"
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Gulbot//Taklifnoma//UZ",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{page.id}-{start.strftime(fmt)}@gulbot",
        f"DTSTAMP:{now.strftime(fmt)}",
        f"DTSTART:{start.strftime(fmt)}",
        f"DTEND:{end.strftime(fmt)}",
        f"SUMMARY:{_ics_escape(strings.event_label(page.event_type, lang) + ': ' + names)}",
        f"LOCATION:{_ics_escape(page.venue or '')}",
        f"DESCRIPTION:{_ics_escape(page.message or strings.event_message(page.event_type, lang))}",
        f"URL:{page_url}",
    ]
    if page.location_lat is not None and page.location_lon is not None:
        lines.append(f"GEO:{float(page.location_lat):.6f};{float(page.location_lon):.6f}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


# --- samples, for the gallery and the screenshots -------------------------------

SAMPLE_SHOP: Final = "Namuna"


def sample_plan(lang: str, tz_name: str = "Asia/Tashkent") -> Plan:
    """Three places and three evenings, for the gallery and the screenshots."""
    places = {
        "uz": ("Kino", "Bog'da sayr", "Choyxona"),
        "uz_cyrl": ("Кино", "Боғда сайр", "Чойхона"),
        "ru": ("Кино", "Прогулка в парке", "Чайхана"),
        "en": ("Cinema", "A walk in the park", "Tea house"),
    }[lang]
    base = datetime.now(ZoneInfo(tz_name)).replace(hour=19, minute=0, second=0, microsecond=0)
    slots = [base + timedelta(days=d) for d in (2, 3, 5)]
    return Plan(
        places=list(enumerate(places, start=1)),
        slots=[(10 + n, strings.slot_text(s, lang, tz_name)) for n, s in enumerate(slots)],
    )


def sample_page(kind: str, theme: str, lang: str, *, event_type: str = "wedding") -> SharePage:
    """A page that exists nowhere but in this response."""
    today = datetime.now(UTC).date()
    if kind == PageKind.YESNO:
        return SharePage(
            id=0,
            kind=kind,
            template=theme,
            lang=lang,
            question_preset="marry",
            question=strings.question("marry", lang),
        )
    couple = event_type in strings.COUPLE_EVENTS
    cyrillic = lang in ("uz_cyrl", "ru")
    first, second = ("Азиз", "Малика") if cyrillic else ("Aziz", "Malika")
    venue = {
        "uz": "Toshkent, «Navro'z» to'yxonasi",
        "uz_cyrl": "Тошкент, «Наврўз» тўйхонаси",
        "ru": "Ташкент, ресторан «Навруз»",
        "en": "Navruz Banquet Hall, Tashkent",
    }[lang]
    return SharePage(
        id=0,
        kind=kind,
        template=theme,
        lang=lang,
        event_type=event_type,
        name_1=first if couple else second,
        name_2=second if couple else None,
        event_date=today + timedelta(days=45),
        event_time=time(18, 0),
        venue=venue,
        location_lat=Decimal("41.311081"),
        location_lon=Decimal("69.240562"),
        message=None,
        rsvp_enabled=True,
    )
