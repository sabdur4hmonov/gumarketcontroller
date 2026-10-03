"""The creator's "they said Ha": once, through the shop's own bot.

The registry is the real BotRegistry, with bots that record instead of calling
Telegram, and with a token per shop -- so "which bot sent it" is a fact of the
recording, not of a mock's say-so.
"""

from __future__ import annotations

from typing import Any

import pytest
from aiogram import Bot
from aiogram.methods import SendMessage
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.bot_harness import RecordingSession, bound_session_factory
from tests.test_share_pages_service import make_customer, make_shop, yesno

from gulbot.bot.registry import BotRegistry
from gulbot.sending import page_notify
from gulbot.sending.page_notify import NotifyRetry, notify_page_answer
from gulbot.sending.transport import ShopBotUnavailable
from gulbot.services import share_pages

pytestmark = pytest.mark.infra

TOKEN = {
    "A": "111111:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    "B": "222222:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
}


class Bots:
    def __init__(self, token_by_shop: dict[int, str]) -> None:
        self.token_by_shop = token_by_shop
        self.sessions: dict[str, RecordingSession] = {}

    def token_for(self, shop_id: int) -> str:
        try:
            return self.token_by_shop[shop_id]
        except KeyError:
            raise ShopBotUnavailable(shop_id, "no token in this test") from None

    def bot(self, token: str | None) -> Bot:
        assert token is not None
        session = self.sessions.setdefault(token, RecordingSession())
        return Bot(token=token, session=session)

    def sent(self, label: str) -> list[Any]:
        session = self.sessions.get(TOKEN[label])
        return [] if session is None else [c for c in session.calls if isinstance(c, SendMessage)]


@pytest.fixture
async def two_shops(db: AsyncConnection, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    world: dict[str, Any] = {"shop": {}, "page": {}}
    session = bound_session_factory(db)()
    for n, label in enumerate(("A", "B")):
        shop = await make_shop(db, f"Shop {label}")
        # The same person is a customer of both shops.
        customer = await make_customer(db, shop, 7_700)
        page = await share_pages.create_page(
            session,
            shop_id=shop,
            customer_id=customer,
            bot_username=f"shop{label}_bot",
            draft=yesno(question=f"Savol {label}"),
        )
        await share_pages.answer_yes(session, page.token)
        world["shop"][label], world["page"][label] = shop, page.id
        _ = n
    await session.commit()
    bots = Bots({world["shop"]["A"]: TOKEN["A"], world["shop"]["B"]: TOKEN["B"]})

    async def registry_for(
        _session: Any, *, shop_ids: Any = None, bot_factory: Any = None
    ) -> BotRegistry:
        return BotRegistry(token_for=bots.token_for, bot_factory=bots.bot)

    monkeypatch.setattr(page_notify, "registry_for", registry_for)
    world["bots"], world["db"] = bots, db
    return world


async def _notify(world: dict[str, Any], label: str) -> str:
    """The outcome, with a retry reported as one rather than raised, so a
    test expecting a send fails on its assertion."""
    try:
        return await notify_page_answer(
            world["page"][label], session_factory=bound_session_factory(world["db"])
        )
    except NotifyRetry as retry:
        return f"retry: {retry}"


async def test_each_shops_page_is_announced_by_its_own_bot(two_shops: dict[str, Any]) -> None:
    assert await _notify(two_shops, "A") == page_notify.OUTCOME_SENT
    bots: Bots = two_shops["bots"]
    assert [m.text for m in bots.sent("A")] and "Savol A" in bots.sent("A")[0].text
    assert bots.sent("B") == []
    assert await _notify(two_shops, "B") == page_notify.OUTCOME_SENT
    assert len(bots.sent("A")) == 1 and len(bots.sent("B")) == 1
    assert "Savol B" in bots.sent("B")[0].text
    assert bots.sent("A")[0].chat_id == 7_700


async def test_the_creator_is_told_once(two_shops: dict[str, Any]) -> None:
    assert await _notify(two_shops, "A") == page_notify.OUTCOME_SENT
    assert await _notify(two_shops, "A") == page_notify.OUTCOME_NOTHING
    assert len(two_shops["bots"].sent("A")) == 1


async def test_a_failed_send_releases_the_claim_for_a_retry(
    two_shops: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from gulbot.sending.telegram import TelegramTransport
    from gulbot.sending.transport import SendResult

    async def flaky(self: Any, **kwargs: Any) -> SendResult:
        return SendResult.failed("network")

    monkeypatch.setattr(TelegramTransport, "send_text", flaky)
    assert (await _notify(two_shops, "A")).startswith("retry")
    claimed = await two_shops["db"].scalar(
        text("SELECT notified_at FROM share_pages WHERE id = :id"), {"id": two_shops["page"]["A"]}
    )
    assert claimed is None


async def test_a_blocked_creator_is_not_retried(
    two_shops: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from gulbot.sending.telegram import TelegramTransport
    from gulbot.sending.transport import SendResult

    async def blocked(self: Any, **kwargs: Any) -> SendResult:
        return SendResult.forbidden()

    monkeypatch.setattr(TelegramTransport, "send_text", blocked)
    assert await _notify(two_shops, "A") == page_notify.OUTCOME_BLOCKED
    assert await _notify(two_shops, "A") == page_notify.OUTCOME_NOTHING


async def test_a_shop_without_a_bot_fails_loudly_and_keeps_the_page_retryable(
    two_shops: dict[str, Any],
) -> None:
    two_shops["bots"].token_by_shop.pop(two_shops["shop"]["B"])
    assert (await _notify(two_shops, "B")).startswith("retry")
    assert two_shops["bots"].sent("A") == []
