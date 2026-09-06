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
| CP7 | Catalog schema, hashtag normalisation, price parser | done |
| CP8 | Channel indexer (albums, edits) | done |
| CP9 | Search and presentation: a bouquet on every reminder | done |
| CP9.5 | Ranking fix: resolve the STORED tag, not the preset | done |
| CP10a | Ordering: schema, order FSM, submit, snapshot, single-flight | done |
| CP10b | Group notification + admin ping tick | code done; **live proof blocked**: the group's chat_id is still unknown |

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

## What CP6 guarantees

The sending contract, so later checkpoints do not have to re-derive it. **A
reminder is claimed durably before it is sent, and delivered exactly once per
`merge_key` group.** The claim is written to `message_log` and COMMITTED before
any Telegram call, so a worker that dies mid-send cannot cause a duplicate; a
claim left unresolved becomes re-claimable after 15 minutes, which trades a rare
duplicate for a genuinely dead worker against never losing a reminder. Every row
in a group is marked in a single UPDATE, so a partially-sent group is not a
state the database can hold. A 403 marks the customer `blocked`, cancels **all**
their pending rows immediately — not just the current batch — and stops the
materializer generating any more. A 429 defers the rows by exactly the
`retry_after` Telegram gave, never a guessed backoff. A row that fails five
times parks in `dead_letter` instead of retrying forever. Rows arrive already
clamped inside the 09:00–20:00 window, so the send-time staleness check is a
defensive backstop, not where the rules live.

What CP9 and CP10 may rely on: `run_tick` takes a `Renderer` and a `Transport`
and knows nothing else about Telegram; widen those, not dispatch. Do not change
`transition_key_for` — those keys are already in `message_log`, and reshaping
them would make historical claims unmatchable.

## What CP8 guarantees

**An album becomes exactly one product, whatever order its photos arrive in and
however many workers handle them.** Every album arrival upserts onto CP7's
partial unique index `(shop_id, media_group_id)`, merging rather than racing:
`caption_raw` is filled only if still empty, the anchor is the EARLIEST
`channel_message_id`, and `telegram_file_id` follows the anchor. The row is
PROVISIONAL -- `finalized_at IS NULL` -- until a debounced finalize parses it.
Finalize is idempotent, and that, not the debounce, is the correctness argument:
running it twice is a verified no-op the second time. The debounce collapses N
arrivals into ONE task via a Redis deadline plus an NX lock, and a task that
fires early reschedules ITSELF rather than spawning a sibling.

The gate is "photo AND at least one usable hashtag". For a single post that is
decided on arrival and nothing is written -- proven by the id sequence, not just
by the absence of a row. For an album it CANNOT be decided on arrival, so it
moves to finalize, and a group with no usable hashtag is deleted. That makes a
very late caption self-healing: it simply re-creates the row.

An edit finds its row by the same unique keys the insert used -- by
`media_group_id` for an album, since Telegram sends the edit for whichever
message changed and that need not be the anchor -- so an edit can never make a
second product. An edit that adds a first hashtag to a previously-ignored post
indexes it. An edit that strips every hashtag off a LIVE product deactivates it
rather than deleting it.

Proven against a REAL Celery worker, not only the test recorder: an album fed
through the real dispatcher with the real Redis debounce is picked up, deferred
once while photos are still arriving (`{'action': 'wait'}`), rescheduled, and
finalized (`{'action': 'done', 'outcome': 'finalized'}`). That run found a bug
the whole green suite could not: see below.

LIVE EVIDENCE, against a real channel (`-1003987514504`), 5 Sep 2026:

| | single post | album |
|---|---|---|
| `channel_message_id` | 6 | 7 (the earliest of the group -- the anchor) |
| `media_group_id` | NULL | `14308998368401066` |
| rows created | 1 | 1, from 4 arrivals |
| `finalized_at - indexed_at` | 12 ms, inline | 4.1 s, via the debounce and a real Celery worker |
| price | NULL / `none` | NULL / `none` |

