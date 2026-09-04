"""The three-tier fallback chains, and the fact that they are TOTAL.

Every combination of (customer set / customer NULL) x (shop set / shop unset)
is walked, asserting both the VALUE and which tier supplied it. Asserting the
source matters: the right value arriving from the wrong tier means the chain is
not actually falling through, and the bug only shows up when the tiers disagree.
"""

from __future__ import annotations

from datetime import time

import pytest

from gulbot.models.customer import (
    DEFAULT_REMINDER_COUNT,
    DEFAULT_SEND_TIME,
    REMINDER_COUNT_OFFSETS,
    Customer,
)
from gulbot.models.shop import Shop
from gulbot.services.reminder_settings import (
    SettingSource,
    resolve_offsets,
    resolve_reminder_settings,
    resolve_send_time,
)

CUSTOMER_TIME = time(9, 0)
SHOP_TIME = time(13, 0)
SHOP_OFFSETS = [-14, -2]


def make_customer(*, count: int | None, send_time: time | None) -> Customer:
    customer = Customer()
    customer.reminder_count = count
    customer.preferred_send_time = send_time
    return customer


def make_shop(*, offsets: list[int] | None, send_time: time | None) -> Shop:
    shop = Shop()
    shop.reminder_offsets = [] if offsets is None else offsets
    shop.default_send_time = send_time
    return shop


# --- the four combinations, send time --------------------------------------


@pytest.mark.parametrize(
    ("customer_time", "shop_time", "expected", "expected_source"),
    [
        (CUSTOMER_TIME, SHOP_TIME, CUSTOMER_TIME, SettingSource.CUSTOMER),
        (CUSTOMER_TIME, None, CUSTOMER_TIME, SettingSource.CUSTOMER),
        (None, SHOP_TIME, SHOP_TIME, SettingSource.SHOP),
        (None, None, DEFAULT_SEND_TIME, SettingSource.CONSTANT),
    ],
    ids=[
        "customer-set_shop-set",
        "customer-set_shop-unset",
        "customer-null_shop-set",
        "customer-null_shop-unset",
    ],
)
def test_send_time_falls_through_in_order(
    customer_time: time | None,
    shop_time: time | None,
    expected: time,
    expected_source: SettingSource,
) -> None:
    customer = make_customer(count=None, send_time=customer_time)
    shop = make_shop(offsets=None, send_time=shop_time)
    value, source = resolve_send_time(customer, shop)
    assert value == expected
    assert source == expected_source


# --- the four combinations, offsets ----------------------------------------


@pytest.mark.parametrize(
    ("customer_count", "shop_offsets", "expected", "expected_source"),
    [
        (1, SHOP_OFFSETS, (0,), SettingSource.CUSTOMER),
        (1, None, (0,), SettingSource.CUSTOMER),
        (None, SHOP_OFFSETS, (-14, -2), SettingSource.SHOP),
        (
            None,
            None,
            REMINDER_COUNT_OFFSETS[DEFAULT_REMINDER_COUNT],
            SettingSource.CONSTANT,
        ),
    ],
    ids=[
        "customer-set_shop-set",
        "customer-set_shop-unset",
        "customer-null_shop-set",
        "customer-null_shop-unset",
    ],
)
def test_offsets_fall_through_in_order(
    customer_count: int | None,
    shop_offsets: list[int] | None,
    expected: tuple[int, ...],
    expected_source: SettingSource,
) -> None:
    customer = make_customer(count=customer_count, send_time=None)
    shop = make_shop(offsets=shop_offsets, send_time=None)
    value, source = resolve_offsets(customer, shop)
    assert value == expected
    assert source == expected_source


# --- mapping and totality --------------------------------------------------


@pytest.mark.parametrize(("count", "expected"), [(1, (0,)), (2, (-1, 0)), (3, (-7, -1, 0))])
def test_each_reminder_count_maps_to_its_offsets(count: int, expected: tuple[int, ...]) -> None:
    customer = make_customer(count=count, send_time=None)
    shop = make_shop(offsets=SHOP_OFFSETS, send_time=None)
    assert resolve_offsets(customer, shop)[0] == expected


def test_the_two_chains_resolve_independently() -> None:
    """A customer may set one and not the other."""
    customer = make_customer(count=2, send_time=None)
    shop = make_shop(offsets=SHOP_OFFSETS, send_time=SHOP_TIME)
    settings = resolve_reminder_settings(customer, shop)

    assert settings.offsets == (-1, 0)
    assert settings.offsets_source == SettingSource.CUSTOMER
    assert settings.send_time == SHOP_TIME
    assert settings.send_time_source == SettingSource.SHOP


def test_resolution_never_fails_on_any_combination() -> None:
    """The chain is total: no input resolves to nothing."""
    for count in (None, 1, 2, 3):
        for customer_time in (None, CUSTOMER_TIME):
            for shop_offsets in (None, SHOP_OFFSETS):
                for shop_time in (None, SHOP_TIME):
                    settings = resolve_reminder_settings(
                        make_customer(count=count, send_time=customer_time),
                        make_shop(offsets=shop_offsets, send_time=shop_time),
                    )
                    assert settings.offsets, (count, shop_offsets)
                    assert isinstance(settings.send_time, time)


def test_an_empty_shop_offset_list_means_unset_not_silence() -> None:
    """A shop silencing reminders would deactivate, not configure an empty list."""
    customer = make_customer(count=None, send_time=None)
    shop = make_shop(offsets=[], send_time=None)
    offsets, source = resolve_offsets(customer, shop)
    assert offsets == REMINDER_COUNT_OFFSETS[DEFAULT_REMINDER_COUNT]
    assert source == SettingSource.CONSTANT


def test_shop_offsets_are_deduplicated_and_ordered() -> None:
    customer = make_customer(count=None, send_time=None)
    shop = make_shop(offsets=[0, -7, -7, -1], send_time=None)
    assert resolve_offsets(customer, shop)[0] == (-7, -1, 0)


def test_an_out_of_range_customer_count_falls_through() -> None:
    """A value the CHECK constraint would refuse must not crash the scheduler."""
    customer = make_customer(count=None, send_time=None)
    customer.reminder_count = 9  # not in REMINDER_COUNT_OFFSETS
    shop = make_shop(offsets=SHOP_OFFSETS, send_time=None)
    offsets, source = resolve_offsets(customer, shop)
    assert offsets == (-14, -2)
    assert source == SettingSource.SHOP
