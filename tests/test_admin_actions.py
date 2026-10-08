# ruff: noqa: F811, F401  -- fixtures are imported by name; pytest injects them into
# the same-named test parameters, which ruff reads as a redefinition.
"""CP18: what a platform admin can do, and that each action is recorded.

Every action is tested at the service, where the screens call it: the state
it changes, the audit entry it writes in the same transaction (before ->
after, admin, reason, address), and the refusals that change nothing.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import bound_session_factory
from tests.test_dispatcher import NOW, add_due_row, world

from gulbot.services import shop_admin
from gulbot.services.admin_auth import Admin

pytestmark = pytest.mark.infra

ADMIN = Admin(telegram_id=7_100_001, csrf="c" * 43, session_id=0)
IP = "203.0.113.7"


async def audit_rows(db: AsyncConnection) -> list[dict[str, Any]]:
    result = await db.execute(
        text(
            "SELECT admin_telegram_id, action, shop_id, target_type, target_id, before, after, "
            "reason, ip FROM admin_audit_log ORDER BY id"
        )
    )
    return [dict(r) for r in result.mappings()]


async def shop_row(db: AsyncConnection, shop_id: int) -> dict[str, Any]:
    result = await db.execute(
        text(
            "SELECT status, status_changed_at, subscription_status, paid_until "
            "FROM shops WHERE id = :s"
        ),
        {"s": shop_id},
    )
    return dict(result.mappings().one())


# --- pause and resume -------------------------------------------------------------


async def test_pausing_changes_the_shop_and_records_who_why_and_from_where(
    db: AsyncConnection, world: dict[str, Any]
) -> None:
    shop = world["shop_id"]
    async with bound_session_factory(db)() as session:
        after = await shop_admin.set_shop_status(
            session, admin=ADMIN, shop_id=shop, status="paused", reason="  owner  asked ", ip=IP
        )
        await session.commit()
    assert after["status"] == "paused"
    row = await shop_row(db, shop)
    assert row["status"] == "paused" and row["status_changed_at"] is not None
    (entry,) = await audit_rows(db)
    assert entry["action"] == "shop_pause"
    assert (entry["admin_telegram_id"], entry["shop_id"], entry["ip"]) == (
        ADMIN.telegram_id,
        shop,
        IP,
    )
    assert (entry["target_type"], entry["target_id"]) == ("shop", shop)
    assert entry["before"]["status"] == "active" and entry["after"]["status"] == "paused"
    assert entry["reason"] == "owner asked"


async def test_resuming_says_how_many_waiting_reminders_will_expire_instead_of_firing(
    db: AsyncConnection, world: dict[str, Any]
) -> None:
    shop = world["shop_id"]
    now = datetime.now(UTC)
    await add_due_row(db, world, day=1, due=now - timedelta(hours=7))  # past the 6 h grace
    await add_due_row(db, world, day=2, due=now - timedelta(minutes=5))  # still fresh
    async with bound_session_factory(db)() as session:
        await shop_admin.set_shop_status(
            session, admin=ADMIN, shop_id=shop, status="paused", reason=None, ip=IP, now=now
        )
        after = await shop_admin.set_shop_status(
            session, admin=ADMIN, shop_id=shop, status="active", reason=None, ip=IP, now=now
        )
        await session.commit()
    assert after["reminders_expiring_on_resume"] == 1
    assert [e["action"] for e in await audit_rows(db)] == ["shop_pause", "shop_resume"]


async def test_an_unknown_status_or_shop_is_refused_and_nothing_is_recorded(
    db: AsyncConnection, world: dict[str, Any]
) -> None:
    for shop_id, status, reason in (
        (world["shop_id"], "closed", "status"),
        (2**52, "paused", "shop"),
    ):
        async with bound_session_factory(db)() as session:
            try:
                await shop_admin.set_shop_status(
                    session, admin=ADMIN, shop_id=shop_id, status=status, reason=None, ip=IP
                )
            except shop_admin.ActionRefused as refused:
                assert refused.reason == reason
            else:
                raise AssertionError(f"{status!r} for shop {shop_id} was accepted")
    assert await audit_rows(db) == []
    assert (await shop_row(db, world["shop_id"]))["status"] == "active"


# --- the subscription -----------------------------------------------------------------


async def test_marking_paid_writes_the_ledger_the_shop_and_the_audit(
    db: AsyncConnection, world: dict[str, Any]
) -> None:
    shop = world["shop_id"]
    until = date(2027, 1, 15)
    async with bound_session_factory(db)() as session:
        await shop_admin.mark_paid(
            session,
            admin=ADMIN,
            shop_id=shop,
            payment=shop_admin.Payment(
                paid_until=until, amount_uzs=150_000, method="cash", note="yanvar"
            ),
            ip=IP,
        )
        await session.commit()
    row = await shop_row(db, shop)
    assert (row["subscription_status"], row["paid_until"]) == ("paid", until)
    ledger = (
        await db.execute(
            text(
                "SELECT shop_id, amount_uzs, method, note, paid_until, admin_telegram_id "
                "FROM subscription_payments"
            )
        )
    ).all()
    assert ledger == [(shop, 150_000, "cash", "yanvar", until, ADMIN.telegram_id)]
    (entry,) = await audit_rows(db)
    assert entry["action"] == "subscription_paid"
    assert entry["before"]["subscription_status"] == "none"
    assert entry["after"]["paid_until"] == "2027-01-15" and entry["after"]["amount_uzs"] == 150_000


@pytest.mark.parametrize(("amount", "method"), [(0, "cash"), (-5, "cash"), (100, "bitcoin")])
async def test_a_bad_payment_is_refused_and_nothing_is_written(
    db: AsyncConnection, world: dict[str, Any], amount: int, method: str
) -> None:
    async with bound_session_factory(db)() as session:
        try:
            await shop_admin.mark_paid(
                session,
                admin=ADMIN,
                shop_id=world["shop_id"],
                payment=shop_admin.Payment(
                    paid_until=date(2027, 1, 1), amount_uzs=amount, method=method
                ),
                ip=IP,
            )
        except Exception as error:  # noqa: BLE001 - the type is the assertion
            refused: BaseException | None = error
        else:
            refused = None
    # Refused HERE, by the service -- a database CHECK firing behind a
    # missing guard is a failed assertion, not a pass.
    assert isinstance(refused, shop_admin.ActionRefused), repr(refused)
    assert refused.reason == "payment"
    assert await db.scalar(text("SELECT count(*) FROM subscription_payments")) == 0
    assert await audit_rows(db) == []


async def _refusal(db: AsyncConnection, sql: str, params: dict[str, Any]) -> str:
    try:
        async with db.begin_nested():
            await db.execute(text(sql), params)
    except Exception as error:  # noqa: BLE001 - the constraint's name is the assertion
        return str(error)
    return ""


async def test_the_database_refuses_an_unknown_subscription_or_a_free_payment(
    db: AsyncConnection, world: dict[str, Any]
) -> None:
    shop = world["shop_id"]
    unknown = await _refusal(
        db, "UPDATE shops SET subscription_status = 'gold' WHERE id = :s", {"s": shop}
    )
    assert "ck_shops_subscription_known" in unknown, unknown or "'gold' was accepted"
    free = await _refusal(
        db,
        "INSERT INTO subscription_payments (shop_id, amount_uzs, method, paid_until, "
        "admin_telegram_id) VALUES (:s, 0, 'cash', '2027-01-01', 1)",
        {"s": shop},
    )
    assert "ck_subscription_payments_amount_positive" in free, free or "a free payment was accepted"


async def test_a_payment_can_only_be_filed_under_a_shop_that_exists(db: AsyncConnection) -> None:
    orphan = await _refusal(
        db,
        "INSERT INTO subscription_payments (shop_id, amount_uzs, method, paid_until, "
        "admin_telegram_id) VALUES (:s, 1, 'cash', '2027-01-01', 1)",
        {"s": 2**52},
    )
    assert "fk_subscription_payments_shop_id_shops" in orphan, (
        orphan or "an orphan payment was accepted"
    )
