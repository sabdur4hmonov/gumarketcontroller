"""Resolving which offsets and send time apply to a given customer.

The chain is TOTAL, not partial: every tier has a successor, so there is no
input for which resolution fails. Tier 3 should be unreachable in practice --
shops carry their own default -- but "should not happen" is not a guarantee,
and a scheduler that raises on an odd row stops scheduling for everyone.

Offsets:
    1. customers.reminder_count -> REMINDER_COUNT_OFFSETS[count]
    2. shops.reminder_offsets
    3. REMINDER_COUNT_OFFSETS[DEFAULT_REMINDER_COUNT]

Send time:
    1. customers.preferred_send_time
    2. shops.default_send_time
    3. DEFAULT_SEND_TIME

This lives in services/, not scheduling/, on purpose: the pure occurrence engine
takes offsets and a send time as ARGUMENTS and must never learn the names of
database columns. tests/test_preferences.py enforces that boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from enum import StrEnum

from gulbot.models.customer import (
    DEFAULT_REMINDER_COUNT,
    DEFAULT_SEND_TIME,
    REMINDER_COUNT_OFFSETS,
    Customer,
)
from gulbot.models.shop import Shop


class SettingSource(StrEnum):
    """Which tier of the chain actually supplied the value."""

    CUSTOMER = "customer"
    SHOP = "shop"
    CONSTANT = "constant"


@dataclass(frozen=True)
class ReminderSettings:
    offsets: tuple[int, ...]
    send_time: time
    offsets_source: SettingSource
    send_time_source: SettingSource


def resolve_offsets(customer: Customer, shop: Shop) -> tuple[tuple[int, ...], SettingSource]:
    count = customer.reminder_count
    if count is not None and count in REMINDER_COUNT_OFFSETS:
        return REMINDER_COUNT_OFFSETS[count], SettingSource.CUSTOMER

    shop_offsets = shop.reminder_offsets
    # An empty array is "unset", not "no reminders at all": a shop that wanted
    # to silence reminders would deactivate, not configure an empty list.
    if shop_offsets:
        return tuple(sorted(set(shop_offsets))), SettingSource.SHOP

    return REMINDER_COUNT_OFFSETS[DEFAULT_REMINDER_COUNT], SettingSource.CONSTANT


def resolve_send_time(customer: Customer, shop: Shop) -> tuple[time, SettingSource]:
    if customer.preferred_send_time is not None:
        return customer.preferred_send_time, SettingSource.CUSTOMER
    if shop.default_send_time is not None:
        return shop.default_send_time, SettingSource.SHOP
    return DEFAULT_SEND_TIME, SettingSource.CONSTANT


def resolve_reminder_settings(customer: Customer, shop: Shop) -> ReminderSettings:
    offsets, offsets_source = resolve_offsets(customer, shop)
    send_time, send_time_source = resolve_send_time(customer, shop)
    return ReminderSettings(
        offsets=offsets,
        send_time=send_time,
        offsets_source=offsets_source,
        send_time_source=send_time_source,
    )
