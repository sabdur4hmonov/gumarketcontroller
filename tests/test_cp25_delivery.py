"""A matching total cannot hide a missing shop or duplicated delivery."""

from __future__ import annotations

import pytest
from scripts.cp25_load.validation import reconcile_deliveries


def workload() -> list[dict[str, int | str]]:
    return [
        {"bot_id": bot, "chat_id": chat, "role": role, "method": method}
        for bot in (600001, 600002)
        for chat, role, method in (
            (2000000 + bot - 600000, "customer", "sendMessage"),
            (2010000 + bot - 600000, "customer", "sendMessage"),
            (2020000 + bot - 600000, "customer", "sendMessage"),
            (3000000 + bot - 600000, "owner", "sendMessage"),
            (2000000 + bot - 600000, "other", "sendMessage"),
            (-1002000000 - bot + 600000, "other", "sendPhoto"),
            (-1001000000 - bot + 600000, "other", "sendPhoto"),
        )
    ]


def test_deliveries_require_every_target_exactly_once() -> None:
    reconcile_deliveries(workload(), shops=2, fault="none")


def test_extra_cross_shop_delivery_cannot_be_silently_ignored() -> None:
    replies = workload()
    replies.append({"bot_id": 600002, "chat_id": 2000001, "role": "other", "method": "sendMessage"})
    assert refused(replies), "An extra message to another shop's customer invalidates evidence"


def test_an_unregistered_bot_cannot_add_a_delivery() -> None:
    replies = workload()
    replies.append({"bot_id": 600009, "chat_id": 2000001, "role": "other", "method": "sendPhoto"})
    assert refused(replies), "Every sending bot must belong to the fixture fleet"


def refused(replies: list[dict[str, int | str]], *, fault: str = "none") -> bool:
    try:
        reconcile_deliveries(replies, shops=2, fault=fault)
    except ValueError:
        return True
    return False


@pytest.mark.parametrize("index", [0, 3, 4, 5, 6])
def test_delivery_total_cannot_hide_missing_shop_with_duplicate(index: int) -> None:
    replies = workload()
    replies[index] = replies[index + 7]
    assert refused(replies), "Missing and duplicate shop deliveries must be rejected"


def test_edits_cannot_count_as_sent_announcements() -> None:
    replies = workload()
    replies[6]["method"] = "editMessageMedia"
    assert refused(replies), "An edit must not count as a new channel post"


def test_poll_fault_still_requires_outgoing_messages_from_bad_shop() -> None:
    replies = [r for r in workload() if r["bot_id"] != 600001 or r["role"] == "other"]
    # Publishing originates in that shop's missing update, unlike worker sends.
    replies = [r for r in replies if r["chat_id"] != -1001000001]
    reconcile_deliveries(replies, shops=2, fault="poll-flood")
    assert refused([r for r in replies if r["chat_id"] != -1002000001], fault="poll-flood"), (
        "A polling fault does not excuse missing worker deliveries"
    )
