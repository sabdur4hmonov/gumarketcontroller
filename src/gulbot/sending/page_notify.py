"""The one message a Ha/Yo'q page's creator gets: "they said Ha".

EXACTLY ONCE per page, on the CP6 pattern: the claim (`notified_at`) is
COMMITTED before Telegram is called, so a retried task, a second worker or a
second Ha cannot send it twice. A send that fails for a reason worth retrying
releases the claim and raises NotifyRetry, and the task tries again. A send
refused because the creator blocked the bot keeps the claim: that is their
decision, not an error.

THROUGH THE SHOP'S OWN BOT. The page belongs to a shop and the creator met it in
that shop's bot; the registry resolves the shop's bot exactly as every other
send path does (C1/C2 of AUDIT_MULTI_TENANT.md), so shop B's bot can never
deliver shop A's page's news.
"""

from __future__ import annotations

import logging
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gulbot.bot.registry import BotFactory, build_bot_for, registry_for
from gulbot.i18n import t
from gulbot.sending.telegram import TelegramTransport
from gulbot.sending.transport import SendResult, ShopBotUnavailable
from gulbot.services.share_pages import claim_notification, release_notification
from gulbot.utils.render import escape

log = logging.getLogger("gulbot.sending.page_notify")

OUTCOME_SENT: Final = "sent"
OUTCOME_NOTHING: Final = "nothing"
OUTCOME_BLOCKED: Final = "blocked"


class NotifyRetry(Exception):
    """The send failed for a reason worth another attempt; the claim is released."""


async def notify_page_answer(
    page_id: int,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    bot_factory: BotFactory = build_bot_for,
) -> str:
    async with session_factory() as session:
        target = await claim_notification(session, page_id=page_id)
        await session.commit()
    if target is None:
        return OUTCOME_NOTHING

    body = t("pages.notify_yes", target.lang, question=escape(target.question))
    async with session_factory() as session:
        registry = await registry_for(session, shop_ids=[target.shop_id], bot_factory=bot_factory)
    try:
        try:
            transport = TelegramTransport(registry.bot_for(target.shop_id))
        except ShopBotUnavailable as missing:
            log.error("page %s: %s", page_id, missing)
            result = SendResult.failed("no_bot")
        else:
            result = await transport.send_text(chat_id=target.telegram_user_id, text=body)
    finally:
        await registry.close()

    if result.ok:
        log.info("page %s: creator told", page_id)
        return OUTCOME_SENT
    if result.blocked:
        log.info("page %s: the creator has blocked the bot; not retrying", page_id)
        return OUTCOME_BLOCKED
    async with session_factory() as session:
        await release_notification(session, page_id=page_id)
        await session.commit()
    raise NotifyRetry(f"page {page_id}: {result.error_code}")
