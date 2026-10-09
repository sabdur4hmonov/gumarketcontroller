"""Ha/Yo'q pages and taklifnomas: creating, finding, answering, deleting.

EVERY CUSTOMER-SIDE READ AND WRITE IS SCOPED BY (shop_id, customer_id). The bot
passes the shop its dispatcher is bound to and the customer the middleware
resolved, never a value from a callback. A page id that arrives in a button --
which a client can craft -- is only ever looked up together with those two, so
shop A's bot cannot open, count or delete a page of shop B's, or another
customer's page in the same shop. `tests/test_share_page_tenancy.py`.

THE PUBLIC SIDE IS SCOPED BY THE TOKEN, and only the token. It is 128 random
bits, it is the whole of the page's address, and it is never derived from an id.
A referral is the one place both meet: a token arriving in shop A's bot is
honoured only if the page belongs to shop A.

THE CREATION LIMIT is per customer, taken under an advisory lock so a double tap
cannot slip two pages past it: CREATE_PER_DAY in any rolling 24 hours, deleted
pages included (deleting is not a way round it), and LIVE_PER_CUSTOMER at once.
"""

from __future__ import annotations

import re
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Final
from zoneinfo import ZoneInfo

from sqlalchemy import and_, delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.models.customer import Customer
from gulbot.models.order import Order
from gulbot.models.share_page import (
    ANSWERABLE_KINDS,
    CLOSING_MAX,
    CONTACT_MAX,
    DRESS_CODE_MAX,
    EVENT_TYPES,
    GUEST_NAME_MAX,
    MAX_GUESTS,
    MESSAGE_MAX,
    MONOGRAM_MAX,
    MUSIC_TRACKS,
    NAME_MAX,
    PAGE_LANGUAGES,
    PAGE_TEMPLATES,
    PLACE_MAX,
    PLAN_MAX,
    PROGRAM_MAX,
    QUESTION_MAX,
    QUESTION_PRESETS,
    TITLE_MAX,
    VENUE_MAX,
    PageKind,
    SharePage,
    SharePageOption,
    SharePagePhoto,
    SharePageReferral,
    SharePageRsvp,
    SharePageWish,
)
from gulbot.models.shop import Shop, ShopStatus
from gulbot.services import premium
from gulbot.web import sections

#: Pages one customer may create in any rolling 24 hours, deleted ones included.
CREATE_PER_DAY: Final = 5
#: Live pages one customer may hold at once.
LIVE_PER_CUSTOMER: Final = 20
#: A Ha/Yo'q page answers one question; two months is plenty to be asked it.
YESNO_LIFETIME: Final = timedelta(days=60)
#: An invitation stays up a fortnight after the event, for the photos-and-thanks
#: messages that follow one.
INVITE_GRACE: Final = timedelta(days=14)
#: How far ahead an event may be. The month picker offers exactly this window.
INVITE_HORIZON_MONTHS: Final = 12
#: A crude cap on one page's RSVP rows, so a script cannot fill the table.
RSVPS_PER_PAGE: Final = 500
#: Namespaces the advisory lock, so it cannot collide with the order path's
#: (shop_id, day) locks -- shop ids are small and this is not one.
_LOCK_NAMESPACE: Final = 0x50474553  # "PGES"

_CONTROL = re.compile(r"[\u0000-\u0008\u000b-\u001f\u007f-\u009f​-‏‪-‮⁦-⁩]")
_SPACES = re.compile(r"[ \t]+")


class PageLimitReached(Exception):
    """The customer has made as many pages as they may for now."""

    def __init__(self, which: str) -> None:
        super().__init__(which)
        self.which = which  # "daily" or "live"


class InvalidDraft(ValueError):
    """A draft that did not come from the bot's own pickers."""


def clean_text(value: str | None, limit: int, *, multiline: bool = False) -> str | None:
    """User text as it is stored: trimmed, capped, with control and
    direction-override characters removed. None when nothing is left.

    Escaping is NOT done here -- it belongs to the output (Jinja's autoescape,
    or `escape` before Telegram HTML). Stored text is the text that was typed.
    """
    if value is None:
        return None
    value = unicodedata.normalize("NFC", value)
    value = _CONTROL.sub("", value.replace("\r\n", "\n").replace("\r", "\n"))
    if multiline:
        lines = [_SPACES.sub(" ", line).strip() for line in value.split("\n")]
        value = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    else:
        value = _SPACES.sub(" ", value.replace("\n", " ")).strip()
    value = value[:limit].rstrip()
    return value or None


def new_token() -> str:
    """128 random bits, URL-safe: the page's address and its only secret."""
    return secrets.token_urlsafe(16)


@dataclass(frozen=True)
class YesNoDraft:
    template: str
    lang: str
    question_preset: str
    question: str
    notify_creator: bool
    #: CP17: the optional date plan. Both empty, or 1-5 of each.
    places: tuple[str, ...] = ()
    slots: tuple[datetime, ...] = ()


@dataclass(frozen=True)
class ApologyDraft:
    """Uzrnoma (CP17): the creator's own letter, answered "Kechirdim"."""

    template: str
    lang: str
    text: str
    notify_creator: bool


@dataclass(frozen=True)
class InviteDraft:
    template: str
    lang: str
    event_type: str
    name_1: str
    name_2: str | None
    event_date: date
    event_time: time
    venue: str
    location: tuple[Decimal, Decimal] | None
    message: str | None
    rsvp_enabled: bool
    #: The Konvert seal (CP17); None shows the couple's initials.
    seal_monogram: str | None = None


