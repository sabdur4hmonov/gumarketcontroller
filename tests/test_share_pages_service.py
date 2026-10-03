"""The service under the bot and the web pages: limits, answers, deletion.

Against real Postgres, inside the test's rolled-back transaction.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
from tests.bot_harness import bound_session_factory

from gulbot.models.share_page import SharePage, SharePageRsvp
from gulbot.models.shop import DEFAULT_WORKING_HOURS
from gulbot.services import share_pages
from gulbot.services.share_pages import (
    InvalidDraft,
    InviteDraft,
    PageLimitReached,
    RsvpRefused,
    YesNoDraft,
    clean_text,
)

pytestmark = pytest.mark.infra

NOW = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)


async def make_shop(db: AsyncConnection, name: str = "Lola") -> int:
    row = await db.execute(
        text(
            "INSERT INTO shops (name, working_hours) VALUES (:n, CAST(:wh AS jsonb)) RETURNING id"
        ),
        {"n": name, "wh": json.dumps(DEFAULT_WORKING_HOURS)},
    )
    return int(row.scalar_one())


async def make_customer(db: AsyncConnection, shop_id: int, telegram_user_id: int) -> int:
    row = await db.execute(
        text(
            "INSERT INTO customers (shop_id, telegram_user_id, phone) "
            "VALUES (:s, :t, '+998901234567') RETURNING id"
        ),
        {"s": shop_id, "t": telegram_user_id},
    )
    return int(row.scalar_one())


def yesno(**overrides: object) -> YesNoDraft:
    values: dict[str, object] = {
        "template": "romantik",
        "lang": "uz",
        "question_preset": "marry",
        "question": "Menga turmushga chiqasanmi?",
        "notify_creator": True,
    }
    values.update(overrides)
    return YesNoDraft(**values)  # type: ignore[arg-type]


def invite(**overrides: object) -> InviteDraft:
    values: dict[str, object] = {
        "template": "milliy",
        "lang": "uz",
        "event_type": "wedding",
        "name_1": "Aziz",
        "name_2": "Malika",
        "event_date": date(2026, 11, 14),
        "event_time": time(18, 0),
        "venue": "Toshkent, Navro'z to'yxonasi",
        "location": (Decimal("41.311081"), Decimal("69.240562")),
        "message": None,
        "rsvp_enabled": True,
    }
    values.update(overrides)
    return InviteDraft(**values)  # type: ignore[arg-type]


@pytest.fixture
async def session(db: AsyncConnection) -> AsyncSession:
    return bound_session_factory(db)()


async def create(
    session: AsyncSession, shop_id: int, customer_id: int, draft: object, now: datetime = NOW
) -> SharePage:
    return await share_pages.create_page(
        session,
        shop_id=shop_id,
        customer_id=customer_id,
        bot_username="lola_gullar_bot",
        draft=draft,  # type: ignore[arg-type]
        now=now,
    )


# --- text --------------------------------------------------------------------


def test_clean_text_trims_caps_and_strips_controls() -> None:
    assert clean_text("  Aziz ‮  ", 60) == "Aziz"
    assert clean_text("a\x00b\x07c", 60) == "abc"
    assert clean_text("x" * 80, 60) == "x" * 60
    assert clean_text("   ", 60) is None
    assert clean_text(None, 60) is None
    assert clean_text("one\ntwo", 60) == "one two"
    assert clean_text("one\n\n\n\ntwo", 60, multiline=True) == "one\n\ntwo"


def test_tokens_are_random_and_url_safe() -> None:
    tokens = {share_pages.new_token() for _ in range(200)}
    assert len(tokens) == 200
    assert all(len(token) == 22 and token.isascii() for token in tokens)
    assert all(
        set(token) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
        for token in tokens
    )


# --- creating ------------------------------------------------------------------


async def test_a_yesno_page_is_created_with_its_expiry(
    db: AsyncConnection, session: AsyncSession
) -> None:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 501)
    page = await create(session, shop, customer, yesno())
    assert page.kind == "yesno" and page.shop_id == shop and page.customer_id == customer
    assert page.expires_at == NOW + share_pages.YESNO_LIFETIME
    assert page.bot_username == "lola_gullar_bot"
    assert len(page.token) == 22


async def test_an_invitation_expires_after_its_event(
    db: AsyncConnection, session: AsyncSession
) -> None:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 502)
    page = await create(session, shop, customer, invite())
    # 14 Nov 23:59 in Tashkent (UTC+5), plus the fortnight's grace.
    assert page.expires_at == datetime(2026, 11, 28, 18, 59, tzinfo=UTC)
    assert page.location_lat == Decimal("41.311081")


@pytest.mark.parametrize(
    "draft",
    [
        yesno(template="nope"),
        yesno(lang="de"),
        yesno(question_preset="nope"),
        yesno(question="   "),
        invite(event_type="nope"),
        invite(name_1=" "),
        invite(venue=""),
        invite(event_date=date(2026, 10, 2)),  # yesterday
        invite(event_date=date(2027, 10, 4)),  # past the 12-month window
        invite(location=(Decimal("91"), Decimal("0"))),
    ],
)
async def test_a_draft_the_pickers_could_not_produce_is_refused(
    db: AsyncConnection, session: AsyncSession, draft: object
) -> None:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 503)
    with pytest.raises(InvalidDraft):
        await create(session, shop, customer, draft)
    assert await session.scalar(select(SharePage.id).where(SharePage.shop_id == shop)) is None


async def test_the_daily_limit_counts_deleted_pages_too(
    db: AsyncConnection, session: AsyncSession
) -> None:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 504)
    for _ in range(share_pages.CREATE_PER_DAY):
        page = await create(session, shop, customer, yesno())
        assert await share_pages.delete_page(
            session, shop_id=shop, customer_id=customer, page_id=page.id, now=NOW
        )
    with pytest.raises(PageLimitReached) as limit:
        await create(session, shop, customer, yesno())
    assert limit.value.which == "daily"
    # A day later the window has moved on.
    await create(session, shop, customer, yesno(), now=NOW + timedelta(hours=25))


async def test_the_live_limit(
    db: AsyncConnection, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(share_pages, "CREATE_PER_DAY", 1000)
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 505)
    for _ in range(share_pages.LIVE_PER_CUSTOMER):
        await create(session, shop, customer, yesno())
    with pytest.raises(PageLimitReached) as limit:
        await create(session, shop, customer, yesno())
    assert limit.value.which == "live"


async def test_limits_are_per_shop(db: AsyncConnection, session: AsyncSession) -> None:
    """The same person in two shops is two customers, each with a limit."""
    shop_a, shop_b = await make_shop(db, "A"), await make_shop(db, "B")
    in_a, in_b = await make_customer(db, shop_a, 506), await make_customer(db, shop_b, 506)
    for _ in range(share_pages.CREATE_PER_DAY):
        await create(session, shop_a, in_a, yesno())
    await create(session, shop_b, in_b, yesno())


# --- answering ------------------------------------------------------------------


async def test_only_the_first_ha_counts(db: AsyncConnection, session: AsyncSession) -> None:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 507)
    page = await create(session, shop, customer, yesno())
    first = await share_pages.answer_yes(session, page.token, now=NOW)
    again = await share_pages.answer_yes(session, page.token, now=NOW + timedelta(minutes=1))
    assert first is not None and first.first and first.notify
    assert again is not None and not again.first and not again.notify
    await session.refresh(page)
    assert page.answered_at == NOW


async def test_ha_on_anything_but_a_live_yesno_is_nothing(
    db: AsyncConnection, session: AsyncSession
) -> None:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 508)
    card = await create(session, shop, customer, invite())
    gone = await create(session, shop, customer, yesno())
    await share_pages.delete_page(session, shop_id=shop, customer_id=customer, page_id=gone.id)
    old = await create(session, shop, customer, yesno())
    assert await share_pages.answer_yes(session, card.token, now=NOW) is None
    assert await share_pages.answer_yes(session, gone.token, now=NOW) is None
    assert await share_pages.answer_yes(session, "x" * 22, now=NOW) is None
    assert await share_pages.answer_yes(session, old.token, now=NOW + timedelta(days=61)) is None


async def test_the_creator_is_claimed_exactly_once(
    db: AsyncConnection, session: AsyncSession
) -> None:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 509)
    page = await create(session, shop, customer, yesno())
    assert await share_pages.claim_notification(session, page_id=page.id) is None  # no Ha yet
    await share_pages.answer_yes(session, page.token, now=NOW)
    target = await share_pages.claim_notification(session, page_id=page.id)
    assert target is not None
    assert (target.shop_id, target.telegram_user_id) == (shop, 509)
    assert await share_pages.claim_notification(session, page_id=page.id) is None
    await share_pages.release_notification(session, page_id=page.id)
    assert await share_pages.claim_notification(session, page_id=page.id) is not None


async def test_no_claim_when_the_creator_did_not_ask(
    db: AsyncConnection, session: AsyncSession
) -> None:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 510)
    page = await create(session, shop, customer, yesno(notify_creator=False))
    outcome = await share_pages.answer_yes(session, page.token, now=NOW)
    assert outcome is not None and outcome.first and not outcome.notify
    assert await share_pages.claim_notification(session, page_id=page.id) is None


async def test_the_database_refuses_a_notification_without_an_answer(
    db: AsyncConnection, session: AsyncSession
) -> None:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 511)
    page = await create(session, shop, customer, yesno())
    await session.commit()
    with pytest.raises(IntegrityError, match="ck_share_pages_notified_after_ha"):
        async with session.begin_nested():
            await session.execute(
                text("UPDATE share_pages SET notified_at = now() WHERE id = :id"), {"id": page.id}
            )


# --- RSVP ----------------------------------------------------------------------


async def test_one_browser_answers_once_and_may_change_its_mind(
    db: AsyncConnection, session: AsyncSession
) -> None:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 512)
    page = await create(session, shop, customer, invite())
    voter = "v" * 22
    await share_pages.submit_rsvp(
        session,
        page.token,
        voter_key=voter,
        answer="yes",
        guests=3,
        guest_name=" Dilnoza ",
        now=NOW,
    )
    await share_pages.submit_rsvp(
        session, page.token, voter_key="w" * 22, answer="no", guests=0, guest_name=None, now=NOW
    )
    summary = await share_pages.rsvp_summary(session, shop_id=shop, page_id=page.id)
    assert summary == share_pages.RsvpSummary(coming=1, guests=3, not_coming=1)
    await share_pages.submit_rsvp(
        session, page.token, voter_key=voter, answer="no", guests=5, guest_name=None, now=NOW
    )
    summary = await share_pages.rsvp_summary(session, shop_id=shop, page_id=page.id)
    assert summary == share_pages.RsvpSummary(coming=0, guests=0, not_coming=2)


@pytest.mark.parametrize(("answer", "guests"), [("maybe", 1), ("yes", 0), ("yes", 11), ("yes", -1)])
async def test_rsvp_values_the_form_cannot_send_are_refused(
    db: AsyncConnection, session: AsyncSession, answer: str, guests: int
) -> None:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 513)
    page = await create(session, shop, customer, invite())
    with pytest.raises(RsvpRefused):
        await share_pages.submit_rsvp(
            session,
            page.token,
            voter_key="v" * 22,
            answer=answer,
            guests=guests,
            guest_name=None,
            now=NOW,
        )


async def test_rsvp_needs_a_live_invitation_that_asked_for_it(
    db: AsyncConnection, session: AsyncSession
) -> None:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 514)
    closed = await create(session, shop, customer, invite(rsvp_enabled=False))
    question = await create(session, shop, customer, yesno())
    for token in (closed.token, question.token, "z" * 22):
        with pytest.raises(RsvpRefused, match="page"):
            await share_pages.submit_rsvp(
                session, token, voter_key="v" * 22, answer="yes", guests=1, guest_name=None, now=NOW
            )


async def test_one_page_cannot_take_unlimited_answers(
    db: AsyncConnection, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(share_pages, "RSVPS_PER_PAGE", 3)
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 515)
    page = await create(session, shop, customer, invite())
    for n in range(3):
        await share_pages.submit_rsvp(
            session,
            page.token,
            voter_key=f"{n:022d}",
            answer="yes",
            guests=1,
            guest_name=None,
            now=NOW,
        )
    with pytest.raises(RsvpRefused, match="full"):
        await share_pages.submit_rsvp(
            session,
            page.token,
            voter_key="9" * 22,
            answer="yes",
            guests=1,
            guest_name=None,
            now=NOW,
        )
    # An existing voter may still change their answer.
    await share_pages.submit_rsvp(
        session, page.token, voter_key=f"{0:022d}", answer="no", guests=0, guest_name=None, now=NOW
    )


# --- deleting and expiring ----------------------------------------------------


async def test_deleting_scrubs_everything_typed_and_keeps_the_counts(
    db: AsyncConnection, session: AsyncSession
) -> None:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 516)
    page = await create(session, shop, customer, invite(message="Kutib qolamiz"))
    await share_pages.submit_rsvp(
        session,
        page.token,
        voter_key="v" * 22,
        answer="yes",
        guests=2,
        guest_name="Dilnoza",
        now=NOW,
    )
    await share_pages.record_view(session, page_id=page.id)
    assert await share_pages.delete_page(
        session, shop_id=shop, customer_id=customer, page_id=page.id
    )
    await session.refresh(page)
    assert page.deleted_at is not None
    assert (page.name_1, page.name_2, page.venue, page.message, page.location_lat) == (None,) * 5
    assert page.view_count == 1
    names = await session.scalars(
        select(SharePageRsvp.guest_name).where(SharePageRsvp.page_id == page.id)
    )
    assert list(names) == [None]
    # A second delete changes nothing and says so.
    assert not await share_pages.delete_page(
        session, shop_id=shop, customer_id=customer, page_id=page.id
    )


async def test_expired_pages_are_scrubbed_nightly(
    db: AsyncConnection, session: AsyncSession
) -> None:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 517)
    old = await create(session, shop, customer, yesno())
    fresh = await create(session, shop, customer, yesno(), now=NOW + timedelta(days=30))
    scrubbed = await share_pages.scrub_expired(session, now=NOW + timedelta(days=61))
    assert scrubbed >= 1
    await session.refresh(old)
    await session.refresh(fresh)
    assert old.deleted_at is not None and old.question is None
    assert fresh.deleted_at is None and fresh.question


# --- the public side and attribution --------------------------------------------


async def test_public_lookup_says_whether_the_page_is_live(
    db: AsyncConnection, session: AsyncSession
) -> None:
    shop = await make_shop(db, "Lola gullari")
    customer = await make_customer(db, shop, 518)
    page = await create(session, shop, customer, yesno())
    found = await share_pages.load_public_page(session, page.token, now=NOW)
    assert found is not None and found.live and found.shop_name == "Lola gullari"
    later = await share_pages.load_public_page(session, page.token, now=NOW + timedelta(days=61))
    assert later is not None and not later.live
    assert await share_pages.load_public_page(session, "q" * 22) is None


async def test_a_tap_on_the_shop_link_is_counted(
    db: AsyncConnection, session: AsyncSession
) -> None:
    shop = await make_shop(db)
    customer = await make_customer(db, shop, 519)
    page = await create(session, shop, customer, yesno())
    assert await share_pages.record_cta(session, page.token, now=NOW) == ("lola_gullar_bot", True)
    assert await share_pages.record_cta(session, "q" * 22) is None
    await session.refresh(page)
    assert page.cta_click_count == 1


async def test_orders_are_attributed_to_the_page_that_brought_the_customer(
    db: AsyncConnection, session: AsyncSession
) -> None:
    shop = await make_shop(db)
    creator = await make_customer(db, shop, 520)
    visitor = await make_customer(db, shop, 521)
    page = await create(session, shop, creator, yesno())
    await share_pages.record_view(session, page_id=page.id)
    await share_pages.record_cta(session, page.token)
    assert await share_pages.record_referral(
        session, shop_id=shop, customer_id=visitor, token=page.token
    )
    # Recorded once, however many times they come back through it.
    assert await share_pages.record_referral(
        session, shop_id=shop, customer_id=visitor, token=page.token
    )
    await db.execute(
        text(
            "INSERT INTO orders (shop_id, customer_id, product_name_snapshot, "
            " price_uzs_snapshot, telegram_file_id_snapshot, delivery_date, "
            " delivery_hour, delivery_location_text, landmark, status, submit_token) "
            "VALUES (:s, :c, 'Oq atirgul', 450000, 'f', CURRENT_DATE + 1, '14:00', "
            " 'Chilonzor', 'eshik', 'placed', 'tok-attr-1')"
        ),
        {"s": shop, "c": visitor},
    )
    stats = await share_pages.shop_page_stats(session, shop_id=shop)
    assert stats == share_pages.PageStats(
        pages=1, views=1, cta_clicks=1, referred_customers=1, referred_orders=1
    )


async def test_only_the_owner_can_find_or_delete_a_page(
    db: AsyncConnection, session: AsyncSession
) -> None:
    """The service's own scoping, independent of the router's lookup in front
    of it: another customer of the same shop, or the same person in another
    shop, gets nothing and changes nothing."""
    shop_a, shop_b = await make_shop(db, "A"), await make_shop(db, "B")
    owner = await make_customer(db, shop_a, 530)
    neighbour = await make_customer(db, shop_a, 531)
    same_person_in_b = await make_customer(db, shop_b, 530)
    page = await create(session, shop_a, owner, yesno())
    for shop, customer in ((shop_a, neighbour), (shop_b, same_person_in_b), (shop_b, owner)):
        assert (
            await share_pages.get_own_page(
                session, shop_id=shop, customer_id=customer, page_id=page.id
            )
            is None
        )
        assert not await share_pages.delete_page(
            session, shop_id=shop, customer_id=customer, page_id=page.id
        )
    await session.refresh(page)
    assert page.deleted_at is None and page.question
