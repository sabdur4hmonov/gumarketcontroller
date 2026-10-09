"""CP18, the gift rule: basic share pages are free for everyone; the premium
parts unlock for a customer once one of their orders AT THAT SHOP is confirmed.

Premium (gulbot.services.premium, defined there and nowhere else): the ten
designs CP17 added, music, and photos. Per shop, never shared: the same
person, a customer of two shops, ordering at one unlocks nothing at the other.
Proven at the service (every wall), at the confirmation (the grant), at the
database (the composite FKs), and in the bot (the picker says why).
"""

from __future__ import annotations

import io
from datetime import date, time
from typing import Any

import pytest
from PIL import Image
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import bound_session_factory
from tests.share_pages_harness import ShopBot
from tests.test_share_pages_service import invite, make_customer, make_shop, yesno

from gulbot.bot.callbacks import PageTemplateCB
from gulbot.i18n.catalog import CATALOG
from gulbot.models.share_page import PAGE_TEMPLATES
from gulbot.services import order_status, premium, share_page_photos, share_pages
from gulbot.services.orders import OrderDraft, create_order
from gulbot.services.share_pages import EditRefused

pytestmark = pytest.mark.infra

PERSON = 990_401  # a customer of BOTH shops
LOCKED_UZ = CATALOG["premium.locked"]["uz"]


def a_jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 120, 150)).save(out, "JPEG")
    return out.getvalue()


@pytest.fixture
async def two(db: AsyncConnection) -> dict[str, Any]:
    shops = {label: await make_shop(db, f"Gift {label}") for label in ("a", "b")}
    customers = {label: await make_customer(db, shops[label], PERSON) for label in ("a", "b")}
    return {"db": db, "shop": shops, "customer": customers}


async def an_order(two: dict[str, Any], label: str, token: str) -> int:
    db = two["db"]
    product = (
        await db.execute(
            text(
                "INSERT INTO products (shop_id, name, telegram_file_id, source, "
                " channel_message_id, price_uzs, price_confidence, finalized_at) "
                "VALUES (:s, 'Atirgul', 'f', 'channel', :m, 100000, 'high', now()) RETURNING id"
            ),
            {"s": two["shop"][label], "m": abs(hash(token)) % 10**6},
        )
    ).scalar_one()
    async with bound_session_factory(db)() as session:
        order, _ = await create_order(
            session,
            shop_id=two["shop"][label],
            customer_id=two["customer"][label],
            draft=OrderDraft(
                product_id=product,
                product_name="Atirgul",
                price_uzs=100000,
                telegram_file_id="f",
                delivery_date=date(2027, 3, 8),
                delivery_hour=time(14),
                landmark="Ko'k eshik",
                recipient_name="Aziza",
                submit_token=token,
                location_text="Chilonzor 5",
            ),
        )
        await session.commit()
    return int(order.id)


async def confirm(two: dict[str, Any], label: str, order_id: int) -> None:
    async with bound_session_factory(two["db"])() as session:
        await order_status.confirm_order(session, shop_id=two["shop"][label], order_id=order_id)
        await session.commit()


async def is_unlocked(two: dict[str, Any], label: str) -> bool:
    async with bound_session_factory(two["db"])() as session:
        return await premium.unlocked(
            session, shop_id=two["shop"][label], customer_id=two["customer"][label]
        )


async def make(two: dict[str, Any], label: str, draft: Any) -> object:
    """create_page's outcome: the page, or the exception it raised."""
    async with bound_session_factory(two["db"])() as session:
        try:
            page = await share_pages.create_page(
                session,
                shop_id=two["shop"][label],
                customer_id=two["customer"][label],
                bot_username="gift_bot",
                draft=draft,
            )
        except Exception as error:  # noqa: BLE001 - the type is the assertion
            await session.rollback()
            return error
        await session.commit()
        return page


# --- what is premium ------------------------------------------------------------------


def test_premium_is_the_ten_cp17_designs_and_the_rest_stay_free() -> None:
    assert {
        "foto", "bold", "geometrik", "akvarel", "vintaj",
        "oqqora", "bolalar", "suzani", "neon", "deco",
    } == premium.PREMIUM_TEMPLATES  # fmt: skip
    free = set(PAGE_TEMPLATES) - premium.PREMIUM_TEMPLATES
    assert len(free) == 10 and "milliy" in free and "konvert" in free
    assert {"music"} == premium.PREMIUM_FIELDS


# --- locked until a confirmed order, at that shop only --------------------------------


async def test_free_parts_need_nothing_and_premium_parts_are_refused_before_a_gift(
    two: dict[str, Any],
) -> None:
    free = await make(two, "a", yesno(template="romantik"))
    assert not isinstance(free, Exception), repr(free)
    locked = await make(two, "a", invite(template="deco"))
    assert isinstance(locked, premium.PremiumLocked), repr(locked)

    page_id = free.id  # type: ignore[attr-defined]
    for change in ({"template": "neon"}, {"music": "tantana"}):
        async with bound_session_factory(two["db"])() as session:
            try:
                await share_pages.update_page(
                    session,
                    shop_id=two["shop"]["a"],
                    customer_id=two["customer"]["a"],
                    page_id=page_id,
                    changes=change,
                )
            except Exception as error:  # noqa: BLE001
                outcome: object = error
            else:
                outcome = None
        assert isinstance(outcome, EditRefused) and outcome.reason == "premium", (change, outcome)

    async with bound_session_factory(two["db"])() as session:
        try:
            await share_page_photos.store_photo(
                session,
                shop_id=two["shop"]["a"],
                customer_id=two["customer"]["a"],
                page_id=page_id,
                raw=a_jpeg(),
            )
        except Exception as error:  # noqa: BLE001
            photo: object = error
        else:
            photo = None
    assert isinstance(photo, premium.PremiumLocked), repr(photo)