def clean_monogram(value: object) -> str | None:
    """A seal monogram as stored: letters, "&" and a middle dot, upper-cased,
    at most MONOGRAM_MAX, with at least one letter. None for nothing; ValueError
    for anything else -- a seal is pressed, not typed into."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("monogram")
    text = "".join(value.split()).replace(".", "\u00b7").upper()
    if not text:
        return None
    if (
        len(text) > MONOGRAM_MAX
        or not any(ch.isalpha() for ch in text)
        or any(not (ch.isalpha() or ch in "&\u00b7") for ch in text)
    ):
        raise ValueError("monogram")
    return text


def _draft_monogram(value: str | None) -> str | None:
    try:
        return clean_monogram(value)
    except ValueError:
        raise InvalidDraft("a seal monogram the bot could not have taken") from None


def _check_common(template: str, lang: str) -> None:
    if template not in PAGE_TEMPLATES:
        raise InvalidDraft(f"unknown template {template!r}")
    if lang not in PAGE_LANGUAGES:
        raise InvalidDraft(f"unknown page language {lang!r}")


def invite_expiry(event_date: date, tz: ZoneInfo) -> datetime:
    """The end of the event day, plus the grace period, as an instant."""
    end_of_day = datetime.combine(event_date, time(23, 59), tzinfo=tz)
    return (end_of_day + INVITE_GRACE).astimezone(UTC)


def event_window(today: date) -> tuple[date, date]:
    """First and last date an invitation may be for: today, through the same
    day INVITE_HORIZON_MONTHS on."""
    year, month = divmod(today.month - 1 + INVITE_HORIZON_MONTHS, 12)
    last_year, last_month = today.year + year, month + 1
    day = min(today.day, _days_in(last_year, last_month))
    return today, date(last_year, last_month, day)


def _days_in(year: int, month: int) -> int:
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    return (nxt - timedelta(days=1)).day


async def _lock_customer(session: AsyncSession, customer_id: int) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:ns, :customer)"),
        {"ns": _LOCK_NAMESPACE, "customer": customer_id % 2_147_483_647},
    )


async def check_limits(
    session: AsyncSession, *, shop_id: int, customer_id: int, now: datetime
) -> None:
    """Raise PageLimitReached if one more page would be one too many."""
    made_today = await session.scalar(
        select(func.count())
        .select_from(SharePage)
        .where(
            SharePage.shop_id == shop_id,
            SharePage.customer_id == customer_id,
            SharePage.created_at > now - timedelta(hours=24),
        )
    )
    if (made_today or 0) >= CREATE_PER_DAY:
        raise PageLimitReached("daily")
    live = await session.scalar(
        select(func.count())
        .select_from(SharePage)
        .where(
            SharePage.shop_id == shop_id,
            SharePage.customer_id == customer_id,
            SharePage.deleted_at.is_(None),
            SharePage.expires_at > now,
        )
    )
    if (live or 0) >= LIVE_PER_CUSTOMER:
        raise PageLimitReached("live")


async def create_page(
    session: AsyncSession,
    *,
    shop_id: int,
    customer_id: int,
    bot_username: str | None,
    draft: YesNoDraft | InviteDraft | ApologyDraft,
    now: datetime | None = None,
) -> SharePage:
    """Write one page, or raise PageLimitReached / InvalidDraft.

    Call inside the handler's transaction: the limit is checked under a lock
    that the commit releases, so two taps on Create count as two.
    """
    now = now or datetime.now(UTC)
    _check_common(draft.template, draft.lang)
    if premium.is_premium_template(draft.template):
        # Raises PremiumLocked: the bot offers these only once unlocked, and
        # this is the wall behind that offer (CP18, the gift rule).
        await premium.require(session, shop_id=shop_id, customer_id=customer_id)
    values: dict[str, object] = {
        "shop_id": shop_id,
        "customer_id": customer_id,
        "template": draft.template,
        "lang": draft.lang,
        "bot_username": bot_username,
        # The same clock the limit is checked against, not the server's.
        "created_at": now,
    }
    if isinstance(draft, YesNoDraft):
        if draft.question_preset not in QUESTION_PRESETS:
            raise InvalidDraft(f"unknown question preset {draft.question_preset!r}")
        question = clean_text(draft.question, QUESTION_MAX)
        if question is None:
            raise InvalidDraft("empty question")
        values |= {
            "kind": PageKind.YESNO.value,
            "question_preset": draft.question_preset,
            "question": question,
            "notify_creator": draft.notify_creator,
            "expires_at": now + YESNO_LIFETIME,
        }
        plan = await _checked_plan(session, shop_id, draft.places, draft.slots, now)
    elif isinstance(draft, ApologyDraft):
        letter = clean_text(draft.text, MESSAGE_MAX, multiline=True)
        if letter is None:
            raise InvalidDraft("an empty apology")
        values |= {
            "kind": PageKind.APOLOGY.value,
            "message": letter,
            "notify_creator": draft.notify_creator,
            "expires_at": now + YESNO_LIFETIME,
        }
    else:
        if draft.event_type not in EVENT_TYPES:
            raise InvalidDraft(f"unknown event type {draft.event_type!r}")
        name_1 = clean_text(draft.name_1, NAME_MAX)
        venue = clean_text(draft.venue, VENUE_MAX)
        if name_1 is None or venue is None:
            raise InvalidDraft("an invitation needs a name and a venue")
        tz = await _shop_timezone(session, shop_id)
        first, last = event_window(now.astimezone(tz).date())
        if not first <= draft.event_date <= last:
            raise InvalidDraft("event date outside the window the picker offers")
        lat, lon = draft.location if draft.location is not None else (None, None)
        if lat is not None and lon is not None and not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise InvalidDraft("location out of range")
        values |= {
            "kind": PageKind.INVITE.value,
            "event_type": draft.event_type,
            "name_1": name_1,
            "name_2": clean_text(draft.name_2, NAME_MAX),
            "event_date": draft.event_date,
            "event_time": draft.event_time,
            "venue": venue,
            "location_lat": lat,
            "location_lon": lon,
            "message": clean_text(draft.message, MESSAGE_MAX, multiline=True),
            "rsvp_enabled": draft.rsvp_enabled,
            "seal_monogram": _draft_monogram(draft.seal_monogram),
            "expires_at": invite_expiry(draft.event_date, tz),
        }

    await _lock_customer(session, customer_id)
    await check_limits(session, shop_id=shop_id, customer_id=customer_id, now=now)

    for _attempt in range(3):
        page = SharePage(token=new_token(), **values)
        try:
            async with session.begin_nested():
                session.add(page)
                await session.flush()
                if isinstance(draft, YesNoDraft):
                    _add_plan(session, page, *plan)
                    await session.flush()
        except IntegrityError as clash:
            # 128 random bits do not collide; this is here so a collision is a
            # retry rather than a customer-facing error if the impossible happens.
            if "uq_share_pages_token" not in str(clash.orig):
                raise
            continue
        return page
    raise RuntimeError("could not mint a unique page token")  # pragma: no cover


async def _shop_timezone(session: AsyncSession, shop_id: int) -> ZoneInfo:
    name = await session.scalar(select(Shop.timezone).where(Shop.id == shop_id))
    return ZoneInfo(name or "Asia/Tashkent")


async def list_pages(
    session: AsyncSession, *, shop_id: int, customer_id: int, now: datetime | None = None
) -> list[SharePage]:
    """The customer's live pages in THIS shop, newest first."""
    now = now or datetime.now(UTC)
    rows = await session.scalars(
        select(SharePage)
        .where(
            SharePage.shop_id == shop_id,
            SharePage.customer_id == customer_id,
            SharePage.deleted_at.is_(None),
            SharePage.expires_at > now,
        )
        .order_by(SharePage.created_at.desc(), SharePage.id.desc())
        .limit(LIVE_PER_CUSTOMER)
    )
    return list(rows)


