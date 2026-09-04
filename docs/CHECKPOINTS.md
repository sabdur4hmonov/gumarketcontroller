# Checkpoint plan

Build order. Each checkpoint is one commit, revertable without unwinding a
later one, and leaves `make check` green.

**CP6 is the ship line.** Everything through CP6 is a complete, deliverable
product on its own: reminders work with no catalog and no ordering.

## Phase 1 — to the ship line and just past it

| CP | Scope | Status |
|----|-------|--------|
| CP0 | Repo, docker compose, test harness | done |
| CP1 | DB core: shops, customers, tenancy constraints, migration conventions | done |
| CP2 | Bot skeleton, i18n, router discipline, shadow sweep as a build gate | done |
| CP3 | Occasions: list, add (picker-driven), deactivate; versioned consent | done |
| CP4 | Occurrence engine — pure functions, no I/O | done |
| CP3.5 | Recipients, chained onboarding, minimal edit | done |
| CP3.6 | Preferences: flower preset, reminder count, send time | done |
| CP5 | `scheduled_notifications` + nightly materializer | done |
| CP6 | Beat tick + reminder send — **ship line** | done |
| CP7 | Catalog schema, hashtag normalisation, price parser | next |
| CP8 | Channel indexer (albums, edits) | |
| CP9 | Search and presentation (copyMessage, overridden caption) | |
| CP10 | Ordering end-to-end: order FSM, submit, shop group card | |

CP10 replaces the old CP10–CP13 block. The order FSM, the single-flight submit
guard and the one-message-per-order shop card are one deliverable; splitting
them produced a checkpoint that could not be demonstrated on its own.

## Phase 2 — deferred

Not scheduled. Each needs production behaviour to design against, or is polish
that does not gate the ship line.

| Was | Scope | Why deferred |
|-----|-------|--------------|
| CP11 | Customer status updates beyond placed/confirmed | Wants real order flow observed first |
| CP12 | Escalation (T+10 / T+25 / T+40, working-hours aware) | **Blocked**: needs two weeks of CP10 running in production. Timings set from observed behaviour, never guessed |
| CP13 | Peak mode: pinned live summary, suppressed re-pings | Threshold must come from observed load |
| CP14 | Nightly deletion sweep, admin self-probe, monitoring alerts | Only matters once the catalog is live |
| CP15 | Full ru locale, ops hardening, backup/restore runbook | Polish; uz ships first |

## Briefs already agreed for future checkpoints

**CP9** attaches bouquet suggestions to the reminder by widening
`sending/render.py` and `sending/transport.py`. It should not need to touch
`sending/dispatcher.py` at all: dispatch depends only on a `Renderer` callable
and a `Transport` protocol. `tests/test_sending_scope.py` fails the build if the
send path references products, catalogue, hashtags or `copyMessage` before then.

It should use `recipients.preferred_hashtag` as a ranking hint; CP3.6 stores a
normalised preset value and nothing matches it against the real catalogue yet.

CP9 must NOT change `transition_key_for`. Those keys are already written into
`message_log`, and changing their shape would make historical claims
unmatchable — so a reminder already sent could be sent a second time.

## Deliberately not built

**A dead-letter review surface.** Rows that exhaust `MAX_SEND_ATTEMPTS` (5) park
in `state='dead_letter'` and are queryable, but nothing surfaces them to an
operator yet. Deferred with CP14's monitoring work.

**Shop settings admin flow.** `shops.default_send_time` and
`shops.reminder_offsets` are settable only via the seed or psql — there is no
owner-facing UI. A small deferred follow-up, not a blocker: the values have
sensible defaults and no shop has asked to change them yet.

The occasion edit flow, deferred at CP3, was reinstated in CP3.5: once recipient
chaining exists the sub-flow is reused rather than duplicated, so it costs two
states instead of six.

## Open decisions

None currently.

### Resolved

**The reminder window opens at 09:00, not 10:00.** CP3.6's "Ertalab (09:00)"
preset was being clamped to 10:00 by CP4's window. The button label is a promise
to the customer, so the bound moved rather than the label. Both outermost
presets now sit exactly ON a bound -- 09:00 and 20:00 -- and both are inclusive.
Verified that this is a presentation change only: merge and cap decisions are
identical across 09:00 / 10:00 / 13:00 / 20:00, pinned by
`test_merge_and_cap_do_not_depend_on_the_send_time`.

## Decisions that constrain later checkpoints

- Reminder offsets default to `[-7, -1, 0]`, per shop, and become per customer
  in CP3.6 (1 → `[0]`, 2 → `[-1, 0]`, 3 → `[-7, -1, 0]`).
- `occurrence_year` is the year of the OCCASION, never the year of the send.
  The uniqueness of `scheduled_notifications` rests on this.
- Window clamp happens at materialisation. The send-time check is a backstop
  assertion only. The window is 09:00-20:00 local, inclusive at both ends, and
  governs outbound reminders ONLY -- never delivery slots.
- Staleness has two independent conditions: 6h past due, OR the occurrence date
  has already passed. Either expires the row.
- A merged reminder is anchored on the cluster's earliest date, and the weekly
  cap drops the least urgent message first — a day-of reminder is never dropped
  while a `-7` survives.
- Escalation defers to opening time rather than pausing a clock.
- `same_day_cutoff` and a minimum lead time must BOTH pass. Shop working hours
  are authoritative for which delivery slots are offered; the 10:00-20:00
  notification window governs outbound reminders only and never filters slots.
- The daily order cap is enforced at date selection, so a full date is simply
  absent from the picker. An order that fills a date mid-flow is accepted and
  flagged `over_cap` for the shop.
- A customer who declines the contact-share button may type their number;
  `phone_verified=false` marks it on the shop's card. It never blocks an order.
- Peak mode trips at 15 unacknowledged pending orders or 40 in a rolling hour,
  plus a manual owner toggle.
- CP10 stays within `post` + `callback_query` only. The bot's privacy mode is
  on, so it cannot read plain group text. If a group feature ever needs that,
  it is a decision to surface, not a setting to quietly toggle.
- Two recipients may share a label. "Do'stim" is not a unique name, so nothing
  in the schema treats it as one.
- The send tick runs in two phases with a COMMIT between them. Claims must be
  durable before the Telegram call: claiming inside the send transaction rolls
  the claim back with everything else when a worker dies, and the retry then
  sends a second time. SKIP LOCKED and the claim solve different halves —
  concurrent workers, and a later worker redoing a dead worker's batch.
- A `claimed` ledger row is re-claimable after 15 minutes. That accepts a rare
  duplicate for a genuinely dead worker rather than losing a reminder forever.
- Telegram's `retry_after` is honoured exactly, by deferring `due_at_utc` by
  precisely that many seconds. Never a guessed backoff, and never "whenever the
  next tick runs", which could be sooner than Telegram allowed.
- A 403 marks the customer `blocked`, which stops the materializer generating
  further rows for them. It is recorded as `cancelled`, not `failed`: a block is
  the customer's decision, not an error to retry.
