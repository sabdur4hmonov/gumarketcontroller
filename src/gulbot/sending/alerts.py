"""Composing and sending the two health messages to the shop's group.

Split from `health.py` on the same seam as everywhere else in the send path:
that module counts, this one words and delivers. The counting is testable with
no Telegram in sight, and the wording is testable with no database.

WHERE THEY GO: exactly where order cards go -- `ping_targets` decides, so the
group/owners/nowhere fallback is the one already built and tested rather than a
second copy that could disagree with it.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.i18n import t
from gulbot.sending.health import (
    STALL_AFTER,
    DailyTotals,
    Health,
    alert_cooldown,
    read_daily_totals,
    read_health,
)
from gulbot.sending.order_pings import ping_targets
from gulbot.sending.transport import Transport

log = logging.getLogger("gulbot.health")

#: Cooldown keys. Two kinds, because they mean different things and a shop that
#: has already parked something still wants to know when sending stops.
KIND_STALLED = "stalled"
KIND_PARKED = "parked"


def render_summary(totals: DailyTotals, lang: str = "uz") -> str:
    """The daily line. Boring on purpose -- its absence is the signal."""
    body = t(
        "health.summary",
        lang,
        reminders=totals.reminders_sent,
        orders=totals.orders_placed,
    )
    parked = totals.parked_reminders + totals.parked_pings
    if parked:
        body += t("health.summary.parked", lang, count=parked)
    return body


def render_stalled(health: Health, lang: str = "uz") -> str:
    """The alarm. Names what is stuck and for how long, because "something is
    wrong" is not something a shop can act on."""
    return t(
        "health.stalled",
        lang,
        count=health.overdue_reminders + health.overdue_pings,
        minutes=int(STALL_AFTER.total_seconds() // 60),
    )


def render_parked(health: Health, lang: str = "uz") -> str:
    return t("health.parked", lang, count=health.parked_reminders + health.parked_pings)


async def _announce(
    session: AsyncSession, transport: Transport, *, shop_id: int, body: str
) -> bool:
    """Send one line to wherever this shop's admin messages go."""
    targets = await ping_targets(session, shop_id=shop_id)
    if not targets:
        log.error(
            "shop %s has nowhere to receive health messages: set shops.group_chat_id "
            "or shops.owner_telegram_ids",
            shop_id,
        )
        return False
    delivered = False
    for chat_id in targets:
        outcome = await transport.send_text(chat_id=chat_id, text=body)
        delivered = delivered or outcome.ok
    return delivered


async def send_daily_summary(
    session: AsyncSession,
    *,
    transport: Transport,
    shop_id: int,
    now_utc: datetime,
    lang: str = "uz",
) -> bool:
    """Once a day. No cooldown: it is meant to arrive every single day, and a
    missing one is the whole point."""
    totals = await read_daily_totals(session, shop_id=shop_id, now_utc=now_utc)
    sent = await _announce(session, transport, shop_id=shop_id, body=render_summary(totals, lang))
    log.info(
        "daily summary shop=%s reminders=%s orders=%s parked=%s delivered=%s",
        shop_id,
        totals.reminders_sent,
        totals.orders_placed,
        totals.parked_reminders + totals.parked_pings,
        sent,
    )
    return sent


async def check_and_alert(
    session: AsyncSession,
    *,
    transport: Transport,
    shop_id: int,
    now_utc: datetime,
    lang: str = "uz",
) -> list[str]:
    """Look for trouble, and say so at most once per cooldown window.

    Returns the kinds actually announced, which is what the task logs and the
    tests assert on. An empty list is the ordinary answer.
    """
    health = await read_health(session, shop_id=shop_id, now_utc=now_utc)
    if not health.stalled and not health.parked:
        return []

    announced: list[str] = []
    async with alert_cooldown() as cooldown:
        for kind, condition, body in (
            (KIND_STALLED, health.stalled, render_stalled(health, lang)),
            (KIND_PARKED, health.parked, render_parked(health, lang)),
        ):
            if not condition:
                continue
            # Claimed BEFORE sending. A send that fails still burns the window,
            # which is deliberate: the alternative is a shop whose Telegram is
            # unreachable getting one alert attempt per tick forever.
            if not await cooldown.claim(shop_id=shop_id, kind=kind):
                log.info("health alert %s for shop %s is within its cooldown", kind, shop_id)
                continue
            await _announce(session, transport, shop_id=shop_id, body=body)
            announced.append(kind)
            log.warning("health alert %s announced for shop %s", kind, shop_id)
    return announced