async def get_own_page(
    session: AsyncSession, *, shop_id: int, customer_id: int, page_id: int
) -> SharePage | None:
    """One page, only if it is THIS customer's in THIS shop and still live."""
    return await session.scalar(
        select(SharePage).where(
            SharePage.id == page_id,
            SharePage.shop_id == shop_id,
            SharePage.customer_id == customer_id,
            SharePage.deleted_at.is_(None),
        )
    )


#: Everything a person typed, set to NULL when a page is deleted or expires.
_SCRUB = {
    "question": None,
    "name_1": None,
    "name_2": None,
    "venue": None,
    "location_lat": None,
    "location_lon": None,
    "message": None,
    "title": None,
    "dress_code": None,
    "program": None,
    "contact": None,
    "closing": None,
    "dress_colors": None,
    "chosen_place": None,
    "chosen_slot_at": None,
    "chosen_at": None,
    "choice_notified_at": None,
}


async def delete_page(
    session: AsyncSession,
    *,
    shop_id: int,
    customer_id: int,
    page_id: int,
    now: datetime | None = None,
) -> bool:
    """Take the page down and scrub what was typed into it. True if it was
    this customer's live page; False for anything else, which changes nothing."""
    now = now or datetime.now(UTC)
    deleted = await session.scalar(
        update(SharePage)
        .where(
            SharePage.id == page_id,
            SharePage.shop_id == shop_id,
            SharePage.customer_id == customer_id,
            SharePage.deleted_at.is_(None),
        )
        .values(deleted_at=now, **_SCRUB)
        .returning(SharePage.id)
    )
    if deleted is None:
        return False
    await session.execute(delete(SharePageOption).where(SharePageOption.page_id == page_id))
    await session.execute(delete(SharePagePhoto).where(SharePagePhoto.page_id == page_id))
    await session.execute(delete(SharePageWish).where(SharePageWish.page_id == page_id))
    await session.execute(
        update(SharePageRsvp)
        .where(SharePageRsvp.page_id == page_id, SharePageRsvp.shop_id == shop_id)
        .values(guest_name=None)
    )
    return True


