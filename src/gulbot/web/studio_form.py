"""The studio's one form, for every page kind (CP27.1, CP27.2).

What the creator typed is kept as typed (`FormState`) so the form, the design
picker and the preview can all show it again; `to_draft` turns it into the
same draft the bot builds, and share_pages.checked_draft / create_page apply
the rules. Errors are reported next to their field, in Uzbek.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo

from multidict import MultiDictProxy

from gulbot.models.share_page import (
    EVENT_TYPES,
    MESSAGE_MAX,
    MUSIC_TRACKS,
    NAME_MAX,
    PAGE_LANGUAGES,
    PLACE_MAX,
    QUESTION_MAX,
    QUESTION_PRESETS,
    VENUE_ADDRESS_MAX,
    VENUE_KINDS,
    VENUE_NAME_MAX,
    VENUES_MAX,
    PageKind,
)
from gulbot.services import share_pages
from gulbot.services.share_pages import (
    ApologyDraft,
    InvalidDraft,
    InviteDraft,
    VenueDraft,
    YesNoDraft,
    event_window,
)
from gulbot.web import render, strings

#: The kinds the studio makes, as its tabs name them.
KINDS: Final = {
    PageKind.INVITE.value: "Taklifnoma",
    PageKind.YESNO.value: "Ha / Yo‘q",
    PageKind.APOLOGY.value: "Uzrnoma",
}
#: A Ha/Yo'q page's date plan: the form offers this many places and times
#: (the service allows PLAN_MAX; three keeps the form short).
PLAN_ROWS: Final = 3
#: The time a fresh invitation proposes.
DEFAULT_TIME: Final = "18:00"


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

    kind: str = PageKind.INVITE.value
    lang: str = "uz"
    template: str = "milliy"
    music: str = ""
    # invitation
    event_type: str = "wedding"
    name_1: str = ""
    name_2: str = ""
    event_date: str = ""
    event_time: str = DEFAULT_TIME
    message: str = ""
    rsvp: bool = True
    venues: list[VenueRow] = field(default_factory=lambda: [VenueRow()])
    # Ha/Yo'q
    question_preset: str = "marry"
    question: str = ""
    notify: bool = True
    places: list[str] = field(default_factory=lambda: [""] * PLAN_ROWS)
    slots: list[str] = field(default_factory=lambda: [""] * PLAN_ROWS)
    # Uzrnoma
    letter: str = ""
    errors: dict[str, str] = field(default_factory=dict)


def text_of(form: MultiDictProxy[Any], key: str, limit: int = 400) -> str:
    value = form.get(key)
    return value[: limit * 2] if isinstance(value, str) else ""


def read_form(form: MultiDictProxy[Any]) -> FormState:
    """The posted form as typed. Never raises: what cannot be read is kept as
    text and refused later, next to its field."""
    kind = text_of(form, "kind", 8)
    state = FormState(
        kind=kind if kind in KINDS else PageKind.INVITE.value,
        lang=text_of(form, "lang", 8),
        template=text_of(form, "template", 16),
        music=text_of(form, "music", 16),
        event_type=text_of(form, "event_type", 16),
        name_1=text_of(form, "name_1", NAME_MAX),
        name_2=text_of(form, "name_2", NAME_MAX),
        event_date=text_of(form, "event_date", 10),
        event_time=text_of(form, "event_time", 5),
        message=text_of(form, "message", MESSAGE_MAX),
        rsvp=form.get("rsvp") == "1",
        venues=[],
        question_preset=text_of(form, "question_preset", 16),
        question=text_of(form, "question", QUESTION_MAX),
        notify=form.get("notify") == "1",
        places=[text_of(form, f"place_{n}", PLACE_MAX) for n in range(1, PLAN_ROWS + 1)],
        slots=[text_of(form, f"slot_{n}", 16) for n in range(1, PLAN_ROWS + 1)],
        letter=text_of(form, "letter", MESSAGE_MAX),
    )
    raw_count = text_of(form, "venue_count", 2)
    count = min(int(raw_count), VENUES_MAX) if raw_count.isdigit() else 1
    for n in range(1, max(count, 1) + 1):
        state.venues.append(
            VenueRow(
                kind=text_of(form, f"venue_kind_{n}", 16),
                name=text_of(form, f"venue_name_{n}", VENUE_NAME_MAX),
                address=text_of(form, f"venue_address_{n}", VENUE_ADDRESS_MAX),
                map_url=text_of(form, f"venue_map_{n}", 300),
                time=text_of(form, f"venue_time_{n}", 5),
            )
        )
    return state


def fresh_state(kind: str) -> FormState:
    return FormState(kind=kind if kind in KINDS else PageKind.INVITE.value)


def _parse_time(value: str) -> time | None:
    try:
        return time.fromisoformat(value) if value else None
    except ValueError:
        return None


def _common(state: FormState) -> str | None:
    """Checks every kind shares; returns the music track (or None)."""
    if state.lang not in PAGE_LANGUAGES:
        state.errors["lang"] = "Tilni tanlang."
    if state.template not in render.THEME_NAMES:
        state.errors["template"] = "Dizaynni tanlang."
    if state.music and state.music not in MUSIC_TRACKS:
        state.errors["music"] = "Musiqani ro‘yxatdan tanlang."
    return state.music or None


def _invite(state: FormState, today: date) -> InviteDraft | None:
    errors = state.errors
    music = _common(state)
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
        music=music,
    )


def _yesno(state: FormState, today: date, tz: ZoneInfo, now: datetime) -> YesNoDraft | None:
    errors = state.errors
    music = _common(state)
    if state.question_preset not in QUESTION_PRESETS:
        errors["question_preset"] = "Savolni tanlang."
        question = ""
    elif state.question_preset == "custom":
        question = state.question.strip()
        if not question:
            errors["question"] = "Savolingizni yozing."
    else:
        question = strings.question(state.question_preset, state.lang or "uz")
    places = tuple(p.strip() for p in state.places if p.strip())
    slots: list[datetime] = []
    first, last = event_window(today)
    for raw in state.slots:
        if not raw:
            continue
        try:
            moment = datetime.fromisoformat(raw).replace(tzinfo=tz)
        except ValueError:
            errors["slots"] = "Vaqtni tanlang."
            continue
        if moment <= now or not first <= moment.date() <= last:
            errors["slots"] = "Vaqtlar kelajakda, 12 oy ichida bo‘lsin."
        slots.append(moment)
    if bool(places) != bool(slots):
        errors["plan"] = "Uchrashuv rejasi uchun kamida bitta joy va bitta vaqt yozing."
    if len(set(places)) != len(places) or len(set(slots)) != len(slots):
        errors["plan"] = "Joylar va vaqtlar takrorlanmasin."
    if errors:
        return None
    return YesNoDraft(
        template=state.template,
        lang=state.lang,
        question_preset=state.question_preset,
        question=question,
        notify_creator=state.notify,
        places=places,
        slots=tuple(slots),
        music=music,
    )


def _apology(state: FormState) -> ApologyDraft | None:
    music = _common(state)
    if not state.letter.strip():
        state.errors["letter"] = "Maktubingizni yozing."
    if state.errors:
        return None
    return ApologyDraft(
        template=state.template,
        lang=state.lang,
        text=state.letter,
        notify_creator=state.notify,
        music=music,
    )


Draft = InviteDraft | YesNoDraft | ApologyDraft


def to_draft(state: FormState, *, today: date, tz: ZoneInfo, now: datetime) -> Draft | None:
    """The form as the bot's own draft for its kind, or None with errors filled
    in next to their fields. The service checks everything again."""
    if state.kind == PageKind.YESNO:
        return _yesno(state, today, tz, now)
    if state.kind == PageKind.APOLOGY:
        return _apology(state)
    return _invite(state, today)


def preview_draft(state: FormState, *, today: date, tz: ZoneInfo, now: datetime) -> Draft | None:
    """For "Ko'rish": the creator's data, with sample text standing in for what
    is not written yet, so every design can be seen before the end."""
    filled = FormState(**{**state.__dict__, "errors": {}, "venues": list(state.venues)})
    filled.lang = state.lang if state.lang in PAGE_LANGUAGES else "uz"
    filled.music = state.music if state.music in MUSIC_TRACKS else ""
    if filled.kind == PageKind.INVITE:
        filled.event_type = state.event_type if state.event_type in EVENT_TYPES else "wedding"
        if not state.name_1.strip():
            filled.name_1, filled.name_2 = "Aziz", "Malika"
        filled.event_date = state.event_date or (today + timedelta(days=30)).isoformat()
        filled.event_time = state.event_time or DEFAULT_TIME
        filled.venues = [row for row in state.venues if row.name.strip()] or [
            VenueRow(name="To‘yxona")
        ]
    elif filled.kind == PageKind.YESNO:
        if filled.question_preset not in QUESTION_PRESETS or (
            filled.question_preset == "custom" and not filled.question.strip()
        ):
            filled.question_preset = "marry"
        filled.places = [""] * PLAN_ROWS
        filled.slots = [""] * PLAN_ROWS
    else:
        filled.letter = state.letter.strip() or strings.question("forgive", filled.lang)
    return to_draft(filled, today=today, tz=tz, now=now)