async def test_a_confirmed_order_unlocks_premium_at_that_shop_and_not_the_other(
    two: dict[str, Any],
) -> None:
    order = await an_order(two, "a", "gift-a1")
    assert not await is_unlocked(two, "a"), "a PLACED order unlocked premium"
    await confirm(two, "a", order)
    assert await is_unlocked(two, "a")
    assert not await is_unlocked(two, "b"), "the gift leaked to another shop"

    made_here = await make(two, "a", invite(template="deco"))
    assert not isinstance(made_here, Exception), repr(made_here)
    made_there = await make(two, "b", invite(template="deco"))
    assert isinstance(made_there, premium.PremiumLocked), repr(made_there)


async def test_a_rejected_order_or_a_shop_with_the_rule_off_grants_nothing(
    two: dict[str, Any],
) -> None:
    rejected = await an_order(two, "a", "gift-r1")
    async with bound_session_factory(two["db"])() as session:
        await order_status.reject_order(
            session, shop_id=two["shop"]["a"], order_id=rejected, reason="Yo'q gul"
        )
        await session.commit()
    assert not await is_unlocked(two, "a")
    # A late Confirm tap on the rejected card changes nothing -- so it must
    # grant nothing either: only a confirmation that HAPPENED is a gift.
    await confirm(two, "a", rejected)
    assert not await is_unlocked(two, "a"), "a confirmation that did not happen granted premium"

    await two["db"].execute(
        text("UPDATE shops SET gift_premium_after_order = false WHERE id = :s"),
        {"s": two["shop"]["b"]},
    )
    off = await an_order(two, "b", "gift-off")
    await confirm(two, "b", off)
    assert not await is_unlocked(two, "b"), "the rule was off, yet premium was granted"


async def test_a_double_confirm_grants_once_and_turning_music_off_needs_no_gift(
    two: dict[str, Any],
) -> None:
    first = await an_order(two, "a", "gift-d1")
    await confirm(two, "a", first)
    await confirm(two, "a", first)  # the loser of a double tap
    second = await an_order(two, "a", "gift-d2")
    await confirm(two, "a", second)
    rows = await two["db"].scalar(
        text("SELECT count(*) FROM premium_unlocks WHERE shop_id = :s"), {"s": two["shop"]["a"]}
    )
    assert rows == 1
    # Switching a premium part OFF is always allowed, gift or not.
    page = await make(two, "b", yesno(template="romantik"))
    async with bound_session_factory(two["db"])() as session:
        try:
            edited: object = await share_pages.update_page(
                session,
                shop_id=two["shop"]["b"],
                customer_id=two["customer"]["b"],
                page_id=page.id,  # type: ignore[attr-defined]
                changes={"music": None},
            )
        except Exception as error:  # noqa: BLE001 - a refusal here is the failure
            edited = error
    assert getattr(edited, "music", "refused") is None, repr(edited)


# --- the database: an unlock can never cross shops -------------------------------------


async def _refusal(db: AsyncConnection, sql: str, params: dict[str, Any]) -> str:
    try:
        async with db.begin_nested():
            await db.execute(text(sql), params)
    except Exception as error:  # noqa: BLE001 - the constraint's name is the assertion
        return str(error)
    return ""


async def test_the_database_refuses_an_unlock_joining_another_shops_customer_or_order(
    two: dict[str, Any],
) -> None:
    db = two["db"]
    order_a = await an_order(two, "a", "gift-t1")
    customer = await _refusal(
        db,
        "INSERT INTO premium_unlocks (shop_id, customer_id, order_id) VALUES (:s, :c, :o)",
        {"s": two["shop"]["b"], "c": two["customer"]["a"], "o": order_a},
    )
    assert "fk_premium_unlocks_customer_id_shop_id_customers" in customer, customer or "accepted"
    order_b = await an_order(two, "b", "gift-t2")
    order = await _refusal(
        db,
        "INSERT INTO premium_unlocks (shop_id, customer_id, order_id) VALUES (:s, :c, :o)",
        {"s": two["shop"]["a"], "c": two["customer"]["a"], "o": order_b},
    )
    assert "fk_premium_unlocks_order_id_shop_id_orders" in order, order or "accepted"
    control = await _refusal(
        db,
        "INSERT INTO premium_unlocks (shop_id, customer_id, order_id) VALUES (:s, :c, :o)",
        {"s": two["shop"]["a"], "c": two["customer"]["a"], "o": order_a},
    )
    assert control == ""


# --- the bot says why ----------------------------------------------------------------------


async def test_picking_a_premium_design_without_the_gift_says_why_and_stays(
    db: AsyncConnection,
) -> None:
    from tests.test_share_pages_flow import MENU

    from gulbot.bot.callbacks import PageLangCB, PageMenuCB, PageQuestionCB, PlanCB

    bot = ShopBot(db, await make_shop(db, "Gift bot"), bot_id=530_001, username="gift_bot")
    await bot.say(MENU, user=PERSON)
    await bot.tap(PageMenuCB(action="yesno").pack(), user=PERSON)
    await bot.tap(PageLangCB(lang="uz").pack(), user=PERSON)
    await bot.tap(PageQuestionCB(preset="marry").pack(), user=PERSON)
    await bot.tap(PlanCB(action="skip").pack(), user=PERSON)
    bot.clear()
    await bot.tap(PageTemplateCB(template="deco").pack(), user=PERSON)
    assert bot.texts() == [LOCKED_UZ], bot.texts()
    await bot.tap(PageTemplateCB(template="romantik").pack(), user=PERSON)
    assert LOCKED_UZ not in bot.texts()[1:], "a free design was refused"