async def scrub_expired(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Nightly: expired pages lose their text exactly as a deleted one does."""
    now = now or datetime.now(UTC)
    ids = list(
        await session.scalars(
            update(SharePage)
            .where(SharePage.deleted_at.is_(None), SharePage.expires_at <= now)
            .values(deleted_at=now, **_SCRUB)
            .returning(SharePage.id)
        )
    )
    if ids:
        await session.execute(
            update(SharePageRsvp).where(SharePageRsvp.page_id.in_(ids)).values(guest_name=None)
        )
        await session.execute(delete(SharePageOption).where(SharePageOption.page_id.in_(ids)))
        await session.execute(delete(SharePagePhoto).where(SharePagePhoto.page_id.in_(ids)))
        await session.execute(delete(SharePageWish).where(SharePageWish.page_id.in_(ids)))
    return len(ids)


@dataclass(frozen=True)
class RsvpSummary:
    coming: int
    guests: int
    not_coming: int


async def rsvp_summary(session: AsyncSession, *, shop_id: int, page_id: int) -> RsvpSummary:
    row = (
        await session.execute(
            select(
                func.count().filter(SharePageRsvp.answer == "yes"),
                func.coalesce(func.sum(SharePageRsvp.guests), 0),
                func.count().filter(SharePageRsvp.answer == "no"),
            ).where(SharePageRsvp.page_id == page_id, SharePageRsvp.shop_id == shop_id)
        )
    ).one()
    return RsvpSummary(coming=int(row[0]), guests=int(row[1]), not_coming=int(row[2]))


# --- the public side ---------------------------------------------------------


@dataclass(frozen=True)
class PublicPage:
    page: SharePage
    shop_name: str
    shop_timezone: str
    live: bool
    #: CP18: the shop is paused -- the page stays up, the order link goes.
    shop_paused: bool = False


async def load_public_page(
    session: AsyncSession, token: str, *, now: datetime | None = None
) -> PublicPage | None:
    """The page at this token, with its shop's name. None if no such token.

    `live` is False for a deleted or expired page: the caller shows "gone",
    and nothing typed into it is rendered.
    """
    now = now or datetime.now(UTC)
    row = (
        await session.execute(
            select(SharePage, Shop.name, Shop.timezone, Shop.status)
            .join(Shop, Shop.id == SharePage.shop_id)
            .where(SharePage.token == token)
        )
    ).one_or_none()
    if row is None:
        return None
    page, shop_name, shop_tz, shop_status = row
    # CP18: a page hidden by moderation is, to the public, simply gone.
    live = page.deleted_at is None and page.expires_at > now and page.hidden_at is None
    return PublicPage(
        page=page,
        shop_name=shop_name,
        shop_timezone=shop_tz,
        live=live,
        shop_paused=shop_status == ShopStatus.PAUSED.value,
    )


async def record_view(session: AsyncSession, *, page_id: int) -> None:
    await session.execute(
        update(SharePage).where(SharePage.id == page_id).values(view_count=SharePage.view_count + 1)
    )


async def record_cta(
    session: AsyncSession, token: str, *, now: datetime | None = None
) -> tuple[str | None, bool] | None:
    """Count a tap on the shop's link. Returns (bot_username, live), or None
    for an unknown token. A PAUSED shop's link has no bot to go to (CP18):
    the username comes back None, so the tap lands on the page again.

    Only a tap that can GO somewhere is counted (CP18): a deleted, expired or
    hidden page, or a paused shop, offers no link, so a hit on /go there is
    not a customer choosing the shop -- found by the moderation test, which
    saw a hidden page's counter move."""
    now = now or datetime.now(UTC)
    row = (
        await session.execute(
            select(
                SharePage.id,
                SharePage.bot_username,
                SharePage.deleted_at,
                SharePage.expires_at,
                SharePage.hidden_at,
                Shop.status,
            )
            .join(Shop, Shop.id == SharePage.shop_id)
            .where(SharePage.token == token)
        )
    ).one_or_none()
    if row is None:
        return None
    page_id, username, deleted_at, expires_at, hidden_at, shop_status = row
    live = deleted_at is None and expires_at > now and hidden_at is None
    if shop_status == ShopStatus.PAUSED.value:
        username = None
    if live and username is not None:
        await session.execute(
            update(SharePage)
            .where(SharePage.id == page_id)
            .values(cta_click_count=SharePage.cta_click_count + 1)
        )
    return username, live


@dataclass(frozen=True)
class YesOutcome:
    page_id: int
    first: bool
    notify: bool
    #: CP17: the page carries a date plan, so the recipient chooses next.
    has_plan: bool = False


async def answer_yes(
    session: AsyncSession, token: str, *, now: datetime | None = None
) -> YesOutcome | None:
    """Record a Ha. Only the FIRST one sets answered_at -- compare-and-swap on
    `answered_at IS NULL` -- so `first` is True exactly once per page however
    often the button is pressed. None for anything that is not a live yesno."""
    now = now or datetime.now(UTC)
    live = and_(
        SharePage.token == token,
        SharePage.kind.in_(ANSWERABLE_KINDS),
        SharePage.deleted_at.is_(None),
        SharePage.hidden_at.is_(None),  # CP18: hidden by moderation
        SharePage.expires_at > now,
    )
    row = (
        await session.execute(
            update(SharePage)
            .where(live, SharePage.answered_at.is_(None))
            .values(answered_at=now)
            .returning(SharePage.id, SharePage.notify_creator)
        )
    ).one_or_none()
    if row is not None:
        page_id = int(row[0])
        return YesOutcome(
            page_id=page_id,
            first=True,
            notify=bool(row[1]),
            has_plan=await has_plan(session, page_id=page_id),
        )
    found = await session.scalar(select(SharePage.id).where(live))
    if found is None:
        return None
    return YesOutcome(
        page_id=int(found),
        first=False,
        notify=False,
        has_plan=await has_plan(session, page_id=int(found)),
    )


class RsvpRefused(Exception):
    pass


async def submit_rsvp(
    session: AsyncSession,
    token: str,
    *,
    voter_key: str,
    answer: str,
    guests: int,
    guest_name: str | None,
    now: datetime | None = None,
) -> None:
    """One browser's answer, inserted or replaced. RsvpRefused for a page
    that is not a live invitation with RSVP on, for values outside what the
    form offers, or once the page has RSVPS_PER_PAGE answers."""
    now = now or datetime.now(UTC)
    if answer not in ("yes", "no"):
        raise RsvpRefused("answer")
    if answer == "yes" and not 1 <= guests <= MAX_GUESTS:
        raise RsvpRefused("guests")
    if answer == "no":
        guests = 0
    page = await session.scalar(
        select(SharePage)
        .where(
            SharePage.token == token,
            SharePage.kind == PageKind.INVITE.value,
            SharePage.rsvp_enabled.is_(True),
            SharePage.deleted_at.is_(None),
            SharePage.hidden_at.is_(None),  # CP18: hidden by moderation
            SharePage.expires_at > now,
        )
        .with_for_update()
    )
    if page is None:
        raise RsvpRefused("page")
    existing = await session.scalar(
        select(SharePageRsvp.id).where(
            SharePageRsvp.page_id == page.id, SharePageRsvp.voter_key == voter_key
        )
    )
    if existing is None:
        count = await session.scalar(
            select(func.count()).select_from(SharePageRsvp).where(SharePageRsvp.page_id == page.id)
        )
        if (count or 0) >= RSVPS_PER_PAGE:
            raise RsvpRefused("full")
    name = clean_text(guest_name, GUEST_NAME_MAX)
    statement = insert(SharePageRsvp).values(
        shop_id=page.shop_id,
        page_id=page.id,
        voter_key=voter_key,
        answer=answer,
        guests=guests,
        guest_name=name,
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=["page_id", "voter_key"],
            set_={"answer": answer, "guests": guests, "guest_name": name, "updated_at": now},
        )
    )


