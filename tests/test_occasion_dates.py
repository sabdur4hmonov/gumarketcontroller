"""Month/day validity, enforced at all three layers.

The picker is the first line of defence, the Python validator the second, and a
Postgres CHECK constraint the third. Each is tested against every month rather
than a couple of hand-picked cases.
"""

from __future__ import annotations

import calendar

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.test_tenancy import _make_customer, _make_shop

from gulbot.bot.keyboards import day_keyboard
from gulbot.models.occasion import MAX_DAY_IN_MONTH
from gulbot.services.occasions import is_valid_month_day, is_valid_year

ALL_MONTHS = range(1, 13)


def picker_days(month: int) -> list[int]:
    """Days actually offered by the keyboard, ignoring the trailing Back row."""
    keyboard = day_keyboard("uz", month)
    return [int(b.text) for row in keyboard.inline_keyboard[:-1] for b in row]


@pytest.mark.parametrize("month", ALL_MONTHS)
def test_picker_offers_exactly_the_valid_days(month: int) -> None:
    """Structural: an impossible day is never on screen to begin with."""
    days = picker_days(month)
    assert days == list(range(1, MAX_DAY_IN_MONTH[month - 1] + 1))


@pytest.mark.parametrize("month", ALL_MONTHS)
def test_picker_never_offers_an_impossible_day(month: int) -> None:
    """Feb 30 and Apr 31 are unreachable, not merely rejected."""
    days = picker_days(month)
    assert MAX_DAY_IN_MONTH[month - 1] + 1 not in days
    assert 32 not in days


@pytest.mark.parametrize("month", ALL_MONTHS)
def test_picker_matches_a_leap_year_calendar(month: int) -> None:
    """Cross-checked against the stdlib rather than against our own constant."""
    expected = calendar.monthrange(2024, month)[1]  # 2024 is a leap year
    assert picker_days(month)[-1] == expected


@pytest.mark.parametrize("month", ALL_MONTHS)
def test_validator_agrees_with_the_picker(month: int) -> None:
    last = MAX_DAY_IN_MONTH[month - 1]
    assert is_valid_month_day(month, last)
    assert not is_valid_month_day(month, last + 1)
    assert not is_valid_month_day(month, 0)


@pytest.mark.parametrize("month_day", [(2, 30), (2, 31), (4, 31), (6, 31), (9, 31), (11, 31)])
def test_validator_refuses_known_impossible_pairs(month_day: tuple[int, int]) -> None:
    assert not is_valid_month_day(*month_day)


@pytest.mark.parametrize("month", [0, 13, -1, 99])
def test_validator_refuses_impossible_months(month: int) -> None:
    assert not is_valid_month_day(month, 1)


def test_february_29_is_allowed_without_a_year() -> None:
    """A Feb 29 occasion is legitimate; CP4 decides how it fires in common years."""
    assert is_valid_month_day(2, 29)


@pytest.mark.parametrize("year", [2024, 2000, 2028])
def test_february_29_accepts_leap_years(year: int) -> None:
    assert is_valid_year(year, 2, 29)


@pytest.mark.parametrize("year", [2023, 1900, 2100, 2026])
def test_february_29_refuses_common_years(year: int) -> None:
    assert not is_valid_year(year, 2, 29)


@pytest.mark.parametrize("year", [1899, 2101, 0])
def test_year_range_is_enforced(year: int) -> None:
    assert not is_valid_year(year, 3, 8)


# --- the database is the last line of defence ------------------------------


async def _make_recipient(db: AsyncConnection, shop: int, customer: int) -> int:
    """occasions.recipient_id is NOT NULL as of CP3.5."""
    result = await db.execute(
        text(
            "INSERT INTO recipients (shop_id, customer_id, label, type) "
            "VALUES (:s, :c, 'X', 'custom') RETURNING id"
        ),
        {"s": shop, "c": customer},
    )
    return int(result.scalar_one())


async def _insert(db: AsyncConnection, shop: int, customer: int, **kwargs: object) -> None:
    recipient = kwargs.pop("recipient", None) or await _make_recipient(db, shop, customer)
    payload = {
        "s": shop,
        "c": customer,
        "r": recipient,
        "label": "X",
        "type": "custom",
        **kwargs,
    }
    await db.execute(
        text(
            "INSERT INTO occasions "
            "(shop_id, customer_id, recipient_id, label, type, month, day, year) "
            "VALUES (:s, :c, :r, :label, :type, :month, :day, :year)"
        ),
        {"year": None, **payload},
    )


@pytest.mark.infra
@pytest.mark.parametrize("month", ALL_MONTHS)
async def test_postgres_accepts_the_last_valid_day_of_every_month(
    db: AsyncConnection, month: int
) -> None:
    shop = await _make_shop(db, f"S{month}")
    customer = await _make_customer(db, shop, tg_id=month)
    await _insert(db, shop, customer, month=month, day=MAX_DAY_IN_MONTH[month - 1])


@pytest.mark.infra
@pytest.mark.parametrize("month", ALL_MONTHS)
async def test_postgres_refuses_one_day_past_every_month(db: AsyncConnection, month: int) -> None:
    """Proves the CHECK, not the ORM, rejects Feb 30 and Apr 31."""
    shop = await _make_shop(db, f"S{month}")
    customer = await _make_customer(db, shop, tg_id=month)
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await _insert(db, shop, customer, month=month, day=MAX_DAY_IN_MONTH[month - 1] + 1)
    assert "ck_occasions_day_matches_month" in str(excinfo.value)


@pytest.mark.infra
async def test_postgres_refuses_february_29_in_a_common_year(db: AsyncConnection) -> None:
    shop = await _make_shop(db, "S")
    customer = await _make_customer(db, shop, tg_id=1)
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await _insert(db, shop, customer, month=2, day=29, year=2023)
    assert "ck_occasions_feb29_needs_leap_year" in str(excinfo.value)


@pytest.mark.infra
async def test_postgres_allows_february_29_in_a_leap_year(db: AsyncConnection) -> None:
    shop = await _make_shop(db, "S")
    customer = await _make_customer(db, shop, tg_id=1)
    await _insert(db, shop, customer, month=2, day=29, year=2024)


@pytest.mark.infra
async def test_postgres_refuses_month_13(db: AsyncConnection) -> None:
    shop = await _make_shop(db, "S")
    customer = await _make_customer(db, shop, tg_id=1)
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await _insert(db, shop, customer, month=13, day=1)
    assert "ck_occasions_month_range" in str(excinfo.value)


@pytest.mark.infra
async def test_an_occasion_cannot_be_claimed_by_another_shop(db: AsyncConnection) -> None:
    """The composite FK from CP1, now actually load-bearing."""
    shop_a = await _make_shop(db, "A")
    shop_b = await _make_shop(db, "B")
    customer_a = await _make_customer(db, shop_a, tg_id=1)
    recipient_a = await _make_recipient(db, shop_a, customer_a)
    with pytest.raises(IntegrityError) as excinfo:
        async with db.begin_nested():
            await _insert(db, shop_b, customer_a, recipient=recipient_a, month=3, day=8)
    assert "fk_occasions_customer_id_shop_id_customers" in str(excinfo.value)