The 4.1 s is the mechanism working, not latency: a 3 s debounce plus worker
pickup. The four arrivals collapsing to one row is visible in `products_id_seq`,
which advanced by four while only one row appeared -- a conflicting
`ON CONFLICT` insert still burns an id.

Both captions were hashtag-only, so both rows exercised the `product_name()`
fallback to the first tag, and both are unpriced -- the "never drop an unpriced
post" rule got its live proof by accident rather than by design.

OPERATIONAL GOTCHA, learned the hard way. **A channel post made before the bot
is promoted to admin generates no update at all, and is unrecoverable.**
Telegram does not backfill, and the Bot API cannot read channel history -- which
is the same limitation `caption_raw` exists for. The first live attempt indexed
nothing for exactly this reason and looked like an indexer bug. It was not:
`products_id_seq` had not moved, and a rolled-back INSERT still burns a
sequence value, so the handler provably never ran.

What CP9 may rely on, and must not break:

- **Filter on `finalized_at IS NOT NULL`**, or you will show half-built albums.
  `indexed_at` cannot answer this: it is NOT NULL with a server default, so it
  is stamped the instant the row appears.
- `channel_chat_id` is on the row so `copyMessage` has a `from_chat_id` without
  reading config. `UNIQUE(shop_id, channel_message_id)` assumes ONE catalogue
  channel per shop; if that changes, the constraint has to grow that column.
- Tags are stored as `normalize_hashtag` returns them, with NO alias resolution.
  CP9 resolves the QUERY through `hashtag_aliases`. Resolving at index time
  would bake one version of the alias table into stored rows.
- `deleted_at` is still written by nothing. Filter on it defensively anyway.

## What CP9 guarantees

**A reminder carries a bouquet, and never loses a reminder to do it.** The
catalogue may ADD to a reminder; it may never COST one. An empty catalogue, a
customer whose preference matches nothing, a reminder too long to be a caption --
each falls back to the bare text CP6 sent, and the row is still marked sent.

**A reminder with a bouquet is still ONE API call.** `sendPhoto` carries the
reminder as its caption, so CP6's contract holds unchanged: every row of a group
marked in a single UPDATE, no partially-sent state. Text and photo as two
messages would have broken that, which is why one bouquet rather than three.

`sendPhoto` with the stored `telegram_file_id`, NOT `copyMessage`. The caption is
then entirely ours, rather than the shop's own post with its phone numbers,
stale prices and unrelated hashtags in it. `channel_chat_id` is still stored as
the fallback if a file id ever stops resolving.

THE RANKING RULE, in full: a product one of whose stored tags RESOLVES to the
recipient's `preferred_hashtag` through `hashtag_aliases`, else the most
recently indexed. Ties on `indexed_at DESC`.

**CP9.5 fixed the direction of that resolution, and it was a silent
correctness bug rather than a refinement.** CP9 compared the preset to the RAW
stored tag. CP8 stores tags exactly as the shop wrote them, and
`preferred_hashtag` is CHECK-constrained to `atirgul` / `tyulpan` / `lola`, so
the tier could only ever fire for a shop whose vocabulary already happened to be
ours. A shop tagging `#roza` -- an ordinary spelling, already in the shipped
alias fixture -- was as invisible as one tagging `#gulkinder`. In the live
catalogue the tier never fired at all.

The fix resolves the STORED side forward and compares canonical to canonical:

    stored '#gulkinder' --alias--> 'atirgul'  ==  preset 'atirgul'   MATCH

Same table, same direction it was built for, applied to the other operand. The
preset CHECK and the preference buttons are untouched -- widening the enum would
mean editing a constraint and a keyboard every time a shop's vocabulary differs,
which is the treadmill `hashtag_aliases` exists to avoid. A shop with its own
words adds alias rows.

Matching is `EXISTS` over the product's tags, not a join: a post carries several
hashtags and a join would return the product once per tag. In a merged reminder the preference belongs
to the recipient whose date is SOONEST -- the one the message leads with.
Excluded always: provisional albums (`finalized_at IS NULL`), inactive rows, and
`deleted_at` rows, which nothing writes yet.