async def record_referral(
    session: AsyncSession, *, shop_id: int, customer_id: int, token: str
) -> bool:
    """A customer arrived through a page's link. Honoured ONLY when the page
    belongs to this shop: a token from shop B's page arriving in shop A's bot
    is ignored, and says nothing about whether it exists."""
    page_id = await session.scalar(
        select(SharePage.id).where(SharePage.token == token, SharePage.shop_id == shop_id)
    )
    if page_id is None:
        return False
    await session.execute(
        insert(SharePageReferral)
        .values(shop_id=shop_id, page_id=page_id, customer_id=customer_id)
        .on_conflict_do_nothing(index_elements=["page_id", "customer_id"])
    )
    return True


#: How long a recipient who said Ha has to pick a place and a time before the
#: creator is told "Ha, but nothing chosen yet". Ten minutes: long enough to
#: read the options, short enough that the creator is not left wondering.
CHOICE_WAIT: Final = timedelta(minutes=10)

#: The four messages a creator can get, and the column each one claims:
#:   yes             -- no plan                                  notified_at
#:   yes_with_choice -- plan, chosen before the first message    both
#:   yes_no_choice   -- plan, nothing chosen after CHOICE_WAIT   notified_at
#:   choice_later    -- the choice, after yes_no_choice went     choice_notified_at
MESSAGE_KINDS: Final = ("yes", "yes_with_choice", "yes_no_choice", "choice_later")


@dataclass(frozen=True)
class NotifyTarget:
    page_id: int
    shop_id: int
    telegram_user_id: int
    lang: str
    question: str
    kind: str = "yes"
    #: "yesno" or "apology": what the answer was to.
    page_kind: str = "yesno"
    place: str | None = None
    slot_at: datetime | None = None
    shop_timezone: str = "Asia/Tashkent"


