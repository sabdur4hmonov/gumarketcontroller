"""What a Ha/Yo'q page's creator is told -- each message once, through the
shop's own bot.

WHICH MESSAGE (services/share_pages.claim_notification decides, from the page's
state, under a row lock):

* no date plan            -> "Ha!"                                     (once)
* plan, chosen in time    -> "Ha! Joy: Kino. Sana: 12-oktabr, 19:00."  (once)
* plan, nothing chosen    -> "Ha -- but no place or time chosen yet",
  CHOICE_WAIT after the Ha                                              (once)
* chosen after that       -> the choice, as a single follow-up          (once)

EXACTLY ONCE each, on the CP6 pattern: the claim is COMMITTED before Telegram
is called, so a retried task, a second worker or a second Ha cannot send it
twice. A send that fails for a reason worth retrying releases that claim and
raises NotifyRetry, and the task tries again. A send refused because the
creator blocked the bot keeps the claim: that is their decision, not an error.

THROUGH THE SHOP'S OWN BOT, resolved by the registry exactly as every other
send path does (C1/C2 of AUDIT_MULTI_TENANT.md).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Final
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from gulbot.bot.registry import BotFactory, build_bot_for, registry_for
from gulbot.i18n import t
from gulbot.sending.telegram import TelegramTransport
from gulbot.sending.transport import SendResult, ShopBotUnavailable
from gulbot.services.share_pages import NotifyTarget, claim_notification, release_notification
from gulbot.utils.render import escape
from gulbot.web import strings

log = logging.getLogger("gulbot.sending.page_notify")

OUTCOME_SENT: Final = "sent"
OUTCOME_NOTHING: Final = "nothing"
OUTCOME_BLOCKED: Final = "blocked"

_TEMPLATE: Final = {
    "yes": "pages.notify_yes",
    "yes_with_choice": "pages.notify_yes_plan",
    "yes_no_choice": "pages.notify_yes_unchosen",
    "choice_later": "pages.notify_choice_later",
}


class NotifyRetry(Exception):
    """The send failed for a reason worth another attempt; the claim is released."""


def when_text(moment: datetime, lang: str, tz_name: str) -> str:
    """The chosen time as the creator reads it: "12-oktabr, 19:00",
    "12 октября, 19:00", "12 October, 19:00" -- in the shop's timezone."""
    local = moment.astimezone(ZoneInfo(tz_name))
    clock = local.strftime("%H:%M")
    if lang == "ru":
        return f"{local.day} {strings.MONTHS['ru'][local.month - 1]}, {clock}"
    if lang == "en":
        return f"{local.day} {strings.MONTHS['en'][local.month - 1]}, {clock}"
    return f"{local.day}-{strings.MONTHS['uz'][local.month - 1].lower()}, {clock}"


def message_for(target: NotifyTarget) -> str:
    when = (
        when_text(target.slot_at, target.lang, target.shop_timezone)
        if target.slot_at is not None
        else ""
    )
    return t(
        _TEMPLATE[target.kind],
        target.lang,
        question=escape(target.question),
        place=escape(target.place or ""),
        when=when,
    )


async def notify_page_answer(
    page_id: int,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    bot_factory: BotFactory = build_bot_for,
    now: datetime | None = None,
) -> str:
    async with session_factory() as session:
        target = await claim_notification(session, page_id=page_id, now=now)
        await session.commit()
    if target is None:
        return OUTCOME_NOTHING

    body = message_for(target)
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
        log.info("page %s: creator told (%s)", page_id, target.kind)
        return OUTCOME_SENT
    if result.blocked:
        log.info("page %s: the creator has blocked the bot; not retrying", page_id)
        return OUTCOME_BLOCKED
    async with session_factory() as session:
        await release_notification(session, page_id=page_id, kind=target.kind)
        await session.commit()
    raise NotifyRetry(f"page {page_id}: {result.error_code}")
