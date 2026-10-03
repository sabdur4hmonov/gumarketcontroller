"""Shop A's bot can never create, read, delete or link a page of shop B's.

The same standard as the cross-shop routing fixes (AUDIT_MULTI_TENANT.md):
proven twice, once where Postgres refuses the row outright, and once through
the real dispatchers of two shops -- with the SAME person a customer of both,
because that is the case where an id or a token is most tempting to reuse.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import bound_session_factory
from tests.share_pages_harness import ShopBot, make_shop
from tests.test_share_pages_service import invite, yesno

from gulbot.bot.callbacks import MyPageCB, PageMenuCB
from gulbot.i18n.catalog import CATALOG
from gulbot.services import share_pages

pytestmark = pytest.mark.infra

PERSON = 990_101  # a customer of BOTH shops
OTHER = 990_102  # a second customer of shop A
GONE_UZ = CATALOG["pages.gone"]["uz"]


@pytest.fixture
async def two(db: AsyncConnection) -> dict[str, Any]:
    a = ShopBot(db, await make_shop(db, "Shop A"), bot_id=510_001, username="shop_a_bot")
    b = ShopBot(db, await make_shop(db, "Shop B"), bot_id=510_002, username="shop_b_bot")
    # First contact creates the customer in each shop.
    for bot in (a, b):
        await bot.say(CATALOG["btn.menu.help"]["uz"], user=PERSON)
    await a.say(CATALOG["btn.menu.help"]["uz"], user=OTHER)
    return {"a": a, "b": b, "db": db}


async def customer_id(db: AsyncConnection, shop_id: int, user: int) -> int:
    return int(
        await db.scalar(
            text("SELECT id FROM customers WHERE shop_id = :s AND telegram_user_id = :u"),
            {"s": shop_id, "u": user},
        )
    )


async def a_page_in(
    two: dict[str, Any], label: str, *, user: int = PERSON, kind: str = "yesno"
) -> Any:
    bot: ShopBot = two[label]
    session = bound_session_factory(two["db"])()
    page = await share_pages.create_page(
        session,
        shop_id=bot.shop_id,
        customer_id=await customer_id(two["db"], bot.shop_id, user),
        bot_username=bot.bot._me.username,  # noqa: SLF001
        draft=yesno() if kind == "yesno" else invite(),
    )
    await session.commit()
    return page


# --- the database itself ---------------------------------------------------------


async def test_a_page_cannot_be_filed_under_another_shops_customer(two: dict[str, Any]) -> None:
    db = two["db"]
    b_customer = await customer_id(db, two["b"].shop_id, PERSON)
    with pytest.raises(IntegrityError, match="fk_share_pages_customer_id_shop_id_customers"):
        async with db.begin_nested():
            await db.execute(
                text(
                    "INSERT INTO share_pages (shop_id, customer_id, token, kind, template, lang, "
                    " question_preset, question, expires_at) "
                    "VALUES (:a, :c, 'TTTTTTTTTTTTTTTTTTTTTT', 'yesno', 'milliy', 'uz', 'marry', "
                    " 'q', now() + interval '1 day')"
                ),
                {"a": two["a"].shop_id, "c": b_customer},
            )


async def test_an_rsvp_cannot_cross_shops(two: dict[str, Any]) -> None:
    page = await a_page_in(two, "a", kind="invite")
    with pytest.raises(IntegrityError, match="fk_share_page_rsvps_page_id_shop_id_share_pages"):
        async with two["db"].begin_nested():
            await two["db"].execute(
                text(
                    "INSERT INTO share_page_rsvps (shop_id, page_id, voter_key, answer, guests) "
                    "VALUES (:b, :p, 'vvvvvvvvvvvvvvvvvvvvvv', 'yes', 1)"
                ),
                {"b": two["b"].shop_id, "p": page.id},
            )


async def test_a_referral_cannot_join_shop_a_page_to_shop_b_customer(two: dict[str, Any]) -> None:
    page = await a_page_in(two, "a")
    b_customer = await customer_id(two["db"], two["b"].shop_id, PERSON)
    with pytest.raises(IntegrityError):
        async with two["db"].begin_nested():
            await two["db"].execute(
                text(
                    "INSERT INTO share_page_referrals (shop_id, page_id, customer_id) "
                    "VALUES (:a, :p, :c)"
                ),
                {"a": two["a"].shop_id, "p": page.id, "c": b_customer},
            )


# --- through the bots ---------------------------------------------------------------


async def test_a_page_made_in_shop_as_bot_is_shop_as_and_links_to_shop_as_bot(
    two: dict[str, Any],
) -> None:
    from tests.test_share_pages_flow import yesno_up_to_confirm

    from gulbot.bot.callbacks import PageConfirmCB

    for label in ("a", "b"):
        await yesno_up_to_confirm(two[label], user=PERSON)
        await two[label].tap(PageConfirmCB(action="create").pack(), user=PERSON)
    rows = (
        await two["db"].execute(
            text("SELECT shop_id, customer_id, bot_username FROM share_pages ORDER BY id")
        )
    ).all()
    a_customer = await customer_id(two["db"], two["a"].shop_id, PERSON)
    b_customer = await customer_id(two["db"], two["b"].shop_id, PERSON)
    assert [tuple(r) for r in rows] == [
        (two["a"].shop_id, a_customer, "shop_a_bot"),
        (two["b"].shop_id, b_customer, "shop_b_bot"),
    ]


@pytest.mark.parametrize("action", ["open", "delete", "really_delete"])
async def test_shop_bs_bot_cannot_open_or_delete_shop_as_page(
    two: dict[str, Any], action: str
) -> None:
    page = await a_page_in(two, "a")
    b: ShopBot = two["b"]
    b.clear()
    await b.tap(MyPageCB(action=action, page_id=page.id).pack(), user=PERSON)
    assert b.texts() == [GONE_UZ]
    assert all(page.token not in body for body in b.texts())
    live = await two["db"].scalar(
        text("SELECT deleted_at IS NULL FROM share_pages WHERE id = :id"), {"id": page.id}
    )
    assert live is True


@pytest.mark.parametrize("action", ["open", "really_delete"])
async def test_another_customer_of_the_same_shop_cannot_either(
    two: dict[str, Any], action: str
) -> None:
    page = await a_page_in(two, "a", user=PERSON)
    a: ShopBot = two["a"]
    a.clear()
    await a.tap(MyPageCB(action=action, page_id=page.id).pack(), user=OTHER)
    assert a.texts() == [GONE_UZ]
    live = await two["db"].scalar(
        text("SELECT deleted_at IS NULL FROM share_pages WHERE id = :id"), {"id": page.id}
    )
    assert live is True


async def test_the_owner_can_open_and_delete_their_own(two: dict[str, Any]) -> None:
    """The control: the same taps from the right customer in the right shop."""
    page = await a_page_in(two, "a")
    a: ShopBot = two["a"]
    await a.tap(MyPageCB(action="open", page_id=page.id).pack(), user=PERSON)
    assert any(page.token in body for body in a.texts())
    await a.tap(MyPageCB(action="really_delete", page_id=page.id).pack(), user=PERSON)
    live = await two["db"].scalar(
        text("SELECT deleted_at IS NULL FROM share_pages WHERE id = :id"), {"id": page.id}
    )
    assert live is False


async def test_my_pages_in_shop_b_does_not_list_shop_as_pages(two: dict[str, Any]) -> None:
    page = await a_page_in(two, "a")
    b: ShopBot = two["b"]
    b.clear()
    await b.tap(PageMenuCB(action="mine").pack(), user=PERSON)
    assert b.texts() == [CATALOG["pages.mine_empty"]["uz"]]
    markup = b.markups()[-1]
    labels = [btn.text for row in markup.inline_keyboard for btn in row] if markup else []
    assert not any("turmushga" in label for label in labels)
    _ = page


async def test_a_page_link_is_honoured_only_by_its_own_shops_bot(two: dict[str, Any]) -> None:
    page = await a_page_in(two, "a")
    await two["b"].say(f"/start pg_{page.token}", user=PERSON)
    count = await two["db"].scalar(text("SELECT count(*) FROM share_page_referrals"))
    assert count == 0
    await two["a"].say(f"/start pg_{page.token}", user=PERSON)
    rows = (
        await two["db"].execute(text("SELECT shop_id, page_id FROM share_page_referrals"))
    ).all()
    assert [tuple(r) for r in rows] == [(two["a"].shop_id, page.id)]


async def test_the_service_refuses_another_shops_token(two: dict[str, Any]) -> None:
    """Below the bot: shop B asking to record shop A's token gets False. Were
    the service's own shop filter ever lost, the composite FK would still
    refuse the row -- that is the second wall, and it is reported here as a
    failure rather than accepted as a pass."""
    page = await a_page_in(two, "a")
    session = bound_session_factory(two["db"])()
    b_customer = await customer_id(two["db"], two["b"].shop_id, PERSON)
    try:
        async with session.begin_nested():
            outcome: object = await share_pages.record_referral(
                session, shop_id=two["b"].shop_id, customer_id=b_customer, token=page.token
            )
    except IntegrityError:
        outcome = "refused only by the foreign key"
    assert outcome is False


async def test_a_malformed_start_payload_is_ignored(two: dict[str, Any]) -> None:
    for payload in ("pg_", "pg_' OR 1=1 --", "pg_" + "x" * 60, "other"):
        await two["a"].say(f"/start {payload}", user=PERSON)
    count = await two["db"].scalar(text("SELECT count(*) FROM share_page_referrals"))
    assert count == 0