async def claim_notification(
    session: AsyncSession, *, page_id: int, now: datetime | None = None
) -> NotifyTarget | None:
    """Claim whichever creator message is due now, or None if none is.

    EXACTLY ONE of each, ever: the page row is locked FOR UPDATE, the due
    message is decided from its state, and the column that message owns is
    set in the same transaction -- so a retried task, a second worker or a
    second Ha finds it claimed. Commit before sending (the CP6 pattern).
    """
    now = now or datetime.now(UTC)
    page = await session.scalar(
        select(SharePage)
        .where(
            SharePage.id == page_id,
            SharePage.notify_creator.is_(True),
            SharePage.answered_at.is_not(None),
            SharePage.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if page is None or page.answered_at is None:
        return None
    values: dict[str, object]
    if page.notified_at is None:
        if not await has_plan(session, page_id=page.id):
            kind, values = "yes", {"notified_at": now}
        elif page.chosen_at is not None:
            kind, values = "yes_with_choice", {"notified_at": now, "choice_notified_at": now}
        elif now - page.answered_at >= CHOICE_WAIT:
            kind, values = "yes_no_choice", {"notified_at": now}
        else:
            return None  # the delayed check will come back for it
    elif page.chosen_at is not None and page.choice_notified_at is None:
        kind, values = "choice_later", {"choice_notified_at": now}
    else:
        return None
    await session.execute(update(SharePage).where(SharePage.id == page.id).values(**values))
    customer = (
        await session.execute(
            select(Customer.telegram_user_id, Customer.lang).where(
                Customer.id == page.customer_id, Customer.shop_id == page.shop_id
            )
        )
    ).one()
    return NotifyTarget(
        page_id=page.id,
        shop_id=page.shop_id,
        telegram_user_id=int(customer[0]),
        lang=str(customer[1]),
        question=(page.question if page.kind == PageKind.YESNO else page.message) or "",
        kind=kind,
        page_kind=page.kind,
        place=page.chosen_place,
        slot_at=page.chosen_slot_at,
        shop_timezone=await _shop_timezone_name(session, page.shop_id),
    )


async def release_notification(session: AsyncSession, *, page_id: int, kind: str = "yes") -> None:
    """Undo a claim whose send failed for a reason worth retrying."""
    values: dict[str, object] = {}
    if kind in ("yes", "yes_with_choice", "yes_no_choice"):
        values["notified_at"] = None
    if kind in ("yes_with_choice", "choice_later"):
        values["choice_notified_at"] = None
    await session.execute(update(SharePage).where(SharePage.id == page_id).values(**values))


async def _shop_timezone_name(session: AsyncSession, shop_id: int) -> str:
    return str(
        await session.scalar(select(Shop.timezone).where(Shop.id == shop_id)) or "Asia/Tashkent"
    )


# --- the date plan (CP17) ------------------------------------------------------------


async def _checked_plan(
    session: AsyncSession,
    shop_id: int,
    places: tuple[str, ...],
    slots: tuple[datetime, ...],
    now: datetime,
) -> tuple[list[str], list[datetime]]:
    """Both empty, or 1-5 distinct places and 1-5 distinct FUTURE times inside
    the window the picker offers. Anything else is a draft the bot could not
    have produced."""
    if not places and not slots:
        return [], []
    cleaned = [clean_text(place, PLACE_MAX) for place in places]
    if (
        not 1 <= len(cleaned) <= PLAN_MAX
        or not 1 <= len(slots) <= PLAN_MAX
        or any(place is None for place in cleaned)
        or len(set(cleaned)) != len(cleaned)
        or len(set(slots)) != len(slots)
    ):
        raise InvalidDraft("a date plan needs 1-5 distinct places and 1-5 distinct times")
    tz = await _shop_timezone(session, shop_id)
    first, last = event_window(now.astimezone(tz).date())
    for slot in slots:
        if slot.tzinfo is None or slot <= now or not first <= slot.astimezone(tz).date() <= last:
            raise InvalidDraft("a time outside the window the picker offers")
    return [place for place in cleaned if place is not None], sorted(slots)


def _add_plan(
    session: AsyncSession, page: SharePage, places: list[str], slots: list[datetime]
) -> None:
    for n, place in enumerate(places, start=1):
        session.add(
            SharePageOption(
                shop_id=page.shop_id, page_id=page.id, kind="place", position=n, place=place
            )
        )
    for n, slot in enumerate(slots, start=1):
        session.add(
            SharePageOption(
                shop_id=page.shop_id, page_id=page.id, kind="slot", position=n, slot_at=slot
            )
        )


async def has_plan(session: AsyncSession, *, page_id: int) -> bool:
    found = await session.scalar(
        select(SharePageOption.id).where(SharePageOption.page_id == page_id).limit(1)
    )
    return found is not None


async def plan_of(
    session: AsyncSession, *, page_id: int
) -> tuple[list[SharePageOption], list[SharePageOption]]:
    """(places, slots), each in the creator's order."""
    rows = list(
        await session.scalars(
            select(SharePageOption)
            .where(SharePageOption.page_id == page_id)
            .order_by(SharePageOption.kind, SharePageOption.position)
        )
    )
    return [r for r in rows if r.kind == "place"], [r for r in rows if r.kind == "slot"]


async def set_plan(
    session: AsyncSession,
    *,
    shop_id: int,
    customer_id: int,
    page_id: int,
    places: tuple[str, ...],
    slots: tuple[datetime, ...],
    now: datetime | None = None,
) -> SharePage:
    """Replace (or, with both empty, remove) the plan of this customer's own
    Ha/Yo'q page -- refused once it has been answered, like every other edit."""
    now = now or datetime.now(UTC)
    page = await session.scalar(
        select(SharePage)
        .where(
            SharePage.id == page_id,
            SharePage.shop_id == shop_id,
            SharePage.customer_id == customer_id,
            SharePage.kind == PageKind.YESNO.value,
            SharePage.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if page is None or page.expires_at <= now:
        raise EditRefused("gone")
    if page.answered_at is not None:
        raise EditRefused("locked")
    try:
        plan = await _checked_plan(session, shop_id, places, slots, now)
    except InvalidDraft:
        raise EditRefused("invalid") from None
    await session.execute(delete(SharePageOption).where(SharePageOption.page_id == page.id))
    _add_plan(session, page, *plan)
    await session.execute(update(SharePage).where(SharePage.id == page.id).values(edited_at=now))
    await session.flush()
    await session.refresh(page)
    return page


class ChoiceRefused(Exception):
    """`reason`: "page" (no live, answered page with a plan at this token) or
    "options" (ids that are not this page's place and slot)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ChoiceOutcome:
    page_id: int
    first: bool
    place: str
    slot_at: datetime
    shop_timezone: str


async def choose(
    session: AsyncSession,
    token: str,
    *,
    place_id: int,
    slot_id: int,
    now: datetime | None = None,
) -> ChoiceOutcome:
    """The recipient's pick. The FIRST pick is kept -- compare-and-swap on
    chosen_at -- and a later one gets that first pick back, unchanged."""
    now = now or datetime.now(UTC)
    page = await session.scalar(
        select(SharePage)
        .where(
            SharePage.token == token,
            SharePage.kind == PageKind.YESNO.value,
            SharePage.answered_at.is_not(None),
            SharePage.deleted_at.is_(None),
            SharePage.hidden_at.is_(None),  # CP18: hidden by moderation
            SharePage.expires_at > now,
        )
        .with_for_update()
    )
    if page is None:
        raise ChoiceRefused("page")
    tz = await _shop_timezone_name(session, page.shop_id)
    if page.chosen_at is not None:
        assert page.chosen_place is not None and page.chosen_slot_at is not None
        return ChoiceOutcome(page.id, False, page.chosen_place, page.chosen_slot_at, tz)
    place = await session.scalar(
        select(SharePageOption).where(
            SharePageOption.id == place_id,
            SharePageOption.page_id == page.id,
            SharePageOption.kind == "place",
        )
    )
    slot = await session.scalar(
        select(SharePageOption).where(
            SharePageOption.id == slot_id,
            SharePageOption.page_id == page.id,
            SharePageOption.kind == "slot",
        )
    )
    if place is None or slot is None or place.place is None or slot.slot_at is None:
        raise ChoiceRefused("options")
    await session.execute(
        update(SharePage)
        .where(SharePage.id == page.id, SharePage.chosen_at.is_(None))
        .values(chosen_place=place.place, chosen_slot_at=slot.slot_at, chosen_at=now)
    )
    return ChoiceOutcome(page.id, True, place.place, slot.slot_at, tz)


@dataclass(frozen=True)
class PageStats:
    pages: int
    views: int
    cta_clicks: int
    referred_customers: int
    referred_orders: int


async def shop_page_stats(session: AsyncSession, *, shop_id: int) -> PageStats:
    """What the feature has earned one shop: its pages, their views, taps on
    its link, customers who arrived through them and those customers' orders
    placed after they arrived."""
    pages, views, clicks = (
        await session.execute(
            select(
                func.count(),
                func.coalesce(func.sum(SharePage.view_count), 0),
                func.coalesce(func.sum(SharePage.cta_click_count), 0),
            ).where(SharePage.shop_id == shop_id)
        )
    ).one()
    referred = await session.scalar(
        select(func.count(func.distinct(SharePageReferral.customer_id))).where(
            SharePageReferral.shop_id == shop_id
        )
    )
    orders = await session.scalar(
        select(func.count(func.distinct(Order.id)))
        .select_from(Order)
        .join(
            SharePageReferral,
            and_(
                SharePageReferral.customer_id == Order.customer_id,
                SharePageReferral.shop_id == Order.shop_id,
                Order.created_at >= SharePageReferral.created_at,
            ),
        )
        .where(Order.shop_id == shop_id)
    )
    return PageStats(
        pages=int(pages),
        views=int(views),
        cta_clicks=int(clicks),
        referred_customers=int(referred or 0),
        referred_orders=int(orders or 0),
    )


# --- editing (CP17) ------------------------------------------------------------

#: What a creator may change, per kind. Anything else is refused outright,
#: whatever a crafted callback asks for.
EDITABLE_FIELDS: Final[dict[str, frozenset[str]]] = {
    PageKind.INVITE.value: frozenset(
        {
            "title",
            "name_1",
            "name_2",
            "message",
            "event_at",
            "venue",
            "location",
            "dress_code",
            "program",
            "contact",
            "closing",
            "rsvp_enabled",
            "show_countdown",
            "show_gallery",
            "dress_colors",
            "wishes_enabled",
            "seal_monogram",
            "music",
            "template",
            "lang",
        }
    ),
    PageKind.YESNO.value: frozenset({"question", "template", "lang", "notify_creator", "music"}),
    PageKind.APOLOGY.value: frozenset({"message", "template", "lang", "notify_creator", "music"}),
}

#: Text fields: (cap, multi-line, may be emptied). Emptying title, message or
#: closing returns them to the event type's preset; emptying an extra line
#: removes it. A name, the venue and the question can never be empty.
TEXT_FIELDS: Final[dict[str, tuple[int, bool, bool]]] = {
    "title": (TITLE_MAX, False, True),
    "name_1": (NAME_MAX, False, False),
    "name_2": (NAME_MAX, False, True),
    "message": (MESSAGE_MAX, True, True),
    "venue": (VENUE_MAX, False, False),
    "dress_code": (DRESS_CODE_MAX, False, True),
    "program": (PROGRAM_MAX, True, True),
    "contact": (CONTACT_MAX, False, True),
    "closing": (CLOSING_MAX, False, True),
    "seal_monogram": (MONOGRAM_MAX, False, True),
    "question": (QUESTION_MAX, False, False),
}


async def _require_premium(session: AsyncSession, shop_id: int, customer_id: int) -> None:
    """An edit that turns a premium part ON needs the gift. Turning one off,
    or keeping what a page already has, never does."""
    if not await premium.unlocked(session, shop_id=shop_id, customer_id=customer_id):
        raise EditRefused("premium")


class EditRefused(Exception):
    """`reason` is "gone" (not this customer's live page), "locked" (a Ha/Yo'q
    page someone has answered) or "invalid" (a value no keyboard offers)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def effective_text(page: SharePage, field: str) -> str | None:
    """What the page SHOWS for a text field: the creator's words, or the
    event type's preset where they wrote none."""
    from gulbot.web import strings

    value: str | None = getattr(page, field)
    if value or page.kind != PageKind.INVITE or page.event_type is None:
        return value
    if field == "title":
        return strings.event_label(page.event_type, page.lang)
    if field == "message":
        return strings.event_message(page.event_type, page.lang)
    if field == "closing":
        return strings.event_closing(page.event_type, page.lang)
    return value


async def update_page(
    session: AsyncSession,
    *,
    shop_id: int,
    customer_id: int,
    page_id: int,
    changes: dict[str, object],
    now: datetime | None = None,
) -> SharePage:
    """Change a page IN PLACE: same row, same token, same link.

    Scoped like every customer-side call: this shop, this customer, a live page.
    A Ha/Yo'q page is LOCKED once answered -- the answer was given to exactly
    that question, and changing it afterwards would rewrite what was agreed to.
    The row is locked FOR UPDATE first, so an edit and a Ha cannot interleave:
    whichever commits first wins, and the other sees it.
    """
    from gulbot.web import strings

    now = now or datetime.now(UTC)
    page = await session.scalar(
        select(SharePage)
        .where(
            SharePage.id == page_id,
            SharePage.shop_id == shop_id,
            SharePage.customer_id == customer_id,
            SharePage.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if page is None or page.expires_at <= now:
        raise EditRefused("gone")
    if not changes or set(changes) - EDITABLE_FIELDS[page.kind]:
        raise EditRefused("invalid")
    if page.kind in ANSWERABLE_KINDS and page.answered_at is not None:
        raise EditRefused("locked")

    values: dict[str, object] = {}
    for field, value in changes.items():
        if field in TEXT_FIELDS:
            cap, multiline, may_empty = TEXT_FIELDS[field]
            # An invitation's message may go back to its preset; an Uzrnoma's
            # IS the letter, and a letter cannot be emptied.
            may_empty = may_empty and not (field == "message" and page.kind == PageKind.APOLOGY)
            if value is not None and not isinstance(value, str):
                raise EditRefused("invalid")
            cleaned = clean_text(value, cap, multiline=multiline)
            if cleaned is None and not may_empty:
                raise EditRefused("invalid")
            if field == "seal_monogram":
                try:
                    cleaned = clean_monogram(cleaned)
                except ValueError:
                    raise EditRefused("invalid") from None
            if field == "program" and cleaned is not None:
                try:
                    cleaned = sections.normalise_program(cleaned) or None
                except sections.ProgramRefused:
                    raise EditRefused("invalid") from None
            values[field] = cleaned
            if field == "question":
                values["question_preset"] = "custom"
        elif field == "template":
            if value not in PAGE_TEMPLATES:
                raise EditRefused("invalid")
            if value != page.template and premium.is_premium_template(str(value)):
                await _require_premium(session, shop_id, customer_id)
            values[field] = value
        elif field == "lang":
            if value not in PAGE_LANGUAGES:
                raise EditRefused("invalid")
            values[field] = value
            # A ready-made question follows the page into its new language.
            if (
                page.kind == PageKind.YESNO
                and page.question_preset in strings.QUESTIONS
                and "question" not in changes
            ):
                values["question"] = strings.question(page.question_preset, str(value))
        elif field == "music":
            if value is not None and value not in MUSIC_TRACKS:
                raise EditRefused("invalid")
            if value is not None and value != page.music:
                await _require_premium(session, shop_id, customer_id)
            values[field] = value
        elif field == "dress_colors":
            try:
                values[field] = sections.checked_colors(value)
            except ValueError:
                raise EditRefused("invalid") from None
        elif field in (
            "rsvp_enabled",
            "notify_creator",
            "show_countdown",
            "show_gallery",
            "wishes_enabled",
        ):
            if not isinstance(value, bool):
                raise EditRefused("invalid")
            values[field] = value
        elif field == "location":
            if value is None:
                values["location_lat"] = values["location_lon"] = None
            else:
                if not isinstance(value, (tuple, list)) or len(value) != 2:
                    raise EditRefused("invalid")
                try:
                    lat, lon = Decimal(str(value[0])), Decimal(str(value[1]))
                except (TypeError, ValueError, ArithmeticError):
                    raise EditRefused("invalid") from None
                if not (lat.is_finite() and lon.is_finite()):
                    raise EditRefused("invalid")
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    raise EditRefused("invalid")
                values["location_lat"], values["location_lon"] = lat, lon
        elif field == "event_at":
            if not (
                isinstance(value, tuple)
                and len(value) == 2
                and isinstance(value[0], date)
                and isinstance(value[1], time)
            ):
                raise EditRefused("invalid")
            event_date, event_time = value
            tz = await _shop_timezone(session, shop_id)
            first, last = event_window(now.astimezone(tz).date())
            if not first <= event_date <= last:
                raise EditRefused("invalid")
            values["event_date"], values["event_time"] = event_date, event_time
            values["expires_at"] = invite_expiry(event_date, tz)
    values["edited_at"] = now

    await session.execute(update(SharePage).where(SharePage.id == page.id).values(**values))
    await session.refresh(page)
    return page
