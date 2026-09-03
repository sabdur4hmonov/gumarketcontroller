# Checkpoint plan

Build order. Each checkpoint is one commit, revertable without unwinding a
later one, and leaves `make check` green.

**CP6 is the ship line.** Everything through CP6 is a complete, deliverable
product on its own: reminders work with no catalog and no ordering.

**CP12 does not start** until a real shop has been running on CP11 for at least
two weeks. Escalation timings and the peak threshold are set from observed
behaviour, not guessed.

| CP | Scope | Status |
|----|-------|--------|
| CP0 | Repo, docker compose, test harness | done |
| CP1 | DB core: shops, customers, tenancy constraints, migration conventions | done |
| CP2 | Bot skeleton, i18n, router discipline, shadow sweep as a build gate | done |
| CP3 | Occasions: list, add (picker-driven), deactivate; versioned consent | done |
| CP4 | Occurrence engine — pure functions, no I/O | in progress |
| CP5 | `scheduled_notifications` + nightly materializer | |
| CP6 | Beat tick + reminder send — **ship line** | |
| CP7 | Catalog schema, hashtag normalisation, price parser | |
| CP8 | Channel indexer (albums, edits) | |
| CP9 | Search and presentation (copyMessage, overridden caption) | |
| CP10 | Order FSM | |
| CP11 | Submit, shop group card, customer status updates | |
| CP12 | Escalation — **blocked on two weeks of CP11 in production** | |
| CP13 | Peak mode | |
| CP14 | Sweeps, health checks, monitoring | |
| CP15 | ru locale, hardening, ops | |

## Deliberately not built

**Editing an occasion.** Deactivate-and-re-add is four taps. A real edit flow
costs six new FSM states plus the sweep surface that comes with them, for no
user-visible gain. Decided at CP3.

## Decisions that constrain later checkpoints

- Reminder offsets default to `[-7, -1, 0]`, per shop. `-3` was dropped: it adds
  a message without adding a decision point.
- `occurrence_year` is the year of the OCCASION, never the year of the send.
  The uniqueness of `scheduled_notifications` rests on this.
- Window clamp happens at materialisation. The send-time check is a backstop
  assertion only.
- Staleness has two independent conditions: 6h past due, OR the occurrence date
  has already passed. Either expires the row.
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
- CP11 stays within `post` + `callback_query` only. The bot's privacy mode is
  on, so it cannot read plain group text. If a group feature ever needs that,
  it is a decision to surface, not a setting to quietly toggle.