NO FUZZY MATCHING, decided rather than omitted. pg_trgm needs `CREATE EXTENSION`
and elevated rights a future host may not grant, and its threshold would be a
guess made before there is usage data. Showing the WRONG flower is worse than
showing none. `hashtag_aliases` scales to as many flower types as the shop adds;
it is a different tool, not a weaker one. Revisit with real "no match" query
logs, not preemptively.

THE SEAM. `run_tick` GREW a parameter rather than changing one: `attach` is
optional and defaults to None, so a tick built without it behaves exactly as it
did at CP6, down to calling `send_text`. Every CP6 dispatcher test passes
unmodified, which is the evidence that claiming, retrying, 403, 429 and
dead-lettering were untouched. `dispatcher.py` and `render.py` still know
nothing about the catalogue; `sending/attach.py` is the single module that does.

## What CP10a guarantees

**An order is written exactly once, and it is frozen.** The confirmation screen
mints a `submit_token`; both halves of a double-tap carry it and collide on
`UNIQUE(shop_id, submit_token)`. Answering the callback and clearing the
keyboard are done too, and are NOT the guarantee -- a customer can win that
race. Proven by two concurrent submits on separate connections.

**Nothing reaches `orders` before the customer taps Ha.** The flow accumulates
a draft in FSM state; abandoning it at any step leaves the database untouched,
which is asserted at every step rather than at one.

**The snapshot is the record.** Name, price and file id are frozen at submit,
because the catalogue is rebuilt from a channel where posts are edited and
deleted. `product_id` is a convenience that may become NULL.

DELIVERY SLOTS come from THREE separate rules, and the tests keep them separate:
per-day `working_hours` decide which hours exist, `same_day_cutoff` removes
TODAY at the DATE step, and `min_lead_time_minutes` removes individual hours.
A date with no pickable hour is never offered -- offering it and then showing an
empty hour list is a dead end. `daily_order_cap` is applied at date selection,
so a full date is simply absent.

TWO SCHEMA DECISIONS worth not relitigating:

- `ON DELETE SET NULL (product_id)`, column-scoped. On a COMPOSITE foreign key a
  bare SET NULL nulls EVERY referencing column, which here includes `shop_id`
  (NOT NULL), so deleting a product failed outright and would have taken the
  indexer down with it. Postgres 15+ lets the action name its column. Found by
  the test that deletes a product out from under an order, not by reading.
- `order_reminders` IS ITS OWN LEDGER. CP6 needed `message_log` because a GROUP
  of rows shares one message; one ping is one row, so it is claimed in place
  with a state compare-and-swap. That also avoids loosening message_log's
  `customer_id NOT NULL` for something that has no customer.

WHAT CP10a DOES NOT DO: transition a status. It writes 'placed' and stops. The
other four statuses are in the CHECK from the start so the migration that starts
using them is additive. `tests/test_order_scope.py` fails the build if any code
in the order path issues an UPDATE against `orders` at all.

## What CP10b guarantees

**The shop is told exactly once, and it survives a crash.** `order_reminders`
rows are claimed by moving `state` pending -> sending, and that COMMITS before
Telegram is called. A worker that dies mid-send leaves the row claimed, so the
next tick skips it until the claim goes stale -- which is the only case where
the claim differs from SKIP LOCKED (two live workers) or from the resolve (a
finished one). Proven by killing a worker between the two, and by a transport
that opens its own connection mid-send and reads `sending` from outside the
tick's transaction.

**Telling the shop is not done inline.** Submit writes ping 0 and commits; the
handler then flushes THAT ORDER's outbox by running the tick narrowed to one
row, so delivery is immediate in the normal case and the beat is the retry. An
order the shop never learns about is the worst failure this system has, and
best-effort inline sending survives nothing.

**PING 0 IS THE ANNOUNCEMENT.** It shares the delivery reminders' outbox
because it is the same kind of thing -- one message to the shop, sent once,
claimed the same way. A second table would have meant a second copy of the
claim logic. `ping_number >= 0` was widened for it.

