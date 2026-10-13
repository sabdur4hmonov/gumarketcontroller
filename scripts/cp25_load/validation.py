"""Completeness checks for capacity measurements; no production changes."""

from __future__ import annotations

from collections import Counter
from typing import Any, cast


def reconcile_deliveries(replies: Any, *, shops: int, fault: str) -> None:
    expected: Counter[tuple[int, int, str]] = Counter()
    for shop in range(1, shops + 1):
        bot = 600000 + shop
        if shop != 1 or fault == "none":
            for wave in range(3):
                expected[(bot, 2000000 + wave * 10000 + shop, "customer")] = 1
            expected[(bot, 3000000 + shop, "owner")] = 1
            expected[(bot, -1001000000 - shop, "other")] = 1
        if shop != 1 or fault in ("none", "poll-flood"):
            expected[(bot, 2000000 + shop, "other")] = 1
            expected[(bot, -1002000000 - shop, "other")] = 1
    actual: Counter[tuple[int, int, str]] = Counter()
    fault_races = {(600001, 2000001 + wave * 10000, "customer") for wave in range(3)} | {
        (600001, 3000001, "owner"),
        (600001, -1001000001, "other"),
        (600001, 2000001, "other"),
        (600001, -1002000001, "other"),
    }
    for reply in replies:
        key = (reply["bot_id"], reply["chat_id"], reply["role"])
        # Bad-shop update work may race the injected fault. It is not evidence
        # of healthy capacity. Its independent worker sends still must match.
        if fault != "none" and key in fault_races and key not in expected:
            continue
        if reply["method"] in ("sendMessage", "sendPhoto"):
            actual[key] += 1
    if actual != expected:
        raise ValueError(
            f"Incomplete/duplicate delivery: missing={dict(expected - actual)}, "
            f"extra={dict(actual - expected)}"
        )


def validate_outboxes(metrics: dict[str, Any], healthy_shops: int) -> None:
    """Reject incomplete reminder/order work before publishing a measurement."""
    for name in ("reminder_ticks", "order_ticks"):
        ticks = metrics.get(name)
        if not isinstance(ticks, list) or not ticks:
            raise ValueError(f"{name}: missing measured ticks")
        counts = [tick.get("sent") for tick in ticks if isinstance(tick, dict)]
        if len(counts) != len(ticks) or any(type(sent) is not int or sent < 0 for sent in counts):
            raise ValueError(f"{name}: invalid delivery counts")
        total = sum(cast(list[int], counts))
        if total != healthy_shops:
            raise ValueError(f"{name}: delivered {total}; expected {healthy_shops}")
