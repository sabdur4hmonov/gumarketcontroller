"""The beat tick: pick up due reminders and send them.

Once per minute. Selects due rows FOR UPDATE SKIP LOCKED so two workers never
fight over the same row -- the loser simply skips it and takes the next.

ONE MESSAGE PER merge_key. A cluster of occasions within two days of each other
is one message listing all of them, not one per row. Every row in a group is
marked sent in a SINGLE UPDATE inside the same transaction as the ledger
resolve, so "2 of 3 rows marked sent" is not a state the database can hold. It
is not unlikely; there is no instant at which it exists.

The tick runs in TWO PHASES, and the split is the whole idempotency design:

    Phase 1 (one transaction, then COMMIT)
        select due rows FOR UPDATE SKIP LOCKED
        expire the stale, dead-letter the exhausted
        claim each remaining group in message_log
        COMMIT  <- the claims are now durable

    Phase 2 (no locks held; one transaction per group)
        send
        resolve the ledger and mark every row of the group, then COMMIT

The commit between the phases is not incidental. Claiming inside the same
transaction as the send would roll the claim back with everything else when a
worker dies -- and the retry would find pending rows, no claim, and send the
message a second time. The claim has to survive the crash to be worth anything.

SKIP LOCKED gives two workers disjoint batches at the same instant; the durable
claim is what stops a LATER worker redoing a batch whose sender died. They solve
different halves of the problem.

See models/message_log.py for the claim/timeout contract.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import and_, delete, func, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from gulbot.models.customer import Customer, CustomerStatus
from gulbot.models.message_log import (
    CLAIM_TIMEOUT,
    TEMPLATE_REMINDER,
    MessageLog,
    MessageStatus,
)
from gulbot.models.notification import (
    SENDABLE_STATES,
    NotificationState,
    ScheduledNotification,
)
from gulbot.models.occasion import Occasion
from gulbot.models.recipient import Recipient
from gulbot.scheduling.occurrences import DEFAULT_GRACE, TASHKENT
from gulbot.sending.rate_limit import RateLimiter
from gulbot.sending.transport import (
    BREAKER_THRESHOLD,
    FLEET_BREAKER_SHOPS,
    Attachment,
    SendResult,
    ShopBotUnavailable,
    ShopBreakers,
    Transport,
    TransportFor,
    per_shop,
)

log = logging.getLogger("gulbot.sending")

#: error_code for a group whose shop has no usable bot. See ShopBotUnavailable.
NO_BOT_TOKEN = "no_bot_token"

#: Turns a due group into message text. Injected so the dispatcher never
#: needs to know how a reminder is worded.
Renderer = Callable[["DueGroup"], str]

#: CP9. Optionally turns a due group into a ready-made photo message. Returning
#: None means "send bare text", which is CP6 unchanged and is what happens for
#: an empty catalogue, a customer with no match, or a reminder too long to be a
#: caption.
#:
#: It hands back an `Attachment` -- a file id and a caption -- rather than a
#: product, so dispatch still does not know the catalogue exists. Composing one
#: is `sending/attach.py`'s job.
#:
#: DELIBERATELY OPTIONAL. Every CP6 dispatcher test constructs `run_tick`
#: without it and passes unmodified, which is the evidence that claiming,
#: retrying, 403, 429 and dead-lettering were not disturbed by CP9.
Attacher = Callable[["DueGroup"], Awaitable["Attachment | None"]]

#: Rows examined per tick. One minute is plenty for this many sends at ~28/s
#: -- one bot's ceiling, so the worst case, a batch all from one shop -- and it
#: bounds how long a tick holds its locks.
BATCH_SIZE = 100

#: A row that has been claimed this many times without succeeding is parked.
#: Five spreads retries over five minutes of ticks, which outlasts a transient
#: Telegram outage without pestering a customer indefinitely.
#:
#: Until the pre-deployment audit this only ever applied to 429s: every other
#: failure marked the row FAILED, and FAILED rows were not selected, so nothing
#: bumped attempts and nothing ever reached the dead letter.
MAX_SEND_ATTEMPTS = 5

#: How long a generically-failed send waits before the next attempt. One minute
#: per attempt is what makes MAX_SEND_ATTEMPTS mean the five minutes its comment
#: claims. Fixed rather than exponential on purpose: a reminder is time-sensitive
#: -- half an hour late is fine, five hours late is a different message -- so the
#: ladder is short and then a human is told.
RETRY_BACKOFF = timedelta(seconds=60)


@dataclass
class TickResult:
    groups: int = 0
    sent: int = 0
    skipped_claimed: int = 0
    expired: int = 0
    failed: int = 0
    cancelled: int = 0
    dead_lettered: int = 0
    rate_limited: int = 0
    #: Claimed, never attempted, returned untouched because the breaker opened.
    handed_back: int = 0
    waited_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DueGroup:
    """One outbound message and every row it covers."""

    key: str
    customer_id: int
    shop_id: int
    telegram_user_id: int
    lang: str
    rows: tuple[ScheduledNotification, ...]
    occasions: tuple[Occasion, ...]
    recipients: tuple[Recipient, ...]

    @property
    def transition_key(self) -> str:
        return self.key

    @property
    def is_merged(self) -> bool:
        return len(self.rows) > 1


def transition_key_for(row: ScheduledNotification) -> str:
    """Ledger key for a row.

    Merged rows share their merge_key, so the whole group claims once. A lone
    row keys on its own identity. Either way the key identifies the MESSAGE,
    which is what must not be sent twice.
    """
    if row.merge_key:
        return row.merge_key
    return f"occ:{row.occasion_id}:{row.occurrence_year}:{row.offset_days:+d}"


async def select_due_rows(
    session: AsyncSession, *, now_utc: datetime, limit: int = BATCH_SIZE
) -> Sequence[ScheduledNotification]:
    """Lock a batch of due rows, skipping any another worker already holds --
    and never HALF a merge group.

    SKIP LOCKED is what makes two workers cooperative rather than competitive:
    the second one does not block and does not fail, it just works on different
    rows.

    THE UNIT OF LOCKING IS THE GROUP, NOT THE ROW. Row-at-a-time SKIP LOCKED
    let two workers split one merge group: A locked row 1, B skipped it and took
    rows 2 and 3, each built a "group" from what it held, one of them won the
    ledger claim and sent a reminder covering part of the dates, and the rest
    stayed pending behind a key that was already claimed. The batch LIMIT cut
    groups the same way with one worker. Found by the CP16 F4 gate; reproduced
    on purpose by tests/test_merge_group_claim.py.

    So a worker SKIP-LOCKs only each group's ANCHOR -- its lowest-id due row; a
    row with no merge_key is its own anchor -- and then locks the rest of the
    group, waiting for it if it must. Workers never lock a non-anchor row any
    other way, so whoever holds the anchor is the only one that can be asking
    for the members: there is no second worker to split with, and nothing a
    worker waits on here can be waiting on it. A worker that does not get the
    anchor takes none of the group. The LIMIT counts anchors, so it cannot cut
    a group either.
    """
    sendable = and_(
        ScheduledNotification.state.in_(SENDABLE_STATES),
        ScheduledNotification.due_at_utc <= now_utc,
    )
    peer = aliased(ScheduledNotification)
    group_anchor = (
        select(func.min(peer.id))
        .where(
            peer.customer_id == ScheduledNotification.customer_id,
            peer.merge_key == ScheduledNotification.merge_key,
            peer.state.in_(SENDABLE_STATES),
            peer.due_at_utc <= now_utc,
        )
        .scalar_subquery()
    )
    anchors = list(
        await session.scalars(
            select(ScheduledNotification)
            .where(
                sendable,
                or_(
                    ScheduledNotification.merge_key.is_(None),
                    ScheduledNotification.id == group_anchor,
                ),
            )
            .order_by(ScheduledNotification.due_at_utc, ScheduledNotification.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    groups = {(a.customer_id, a.merge_key) for a in anchors if a.merge_key is not None}
    if not groups:
        return anchors
    members = await session.scalars(
        select(ScheduledNotification)
        .where(
            sendable,
            tuple_(ScheduledNotification.customer_id, ScheduledNotification.merge_key).in_(
                list(groups)
            ),
            ScheduledNotification.id.not_in([a.id for a in anchors]),
        )
        .order_by(ScheduledNotification.id)
        # NOT skip_locked: a member held elsewhere is waited for, never left out.
        .with_for_update()
    )
    return anchors + list(members)


async def _load_group_context(
    session: AsyncSession, rows: Sequence[ScheduledNotification]
) -> tuple[dict[int, Occasion], dict[int, Recipient], dict[int, Customer]]:
    occasion_ids = {row.occasion_id for row in rows}
    customer_ids = {row.customer_id for row in rows}
    occasions = {
        o.id: o
        for o in await session.scalars(select(Occasion).where(Occasion.id.in_(occasion_ids)))
    }
    recipient_ids = {o.recipient_id for o in occasions.values()}
    recipients = {
        r.id: r
        for r in await session.scalars(select(Recipient).where(Recipient.id.in_(recipient_ids)))
    }
    customers = {
        c.id: c
        for c in await session.scalars(select(Customer).where(Customer.id.in_(customer_ids)))
    }
    return occasions, recipients, customers


def group_due_rows(
    rows: Sequence[ScheduledNotification],
    occasions: dict[int, Occasion],
    recipients: dict[int, Recipient],
    customers: dict[int, Customer],
) -> list[DueGroup]:
    """Collapse rows into one entry per outbound message."""
    buckets: dict[tuple[int, str], list[ScheduledNotification]] = {}
    for row in rows:
        buckets.setdefault((row.customer_id, transition_key_for(row)), []).append(row)

    groups = []
    for (customer_id, key), bucket in buckets.items():
        customer = customers.get(customer_id)
        if customer is None:  # pragma: no cover - FK makes this unreachable
            continue
        bucket_occasions = tuple(
            occasions[row.occasion_id] for row in bucket if row.occasion_id in occasions
        )
        groups.append(
            DueGroup(
                key=key,
                customer_id=customer_id,
                shop_id=customer.shop_id,
                telegram_user_id=customer.telegram_user_id,
                lang=customer.lang,
                rows=tuple(bucket),
                occasions=bucket_occasions,
                recipients=tuple(
                    recipients[o.recipient_id]
                    for o in bucket_occasions
                    if o.recipient_id in recipients
                ),
            )
        )
    groups.sort(key=lambda g: (min(r.due_at_utc for r in g.rows), g.key))
    return groups


def is_stale(
    row: ScheduledNotification, *, now_utc: datetime, grace: timedelta = DEFAULT_GRACE
) -> bool:
    """DEFENSIVE BACKSTOP ONLY. Staleness logic lives in CP4's engine.

    CP5 clamps due times at materialisation, so a stale row reaching here should
    be rare -- it means a worker outage, a clock jump, or a paused queue. This
    check exists so that such a row is dropped rather than sent late; it is NOT
    where the rules are defined, and it must not grow into a second copy of them.
    """
    if now_utc > row.due_at_utc + grace:
        return True
    occurrence = row.due_at_utc.astimezone(TASHKENT).date() - timedelta(days=row.offset_days)
    return now_utc.astimezone(TASHKENT).date() > occurrence


async def claim_send(
    session: AsyncSession,
    *,
    shop_id: int,
    customer_id: int,
    template_key: str,
    transition_key: str,
    now_utc: datetime,
    channel: str,
) -> bool:
    """Take ownership of ONE send. False means someone else already has it.

    Called BEFORE Telegram. An abandoned claim -- a worker that died mid-call --
    becomes re-claimable after CLAIM_TIMEOUT; until then this returns False and
    the send is skipped, which is what makes a retry safe.

    Keyed on an explicit (customer, template, transition) rather than on a
    `DueGroup`, so CP13's order-outcome message can use the same ledger and the
    same re-claim window instead of growing a second copy of them. CP6 reaches
    it through `claim` below, unchanged.
    """
    stmt = (
        insert(MessageLog)
        .values(
            shop_id=shop_id,
            customer_id=customer_id,
            channel=channel,
            template_key=template_key,
            transition_key=transition_key,
            status=MessageStatus.CLAIMED.value,
            claimed_at=now_utc,
            attempts=1,
        )
        .on_conflict_do_nothing(index_elements=["customer_id", "template_key", "transition_key"])
        .returning(MessageLog.id)
    )
    if await session.scalar(stmt) is not None:
        return True

    # Already present. Re-claimable only if abandoned: still 'claimed' and
    # older than the timeout.
    retake = (
        update(MessageLog)
        .where(
            MessageLog.customer_id == customer_id,
            MessageLog.template_key == template_key,
            MessageLog.transition_key == transition_key,
            MessageLog.status == MessageStatus.CLAIMED.value,
            MessageLog.claimed_at < now_utc - CLAIM_TIMEOUT,
        )
        .values(claimed_at=now_utc, attempts=MessageLog.attempts + 1)
        .returning(MessageLog.id)
    )
    return await session.scalar(retake) is not None


async def resolve_send(
    session: AsyncSession,
    *,
    customer_id: int,
    template_key: str,
    transition_key: str,
    status: MessageStatus,
    now_utc: datetime,
    error_code: str | None = None,
) -> None:
    await session.execute(
        update(MessageLog)
        .where(
            MessageLog.customer_id == customer_id,
            MessageLog.template_key == template_key,
            MessageLog.transition_key == transition_key,
        )
        .values(status=status.value, error_code=error_code, resolved_at=now_utc)
    )


async def claim(session: AsyncSession, group: DueGroup, *, now_utc: datetime, channel: str) -> bool:
    """CP6's reminder claim. The ledger key is the group's transition key."""
    return await claim_send(
        session,
        shop_id=group.shop_id,
        customer_id=group.customer_id,
        template_key=TEMPLATE_REMINDER,
        transition_key=group.transition_key,
        now_utc=now_utc,
        channel=channel,
    )


async def resolve_claim(
    session: AsyncSession,
    group: DueGroup,
    *,
    status: MessageStatus,
    now_utc: datetime,
    error_code: str | None = None,
) -> None:
    await resolve_send(
        session,
        customer_id=group.customer_id,
        template_key=TEMPLATE_REMINDER,
        transition_key=group.transition_key,
        status=status,
        now_utc=now_utc,
        error_code=error_code,
    )


async def mark_group(
    session: AsyncSession,
    group: DueGroup,
    *,
    state: NotificationState,
    now_utc: datetime,
    sent: bool = False,
) -> None:
    """Mark EVERY row in the group, in one statement.

    A single UPDATE over the whole group is what makes a partial send
    structurally impossible: there is no point between "row 1 marked" and
    "row 2 marked" for a crash to land in.
    """
    values: dict[str, object] = {"state": state.value}
    if sent:
        values["sent_at"] = now_utc
    await session.execute(
        update(ScheduledNotification)
        .where(ScheduledNotification.id.in_([row.id for row in group.rows]))
        .values(**values)
    )


async def bump_attempts(session: AsyncSession, group: DueGroup) -> int:
    """Increment attempts on every row; return the highest resulting value."""
    result = await session.scalars(
        update(ScheduledNotification)
        .where(ScheduledNotification.id.in_([row.id for row in group.rows]))
        .values(attempts=ScheduledNotification.attempts + 1)
        .returning(ScheduledNotification.attempts)
    )
    return max(result, default=0)


async def block_customer(session: AsyncSession, group: DueGroup) -> None:
    """403: the customer blocked the bot.

    Marks them blocked so the materializer stops producing rows for them, and
    cancels what is already queued. Not a failure and never retried -- retrying
    a block is how a bot gets reported.
    """
    await session.execute(
        update(Customer)
        .where(Customer.id == group.customer_id)
        .values(status=CustomerStatus.BLOCKED.value)
    )
    await session.execute(
        update(ScheduledNotification)
        .where(
            ScheduledNotification.customer_id == group.customer_id,
            # EVERY sendable state, not just PENDING. Since FAILED became
            # sendable, a PENDING-only filter left a failed reminder alive for
            # a customer who had blocked the bot: its claim was resolved and
            # could not be retaken, so it burned attempts into dead_letter and
            # told the shop that sending had FAILED. Found in the audit.
            ScheduledNotification.state.in_(SENDABLE_STATES),
        )
        .values(state=NotificationState.CANCELLED.value)
    )


async def run_tick(
    session: AsyncSession,
    *,
    render: Renderer,
    now_utc: datetime,
    transport: Transport | None = None,
    transport_for: TransportFor | None = None,
    limit: int = BATCH_SIZE,
    channel: str = "telegram",
    limiter: RateLimiter | None = None,
    attach: Attacher | None = None,
) -> TickResult:
    """One beat. Returns what it did, for logging and for tests.

    The batch spans every shop, so each group is sent through the transport of
    ITS shop -- `transport_for(group.shop_id)` -- never one shared bot (C1 of
    AUDIT_MULTI_TENANT.md). See `per_shop` for the two ways in. Checked before
    anything is claimed, so a bad call locks no rows.
    """
    transport_for = per_shop(transport, transport_for)
    result = TickResult()

    # --- phase 1: decide and claim, then commit --------------------------
    rows = await select_due_rows(session, now_utc=now_utc, limit=limit)
    if not rows:
        return result

    occasions, recipients, customers = await _load_group_context(session, rows)
    groups = group_due_rows(rows, occasions, recipients, customers)
    result.groups = len(groups)

    claimed: list[DueGroup] = []
    for group in groups:
        if all(is_stale(row, now_utc=now_utc) for row in group.rows):
            await mark_group(session, group, state=NotificationState.EXPIRED, now_utc=now_utc)
            result.expired += 1
            continue

        attempts = await bump_attempts(session, group)
        if attempts > MAX_SEND_ATTEMPTS:
            await mark_group(session, group, state=NotificationState.DEAD_LETTER, now_utc=now_utc)
            await resolve_claim(
                session,
                group,
                status=MessageStatus.FAILED,
                now_utc=now_utc,
                error_code="max_attempts",
            )
            result.dead_lettered += 1
            continue

        if await claim(session, group, now_utc=now_utc, channel=channel):
            claimed.append(group)
        else:
            result.skipped_claimed += 1

    # The claims must outlive this worker. Everything after this point may
    # crash without causing a duplicate send.
    await session.commit()

    # --- phase 2: send, one transaction per group ------------------------
    blocked: set[int] = set()
    breakers = ShopBreakers()
    for group in claimed:
        if breakers.open_for(group.shop_id):
            # This shop's bot -- or, on a fleet trip, Telegram -- has stopped
            # answering. Every further send would wait out the full timeout and
            # fail the same way, so its rows go back exactly as they were and
            # the next tick tries again. Every other shop keeps sending (H5).
            await _hand_back(session, group)
            result.handed_back += 1
            await session.commit()
            continue

        if group.customer_id in blocked:
            # A 403 earlier in this same batch. Their rows are already
            # cancelled; sending again would just earn another 403.
            await mark_group(session, group, state=NotificationState.CANCELLED, now_utc=now_utc)
            await resolve_claim(
                session,
                group,
                status=MessageStatus.CANCELLED,
                now_utc=now_utc,
                error_code="bot_blocked",
            )
            await session.commit()
            continue

        # The customer's own shop's bot. It is also the only bot that can use
        # the attachment's file id: Telegram file ids are per bot.
        try:
            shop_transport = transport_for(group.shop_id)
        except ShopBotUnavailable as missing:
            # One shop's setup problem, not the tick's: fail THIS group through
            # the ordinary retry ladder (so it parks after MAX_SEND_ATTEMPTS
            # and the health check counts it) and carry on with every other
            # shop. Not recorded to the breaker -- a missing bot says nothing
            # about whether Telegram is answering.
            log.error("reminder for customer %s NOT SENT: %s", group.customer_id, missing)
            await _apply_outcome(
                session, group, SendResult.failed(NO_BOT_TOKEN), now_utc=now_utc, result=result
            )
            await session.commit()
            continue

        if limiter is not None:
            # Paced as THIS shop's bot: Telegram's limits are per bot (H4).
            result.waited_seconds += await limiter.acquire(
                group.telegram_user_id, shop_id=group.shop_id
            )

        # ONE call either way. A bouquet rides along as the photo's caption
        # rather than as a second message, so the group is still atomic.
        attachment = await attach(group) if attach is not None else None
        if attachment is None:
            outcome = await shop_transport.send_text(
                chat_id=group.telegram_user_id, text=render(group)
            )
        else:
            outcome = await shop_transport.send_photo(
                chat_id=group.telegram_user_id,
                file_id=attachment.file_id,
                caption=attachment.caption,
                reply_markup=attachment.reply_markup,
            )
        await _apply_outcome(session, group, outcome, now_utc=now_utc, result=result)
        if outcome.blocked:
            blocked.add(group.customer_id)
        await session.commit()
        _log_trip(breakers.record(group.shop_id, outcome), group.shop_id, what="tick")

    return result


def _log_trip(tripped: str | None, shop_id: int, *, what: str) -> None:
    """One line per trip, at the send that caused it. Shared with order pings."""
    if tripped == "shop":
        log.warning(
            "%s: shop %s's bot got no answer %d times running; handing that shop's "
            "rows back to the next tick, every other shop keeps sending",
            what,
            shop_id,
            BREAKER_THRESHOLD,
        )
    elif tripped == "fleet":
        log.warning(
            "%s: %d different shops got no answer in a row; Telegram looks unreachable, "
            "handing the rest of the batch back to the next tick",
            what,
            FLEET_BREAKER_SHOPS,
        )


async def _hand_back(session: AsyncSession, group: DueGroup) -> None:
    """Undo phase 1 for a group that was claimed and never sent.

    Both things phase 1 did, reversed: the attempt it counted and the claim it
    took. The due time is NOT touched -- nothing was tried, so there is nothing
    to back off from, and the next tick picks it up at once. An outage must not
    burn a reminder's attempts on sends that never happened, or a long outage
    would dead-letter rows that were never once put on the wire.

    Deleting the claim is safe for the same reason it is in `_defer_and_release`:
    `claim_send` only succeeds on a fresh row or an abandoned CLAIMED one, so the
    row being deleted is the one this tick took, never a resolved record.
    """
    await session.execute(
        update(ScheduledNotification)
        .where(ScheduledNotification.id.in_([row.id for row in group.rows]))
        .values(attempts=ScheduledNotification.attempts - 1)
    )
    await session.execute(
        delete(MessageLog).where(
            MessageLog.customer_id == group.customer_id,
            MessageLog.template_key == TEMPLATE_REMINDER,
            MessageLog.transition_key == group.transition_key,
        )
    )


async def _defer_and_release(session: AsyncSession, group: DueGroup, *, until: datetime) -> None:
    """Push the retry out and let go of the claim.

    BOTH HALVES OR NEITHER. Deferring without releasing leaves a row that is
    selected on every tick and skipped every time, because `claim_send` cannot
    retake a resolved claim -- five attempts of nothing, which is what the
    generic-failure path used to do. Releasing without deferring would retry
    instantly and burn the ladder in one tick.
    """
    await session.execute(
        update(ScheduledNotification)
        .where(ScheduledNotification.id.in_([row.id for row in group.rows]))
        .values(due_at_utc=until)
    )
    await session.execute(
        delete(MessageLog).where(
            MessageLog.customer_id == group.customer_id,
            MessageLog.template_key == TEMPLATE_REMINDER,
            MessageLog.transition_key == group.transition_key,
        )
    )


async def _apply_outcome(
    session: AsyncSession,
    group: DueGroup,
    outcome: SendResult,
    *,
    now_utc: datetime,
    result: TickResult,
) -> None:
    if outcome.ok:
        await mark_group(session, group, state=NotificationState.SENT, now_utc=now_utc, sent=True)
        await resolve_claim(session, group, status=MessageStatus.SENT, now_utc=now_utc)
        result.sent += 1
        return

    if outcome.blocked:
        await block_customer(session, group)
        await resolve_claim(
            session,
            group,
            status=MessageStatus.CANCELLED,
            now_utc=now_utc,
            error_code=outcome.error_code,
        )
        result.cancelled += 1
        return

    if outcome.retry_after is not None:
        # Telegram stated the wait. Honour it EXACTLY by pushing the rows out by
        # precisely that many seconds -- not by a guessed backoff, and not by
        # "whenever the next tick happens to run", which could be sooner.
        #
        # Deferring in the database rather than sleeping keeps the tick free to
        # serve every other customer, and survives a worker restart.
        await _defer_and_release(
            session, group, until=now_utc + timedelta(seconds=outcome.retry_after)
        )
        result.rate_limited += 1
        result.errors.append(f"429 retry_after={outcome.retry_after}")
        return

    # EVERY OTHER FAILURE: a dropped connection, a 500, a timeout. Telegram has
    # not told us it declined, so we do not know whether the message landed.
    #
    # The row stays SENDABLE and is deferred, and the claim is RELEASED so the
    # next tick can genuinely re-send rather than skipping a claim it cannot
    # retake. That accepts a duplicate reminder in the case where a timeout hid
    # a delivery that actually happened -- the deliberate trade, because a
    # duplicate is mildly annoying and a silent miss is the product failing.
    #
    # `mark_group(FAILED)` still records WHAT happened; it no longer means the
    # row is finished, because FAILED is in `SENDABLE_STATES`.
    await mark_group(session, group, state=NotificationState.FAILED, now_utc=now_utc)
    await _defer_and_release(session, group, until=now_utc + RETRY_BACKOFF)
    result.failed += 1
    result.errors.append(outcome.error_code or "unknown")