**Routing is group, then owners, then loud.** `shops.group_chat_id` wins; with
no group every id in `owner_telegram_ids` is tried and the fallback is logged as
a WARNING because it means setup is unfinished; with neither, the ping fails
with an ERROR naming the shop and order, and parks after the usual five
attempts. Leaving it pending forever would mean re-reading a growing pile of
undeliverable rows once a minute for the life of the shop. The order is never
at risk either way -- it is written and committed before any of this.

**The card is the snapshot.** The product row is not consulted even when it
still exists. Prices, names and the photo are what the customer agreed to buy.

CP10b changed CP10a's table twice, additively, and both were things CP10a could
not have known because the send path did not exist yet: `claimed_at` (a claim
needs a clock) and 'sending' in the state CHECK (the claim needs a state to move
to). Autogenerate detected the column and NEITHER constraint -- it compares
CHECKs by name.

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

**CP9** will want pg_trgm for fuzzy hashtag search. It is NOT installed yet:
`CREATE EXTENSION` needs elevated rights, which is a deployment question worth
settling before the code depends on it. CP9 also owes a stated similarity
threshold rather than a magic number in a query.

## Deliberately not built

**The `orders` table, pre-created empty at CP7.** Considered and skipped. The
claimed benefit was that CP10 would migrate into an existing table rather than
create one — but `op.create_table` on an empty table is the cheapest migration
there is, since there is no data to preserve. Against that, every column would
be a guess, and the guess had already moved once: the original design listed
`occasion_id`, `recipient_name`, `recipient_phone`, `note`, `source`, `total`
and `delivery_slot`, while the CP7 brief listed `product_name_snapshot`,
`price_uzs_snapshot`, `telegram_file_id_snapshot`, `delivery_time` and
`delivery_location_*`. Changing a guessed column later costs
add/backfill/drop, and changing a guessed `status` CHECK costs the
drop/recreate dance; creating it right once costs nothing.

Worth keeping from that brief when CP10 arrives: the SNAPSHOT columns. An order
must record the product name, price and file_id AS THEY WERE when it was placed.
The catalogue is rebuilt from a channel that edits and deletes posts, so a live
FK to `products` would let a bouquet silently change price, or vanish, out from
under an order already placed.


**Homoglyph detection in `normalize_hashtag`.** Still not built, and CP8 did
not change that. CP7 deferred it for want of a corpus; CP8 indexes real captions
but has not yet observed one that mixes scripts INSIDE a single word. Revisit
with evidence from a real channel, not before.

**A stale-provisional sweep.** Found by running a real worker, and left
unbuilt on purpose. If a `finalize_album` task RAISES, Celery acks it anyway
(`task_acks_late` only redelivers on worker death, not on an exception), so:

* the album's NX lock stays held for its full 300s TTL, during which further
  photos of that album schedule nothing -- self-healing, bounded, acceptable;
* the row stays PROVISIONAL, and after the TTL nothing re-schedules it. Only a
  later arrival or an edit to that album will settle it.

Nothing is lost or wrong -- the row is correct, merged and invisible to CP9's
search, which filters on `finalized_at`. But it will not fix itself. The real
remedy is a periodic sweep for `finalized_at IS NULL AND indexed_at < now() -
interval`, which belongs with CP14's monitoring rather than inside the indexer;
CP8's scope fence exists precisely to stop it being added here as "two harmless
lines". Raised now so CP14 has the specific query to write.

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
- A product is not visible to anything customer-facing until `finalized_at` is
  set. An album row exists before it is decidable, and that is deliberate -- the
  partial unique index is what stops five updates becoming five products.
- The hashtag gate is applied on ARRIVAL for a single post and at FINALIZE for
  an album, because an album's caption may not have arrived yet. A group that
  settles with no usable hashtag is deleted, which is also what makes a very
  late caption self-healing.
- An ALBUM arrival re-opens the row by setting `finalized_at` back to NULL. New
  album information invalidates the previous parse, and this is what lets a
  photo arriving after finalize still be picked up.
- Albums need a running Celery worker. Without one the row is created and stays
  provisional; nothing is lost, but nothing is searchable either.
