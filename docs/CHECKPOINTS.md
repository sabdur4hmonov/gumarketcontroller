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
| CP-MT | Multi-tenant: per-shop bot tokens, per-shop send paths, owner onboarding, one process for every shop | done, 4 commits; open items in `docs/AUDIT_MULTI_TENANT.md` |
| CP-MT2 | The rest of the multi-tenant audit: H3, H4, H5, M1, M3, L1, L2, L3 | done, one commit per finding (L2's column in its own, after CP17 merged); merged to main |
| CP16 | Ha/Yo'q pages and taklifnomas: made in every shop's bot, served as unguessable links | code done, live-proven locally; **going live blocked**: needs a domain and HTTPS (`docs/DEPLOY.md`, "Public pages") |
| CP17 | Date plans, Uzrnoma, editable invitations, photos, sections, wishes, seal, music, ten more designs | done, one commit per stage, live-proven locally; going live needs the same domain + HTTPS as CP16 |
| CP18 | Platform admin panel (/admin), pause, subscriptions, order source, gift unlock, moderation, photo purge, health + heartbeats | done, one commit per stage; live-proven locally except the platform bot's Telegram delivery (needs PLATFORM_BOT_TOKEN) |
| CP19 | Brand name in one setting, staff allowlist for order decisions, dev scripts under the gate, the two flaky tests | done, one commit per item; code-only (nothing here needed a live bot) |
| CP20 | The shop owner's own panel (/shop), holiday campaigns | done, one commit per feature; code-only, screens shot at 360 px on a throwaway database |
| CP22 | Staff-only photo/voice/text announcements, correction, confirmation, 20 captions and 10 overlays, channel publication and catalog indexing | code and text live proof done; real STT benchmark awaits the owner's ten recordings |

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

## What CP-MT guarantees

Gulbot went from one shop to many. The audit that planned it is
`docs/AUDIT_MULTI_TENANT.md`, and its status box says which findings are
closed.

**A row is sent by its own shop's bot, never by another shop's.** The reminder
tick, the order-ping tick and the health/summary alerts all take
`transport_for(shop_id)`. The registry (`bot/registry.py`) resolves each shop
to its own stored token. The single shop that existed before this keeps a
logged fallback to `BOT_TOKEN`.

**A token is stored only as Fernet ciphertext.** A CHECK refuses anything
else. The key is `SHOP_TOKEN_ENCRYPTION_KEY`, which is only ever an
environment variable.

**Two shops' bots never share conversation state.** Every FSM key carries the
bot id. This was reproduced against real Redis before it was fixed.

**One process serves every shop**, and a shop added through the platform bot
starts polling without a restart. One bot is never polled for two shops.

Nothing from the audit is open: CP-MT2, below, closed the rest, L2's
column included.

## What CP-MT2 guarantees

The findings CP-MT left open in `docs/AUDIT_MULTI_TENANT.md`, one commit each,
every one reproduced by a failing test first and mutation-proved after.
Decisions that were not obvious are recorded with their reasons.

**One shop's outage does not stop the fleet (H5).** Both send ticks hold a
circuit breaker PER SHOP (`ShopBreakers`). A shop whose bot gets no answer three
times running has its remaining rows handed back untouched -- no attempt
counted, no claim held -- and every other shop keeps sending. Proven with two
real shops in one tick, the failing shop's bot pointed at a TCP listener that
never answers (`tests/test_breaker_per_shop.py`). Mutations: 7/7 caught.

- *Decision: a fleet-wide trip stays.* Per-shop breakers alone would turn a real
  Telegram outage into three 15 s timeouts PER SHOP -- hours at a thousand
  shops, on a worker that runs one task at a time, which is exactly what pass 5
  of the pre-deployment audit fixed. So when `FLEET_BREAKER_SHOPS` (3) different
  shops go unanswered in a row with nothing answering in between, the tick
  stops and hands everything back. One or two broken bots can never cause that.
  Three, not two: two broken bots adjacent in the batch would otherwise stall
  everyone, which is the defect again.
- *Decision: the outage bound moved from 45 s to at most 105 s.* The worst
  ordering is two shops tripping in full before a third fails once: 7 sends.
  A batch that mixes shops trips after 3, as before. `test_audit_time_bounds`
  now derives the worst case from the rule and keeps a 2x margin under the
  240 s soft limit (it was 4x over the single 45 s breaker).
- *Accepted:* a shop whose bot stays silent costs each tick up to 3 timeouts
  (45 s) until its rows dead-letter. That was already true; it no longer
  delays anyone else.

**Each shop's bot is paced against its own ceiling (H4).** The limiter's
global bucket and its per-chat buckets are keyed by the shop, whose bot is the
sender, because Telegram's limits are per bot token. Before, one tick's limiter
throttled the whole fleet to one bot's 28 msg/s, and a person who is a customer
of two shops was paced as one chat. `acquire()` now REQUIRES `shop_id`: a
default would put any caller that forgot it back in one shared bucket. One shop
on its own is still held to 28 msg/s, and that half is asserted too
(`tests/test_rate_limit_per_bot.py`). Mutations: 4/4 caught.

- *Not changed:* the order-ping tick and the health alerts never went through
  the limiter and still do not. The audit named only the reminder tick's
  limiter, and both of those send a handful of messages per shop.

**Only the shop's own channel is its catalogue (H3).** The indexer takes a
post, and an edit, only when its chat IS `shops.channel_id`
(`from_the_shops_channel` in `services/indexer.py`). Before, any channel the
shop's bot was added to filled its catalogue -- and because products are keyed
on `(shop_id, channel_message_id)` and message ids are per channel, an EDIT in
a foreign channel re-priced a real product with the same message id. Both were
reproduced before the fix (`tests/test_indexer_channel_scope.py`). The check
sits in the service, in front of the single, album and edit paths, so no route
in can skip it. Mutations: 4/4 caught -- either path unchecked, NULL
accepting any channel, a recorded channel not compared.

- *Decision: NULL `channel_id` indexes nothing.* The alternative -- accept any
  channel until one is recorded, or adopt the first one that posts -- is the
  defect with a delay on it. The pilot shop predates onboarding and has no
  `channel_id` on the dev database, so this needs one operator step before
  deploying: `docs/DEPLOY.md` step 0c. The refusal is logged with the chat id
  to copy. Existing products are not touched.
- *CONTRIBUTING sweep (a value changed meaning):* `shops.channel_id` NULL used
  to mean nothing at all; it now means "indexes nothing". Every reader was
  checked: before this change there were none in `src/`, the onboarding
  service is the only writer, and the test fixtures that post to a channel
  (`test_indexer.py`, `test_chat_gate.py`, `test_indexer_concurrency.py`) now
  connect their shop to `CHANNEL_ID`, as an onboarded shop would be.

**Only the shop's own group gets past the chat gate (M3).** The gate's
exception -- an order-card tap, or a rejection reason from someone who just
tapped Reject -- now also requires the chat to BE `shops.group_chat_id`.
Before, it checked only the shape of the update, and a stranger's group got as
far as `admin_orders`, whose own chat check was the only thing refusing it.
That router check stays: two layers, each enough on its own. The lookup is
asked last, after the cheap shape checks, so ordinary group chatter costs no
query; a shop with no group lets no group in. Mutations: 3/3 caught
(`tests/test_chat_gate_own_group.py`).

- *Decision: `group_chat_id` directly, not `ping_targets`.* `admin_orders`
  reads its chats back through `ping_targets`, which falls back to the
  owners' private chats. For a GROUP update the owners can never match --
  they are users, not groups -- so the two agree, and the gate does not log
  `ping_targets`' owner-fallback warning on every tap.

**Every query in the audited services names its shop (M1).** The eleven
statements that reached tenant rows only through a parent key the caller had
already checked now carry their own `shop_id` predicate; three functions gained
a `shop_id` argument to make that possible (`list_recipient_occasions`,
`discard_pending_reminders`, `has_answered_reminder_preferences`). A structural
fence, `tests/test_query_shop_scope.py`, walks the AST of the six modules the
audit named and fails on any query statement without a shop scope, and on any
`session.get` (a primary-key fetch has no WHERE of its own). It was red on the
old code, naming all eleven. Database tests show what it buys: another shop's
ids now reach nothing. Mutations: 9/9 caught, one per restored unscoped query.

- *The audit's fourteen, accounted for.* Eleven fixed. Three are not queries
  the fence can or should change: `session.add(recipient)` (the object carries
  its `shop_id`), `announce_order`'s INSERT (its `shop_id` comes from the order
  row; the fence accepts a `shop_id=` value), and `_drop_untagged`'s
  `session.delete(product)` -- an ORM delete of an instance already loaded by a
  shop-scoped query, listed in the fence's `UNSCOPED_ON_PURPOSE` with that
  reason, and checked to still exist so the exception cannot outlive its code.
- *Decision: a wrong-shop customer in `has_answered_reminder_preferences`
  raises.* Answering "not answered yet" would hide a caller bug behind a
  repeated question.
- *Fence scope: the six audited modules, not all of `services/`.* The CP16/CP17
  share-page services were not part of the audit and are outside this branch's
  remit; widening the fence to them is a follow-up for after CP17 merges.

**Every dev and ops tool names its shop (L1).** `force_reminder` needs
`--shop-id` to send and looks the customer, the date and the person up inside
that shop; its `--list` filters in SQL. `live_browse`, `live_order` and
`live_confirm` require `--shop-id` for every mode, scope every query by it, and
speak through that shop's own bot from the registry -- before, they hardcoded
shop 1 or took "the first shop", and spoke as the process `BOT_TOKEN`. A fence
(`tests/test_tools_name_their_shop.py`) reads every script and the CLI for a
literal shop id in SQL or a keyword, "the first shop" by position, and
`build_bot()`; it was red on the three scripts. Mutations: 6/6 caught.

- *Not touched:* `scripts/live_pages.py` is CP16/CP17 share-page code; it
  already took `--shop-id` and the registry, and the fence covers it so it
  stays that way. `verify_group.py` was fixed by C4 and is fenced too.
- *Decision: `--shop-id` is required even for `--state` and `--cleanup`.* A
  cleanup scoped to one shop cannot delete another shop's order by a mistyped
  id, and a required flag cannot be forgotten on the dangerous path only.

**What a shop's own people read follows the shop -- except where it is stored
(L2, partly).** Every shop-facing path now asks one function per shop,
`services/shop_language.shop_language(session, shop_id=...)`: the order card
and delivery pings (per ping's shop, not once per tick), the stall and
dead-letter alerts, the daily summary, and the admin group's `lang` (buttons,
stamped outcomes). Nothing shop-facing names a language any more; the
`lang: str = "uz"` defaults on the senders are gone. Proven by replacing the
function so it answers Russian for shop B only: each path then speaks Russian
to B and Uzbek to A in the same run (`tests/test_shop_language.py`, red on
assertions before the change). Mutations: 4/4 caught.

The column came in its own commit once CP17 had merged (below):
`shop_language` now reads `shops.lang`.

**The seed makes more than one shop (L3).** `python -m gulbot.cli.seed` takes
`--name` (the dev shop's name stays the default), `--channel-id`,
`--group-chat-id` and `--owner-id`. Still idempotent and still never
overwrites: a rerun fills only what is unset and refuses (`SeedConflict`) a
value that disagrees with what is stored. Since H3 a seeded shop needs its
`channel_id` to show a catalogue, so the seed is where a dev shop gets wired.
Red first on an assertion: the CLI ignored its arguments entirely
(`tests/test_seed_shops.py`). Mutations: 4/4 caught.

- *Decision: no bot token argument.* A token on a command line ends up in
  shell history and process listings. The platform bot's onboarding is the
  provisioning path for a real shop -- token, channel and group as a unit --
  which the audit's L3 asked for and CP-MT already built; the dev shop speaks
  through `BOT_TOKEN`.

### `shops.lang` -- DONE (2026-10-08), as planned here

Made after CP17 merged, on its single head, as migration `4b6e1d9c2a07`.
The plan below was followed step by step; red first (six tests, the column
absent), and mutations 8/8 caught on assertions: `shop_language` ignoring
the column or reading another shop's, the migration's CHECK admitting
another code, onboarding or its router dropping the owner's language, and
the seed ignoring, overwriting or not passing `--lang`. Every existing shop
reads 'uz', exactly what it read before. The plan, as written:

1. **Migration**, additive and one revision:
   `ALTER TABLE shops ADD COLUMN lang varchar(2) NOT NULL DEFAULT 'uz'`, plus a
   named CHECK `lang_known` with `lang IN ('uz', 'ru', 'en')` -- the same column
   shape and CHECK as `customers.lang`, so there is one definition of a
   language code in the schema. A constant default is a metadata-only change on
   Postgres 11+, no table rewrite; the CHECK on a column whose every row is
   the default needs no NOT VALID / VALIDATE split, but the round trip must
   still run on a throwaway database (CONTRIBUTING, "the migration only runs
   correctly on a database that does not exist yet").
2. **Model**: `Shop.lang` mirroring `Customer.lang`, and the CHECK in
   `__table_args__`; `test_models_match_migrations` and
   `test_check_constraints.py` then cover it.
3. **The one line**: `shop_language` becomes
   `SELECT lang FROM shops WHERE id = :shop_id`. No caller changes.
4. **Onboarding writes it**: the platform bot already derives the owner's
   language (`OwnerLanguageMiddleware`); pass it through `NewShop` into
   `create_onboarded_shop`. The seed CLI gets `--lang`.
5. **Tests**: `test_shop_language.py` keeps its per-module replacement and
   gains a database test -- shop B stored as `ru`, no replacement -- plus the
   onboarding test asserting a Russian-speaking owner's shop is stored `ru`.

## What CP16 guarantees

Customers make two kinds of shareable page in their shop's bot:

- **Ha/Yo'q**: one question, and a Yo'q button that runs away.
- **Taklifnoma**: an invitation for ten event types, with an optional map pin
  and RSVP.

Both are served by `gulbot.web` at `PUBLIC_BASE_URL/p/<token>`. The design
brief is `docs/DESIGN_BRIEF_INVITES.md`, and every design is in
`docs/screenshots/share_pages/`.

**Tenancy.**
- Every page row carries `shop_id`, with composite FKs onto `customers`;
  RSVPs and referrals hang off `(page_id, shop_id)`.
- The bot reads and deletes pages only by (shop, customer, id), so a crafted
  `MyPageCB` from another shop or another customer finds nothing.
- A page links back to the bot that served the conversation, which is that
  shop's bot by construction.
- A `/start pg_<token>` arriving in another shop's bot records nothing.
- Proven in `tests/test_share_page_tenancy.py`, at the database and through
  two shops' real dispatchers, with the same person a customer of both.

**Links.**
- A link is 128 random bits (`secrets.token_urlsafe(16)`), never an id.
- Every response is `noindex`, and `robots.txt` disallows everything.
- There is no access log, because every path is a secret.

**What a stranger with a link can do.**
- Read the page. Every typed field is autoescaped.
- Press Ha once (compare-and-swap on `answered_at`).
- RSVP once per browser, as a cookie key with an upsert.
- Tap the shop's link, which is counted.

**What they cannot do.**
- POST without the page's own `X-Requested-With` header and JSON body. A
  cross-site form cannot send either, and the CORS preflight is never
  granted.
- Exceed the per-address rate limits.
- Exceed 500 RSVPs per page.
- See a phone number. Nothing in `gulbot.web` reads one.

**CSP.**
- Script, style, font and connect are allowed from `'self'` only, images
  from `'self'` and `data:`.
- There is no inline script or style anywhere and no third-party request.
- Fonts are self-hosted, OFL; see `static/fonts/LICENSES.md`.

**"They said Ha".**
- The creator gets the message exactly once, through the shop's own bot.
- The claim is committed before the send.
- A retryable failure releases the claim and the Celery task retries (3×).
- A creator who blocked the bot keeps the claim.

**Mutation proof: 22/22 guards caught on an assertion.** The list is in the
CP16 commit message. Four mutants first failed only with an exception, and
their tests were tightened until each failed on an assertion. One finding:
the referral's shop filter has a second wall, the composite FK refuses the
row.

### Decisions made during CP16, each with its reason

- **One table for both kinds.** Everything public starts from the same token
  lookup. Kind-specific columns are nullable, and a CHECK per kind says what a
  live page must have.
- **Deleting scrubs; it does not drop.** The typed fields go to NULL and the
  row stays, so the shop keeps its view and click counts. The completeness
  CHECKs read "deleted, or complete". Expired pages are scrubbed the same way
  at 03:30 (`gulbot.scrub_expired_pages`).
- **Expiry.**
  - A Ha/Yo'q page lives 60 days.
  - A taklifnoma lives until the event day plus 14 days, for the thank-you
    messages that follow an event.
  - Events can be up to 12 months ahead.
- **Creation limits.** 5 pages per customer in any 24 hours, deleted ones
  included, and 20 live at once, checked under an advisory lock. `created_at`
  is set from the same clock the limit uses: the first test run caught the
  server clock and the check disagreeing.
- **No shop logo.** `shops` has no logo column and nothing collects one, so
  the page shows the shop's name and a monogram. A logo upload is its own
  piece of work.
- **Jinja2 added as a dependency**, for autoescaping. Hand-built HTML is
  exactly where an escaping bug hides. The web server is aiohttp, already
  installed through aiogram.
- **Maps are links (Google, Yandex) and an .ics file, not an embedded map.**
  An iframe would break the strict CSP and add a heavy third party to a page
  opened on mobile data.
- **URL buttons only on https.** Telegram refuses URL buttons for localhost
  and plain IPs, and a refused button would lose the whole message. Until
  there is a domain, the link travels as text.
- **In production the feature switches itself off until `PUBLIC_BASE_URL` is
  https.** The bot says "coming soon" instead of refusing to start. A missing
  domain should not take down the shops.
- **Page language is chosen per page** (Uzbek Latin, Uzbek Cyrillic, Russian,
  English), separately from the customer's bot language (uz/ru).
  - Uzbek Cyrillic is generated from our Latin strings by `to_cyrillic`,
    pinned against hand-checked words.
  - User text is never transliterated.
- **Gendered Russian presets.** "Marry" and "valentine" are written to a woman
  in Russian, the common case for a flower shop. Uzbek has no grammatical
  gender, and anyone else types their own question.
- **RSVP shows counts in "My pages", with no push per answer.** A message per
  guest would be spam at a 300-guest wedding.
- **Only one message is pushed: the first Ha**, and only if the creator asked
  for it. It is queued to Celery from the web request, so a Telegram call
  never runs inside a page request.
- **Attribution has three parts.**
  - Views exclude Telegram's link-preview fetcher.
  - Taps on "Gul buyurtma qilish" are counted at `/p/<token>/go`.
  - A `/start pg_<token>` records a referral. A page's orders are the orders
    its referred customers placed after arriving
    (`share_pages.shop_page_stats`).
  - A returning customer who arrives this way lands on the bouquet list.
- **Fonts, checked glyph by glyph before use.** Manrope, named in the first
  brief, has no Қ Ғ Ҳ and was dropped. Great Vibes, Unbounded and Comfortaa
  switch to a complete face on `:lang(uz-Cyrl)`.
- **Rate limits are in memory, per web process.** That is right for one page
  server. More than one would want them in Redis.

### Found by looking, not by the tests

- In a real 360 px browser, the escaping Yo'q button always landed on top of
  Ha. When Yo'q left the layout, Ha re-centred into the spot just chosen as
  "away from Ha". Fixed with a placeholder, and checked over 8 consecutive
  escapes.
- Uzbek Cyrillic names in Bog' and Romantik rendered at 13 px: an `em` scaled
  from the body text. The Tungi ornament's crescent did not draw.
- Headless Chrome cannot make a 360 px window. The screenshots come from
  DevTools device emulation.

### Found by the gate during CP16, outside it -- FIXED at the start of CP17

`test_concurrency::test_two_processes_racing_a_merged_group_send_it_once_and_whole`
failed once in a full-suite run on 2026-10-03, in the F4 gate. This is a new
signature, different from the 2026-09-06 failure recorded in CONTRIBUTING.

**What the snapshot showed.** Three `race-cluster` rows:
- row 1 was `sent`;
- rows 2 and 3 were `pending`;
- all three had `attempts = 1`;
- the ledger held one `race-cluster` claim, marked sent.

**Diagnosis.** `select_due_rows` locks row by row with SKIP LOCKED, so two
workers starting together each locked PART of one merge group. Each built its
group from only the rows it held. Both claimed the same merge_key. The winner
sent a message covering its rows only; the loser's rows went back to pending,
behind a key that was already claimed.

That breaks CP6's "no partially-sent group" guarantee. It is not caused by
anything in CP16 or CP-MT, which touch neither the selection nor the claim,
and the test passed in every earlier gate today.

A rerun was not taken as evidence that it was gone.

**Fixed in CP17's first commit.** It is reproduced deterministically with
real processes, and a group is now claimed as one unit: the anchor row is
SKIP-LOCKed and the members are locked behind it. See CONTRIBUTING, "A third
occurrence".

### Live evidence, 2026-10-03, through the real dev bot (@Flowersmarketcontroller_bot)

`scripts/live_pages.py --shop-id 1 --customer-id 3`, run against the dev
database and the local page server. It used the real dispatcher and the real
Bot; the taps are synthetic, as in `live_order.py`.

- Made a Ha/Yo'q page: Uzbek, the proposal question, Romantik, notify on Ha.
- Made a taklifnoma: wedding, Sardor & Madina, 14 November 18:30, a map pin,
  RSVP on, Milliy naqsh.
- Both links arrived in the customer's DM. Both pages are stored with
  `bot_username = Flowersmarketcontroller_bot`.
- A visitor opened each page (views 1 and 1), pressed Ha, and RSVPed
  (2 guests).
- "They said Ha" was sent once; the second attempt returned `nothing`.
- Screenshots: `docs/screenshots/share_pages/live-*.png`.

## What CP17 guarantees

CP17 deepens the share pages. All of it reaches the creator through the
shop's own bot, in Uzbek, Russian or English (the customer's language), and
every public page keeps the CP16 rules: autoescaped, `style-src 'self'`, no
inline style or script, no third party, capped and rate-limited input, no
phone number unless the creator types one into a free-text line.

**Three kinds of page.**
- **Ha/Yo'q**, now optionally a **date plan**: 1–5 places (typed) and 1–5
  times (picked). After Ha the recipient picks one of each and confirms.
- **Taklifnoma**, where every visible block is the creator's to write.
- **Uzrnoma** (new): an apology letter. "Kechirdim" answers it; "Hali o'ylab
  ko'raman" runs away like Yo'q, with its own gentle lines.

**The creator hears the answer exactly once**, claimed under `FOR UPDATE`
and committed before the send (the CP6 pattern):

| Page | Message |
|---|---|
| Ha/Yo'q, no plan | "Ha!" |
| Ha/Yo'q, chosen within 10 min | "Ha! Joy: Kino. Sana: 12-oktabr, 19:00." |
| Ha/Yo'q, nothing chosen in 10 min | "Ha — but nothing chosen yet", then ONE follow-up if they choose later |
| Uzrnoma | "Kechirdi! …" with the letter quoted back |

**Editing, at the same link.** From "Mening sahifalarim" → Edit, the creator
changes any text block, the date, the venue and pin, the design, the
language, the photos, the sections and the music. `update_page` edits the
row in place (same token), scoped to shop + customer + live page. A Ha/Yo'q
page or an Uzrnoma locks once answered, and the bot says why.

**A taklifnoma's sections**, each switched on and off or filled in from the
bot: title, names, message, date/time, venue, dress code (text and up to five
palette colours), programme (rows of time + item), contact, closing line,
countdown, photo gallery (up to six), RSVP with guest count (CP16), guest
wishes wall, music.

**Twenty designs**, all original CSS/SVG (see `docs/DESIGN_BRIEF_INVITES.md`).
Ten are new in CP17. Three CP16 designs were re-themed to cover the trends
shops asked for: Oltin (cream and gold, arched frame, white florals), Konvert
(lilac envelope, wax seal with the creator's monogram, the letter revealed
section by section) and Bog' (green botanical garden).

**Public input, bounded.**
- Photos: re-encoded by Pillow (EXIF/GPS/camera gone, at most 1200 px,
  ≤ 1.5 MB stored, 10 MB / 40 MP input cap), stored per shop in Postgres,
  served only through the page's token.
- Wishes: name ≤ 40, wish ≤ 300, cleaned, ≤ 3 per guest, ≤ 300 per page,
  6 per minute per address, hideable one by one by the creator.
- The date choice: option ids must be this page's and of the right kind,
  plain integers; the first choice is kept.

**Music.** Off by default; one of three ORIGINAL tracks written for Gulbot as
notes and synthesised in the browser (no audio files; CC0, recorded in
`static/music/LICENSE.md`); a CHECK admits only those names; it never plays
until the visitor taps, which a Node test proves (no AudioContext exists
before the tap).

### Decisions made during CP17, each with its reason

- **English covers the share-page flows and the language switch, not the
  whole bot.** The brief asked for these flows in uz/ru/en; the rest of the
  bot stays uz/ru for now. `tests/test_i18n_trilingual.py` holds every page
  key to all three languages.
- **NULL means "the preset"** for a taklifnoma's title, message and closing,
  so a language switch carries the preset along and "reset" brings it back.
- **The choice waits 10 minutes** (`CHOICE_WAIT`) before the creator is told
  "nothing chosen yet": long enough to read the options, short enough not to
  leave the creator wondering. The web app queues the check with a Celery
  countdown.
- **The choice is a snapshot.** The chosen place and time are copied onto the
  page, so editing the plan later (impossible once answered anyway) could
  never change what was agreed.
- **Photos live in Postgres**, not on disk: they travel with the backup, are
  deleted in the same transaction as the page, and need no shared filesystem.
- **The programme is typed as lines** ("18:00 Kutib olish") and stored
  normalised; a picker per row would be eight taps a line. Anything that is
  not a time is refused, not half-stored.
- **Colours are a fixed palette**, one CSS class each, so no inline style ever
  reaches the page.
- **Uzrnoma is its own kind**, sharing the Ha/Yo'q answer path
  (`ANSWERABLE_KINDS`), with the letter in `message`. Its downgrade deletes
  apology pages: their kind does not exist below that revision.
- **The second button's lines are kind on purpose.** Ha/Yo'q may tease; an
  apology that pushes is not an apology. Patience and warmth, no guilt.
- **Sections are added after creation**, from Edit, so making a page stays a
  minute's work.
- **Instagram was not scraped.** The in-app browser was refused; the owner
  supplied the Instagram findings (e.taklif, taklifim.uz,
  invitestudio.uz, nafis_taklifnoma) and those shaped the addendum.
- **The geometric design uses eight-pointed girih stars**, not interlaced
  triangles: a six-pointed star reads as a religious symbol, out of place on
  an Uzbek family invitation.
- **The empty Foto frame shows the couple's initials or a heart**, never the
  shop's letter.

### Found by the gate during CP17

- **Alert cooldowns leaked between test runs.** Cooldown keys
  (`gulbot:alert:<shop>:<kind>`, one hour) were written to the broker Redis
  by tests, keyed by test-database shop ids. A rebuilt test database reuses
  those ids, so a run within the hour failed five alert tests. FIXED: each
  test session claims under its own prefix. Reproduced deterministically
  (rebuild, run, rebuild, run).
- **A killed test run can leave a committed row behind** (one shop), which
  then breaks "for every shop" jobs in later runs. The cure is to drop the
  test database; worktrees use their own (`POSTGRES_TEST_DB`), and running
  pytest in a worktree WITHOUT it drops and recreates the main one mid-run.
- **One shop without a bot stopped the health job for every shop -- FIXED.**
  That leftover row was what showed it: the alert/summary job raised
  `KeyError` out of `BotRegistry.bot_for` on the first shop row its resolver
  had no entry for, and every shop after it went unalerted. The production
  resolver (`stored_tokens`) already raised `ShopBotUnavailable`, and a
  revoked token is a failed send rather than an exception -- but the registry
  trusted every resolver to keep that contract. It now enforces it: a
  resolver's `LookupError` becomes `ShopBotUnavailable("no bot is registered
  for it")`, so every send path skips that shop with one ERROR line and serves
  the rest. Failing test first, 6/6 mutants.
- **The C9 tests had never been verified.** Their first mutation run caught
  9 of 12: an expired invitation and a Ha/Yo'q page with the wall forced on
  had no test (one added), and one mutant was equivalent (the template hides
  a closed wall on its own), so it now mutates that template guard. C9 also
  failed mypy (`Select[tuple[int]]` where SQLAlchemy 2.1 types `Select[int]`),
  and C12 passed an `ApologyDraft` that `create_page`'s signature did not
  name. Both fixed in their own stage.
- **The CP17 tables had no database-level tenancy test.** CP16's tables each
  prove the composite FK refuses a row filed under another shop;
  `share_page_options`, `share_page_photos` and `share_page_wishes` had the
  FK but no proof. Added in their own commit, with a control showing the same
  rows are accepted under their own shop.
- **Memory.** On this machine, with ~15 GB shared with other apps, running
  mutation suites and a page server beside the gate made worker processes
  fail allocation (`MemoryError` inside `test_concurrency`'s worker
  processes). Gates run alone.
- **Sleep, not hangs.** Twice a full gate appeared stuck at ~74% for hours:
  the laptop had gone to sleep inside `test_shadow_sweep.py`, the slow,
  CPU-bound file there. Gates now run under a keep-awake request.
- **The shadow sweep is slow** (64 states × 159 probes × 2 dispatchers, about
  5–8 minutes, longer with each stage's new states): not a hang.
- **A mutant reported MISSED with no output.** In C10's first batch one
  mutant came back with no pytest output at all; the runner counts that as
  missed, on purpose. Re-run alone and then in the full batch, it was caught
  on an assertion both times (12/12).

### How CP17 was finished (2026-10-05)

The previous session built C6..C12 in scratch copies. They were ported onto
main as one commit per stage:

- **C10, C11 and C12 were one scratch copy.** They were split by hand into
  three commits (seal + reveal, music, Uzrnoma), each a state that lints,
  type-checks and passes its tests on its own. The combined test file became
  `test_share_page_seal.py` and `test_share_page_music.py`.
- **The Uzrnoma line rules live in `test_share_page_apology.py`**, which
  already held them; the Uzbek Cyrillic check (no Latin left behind) joined
  them there.
- **One mutant was dropped as equivalent:** the music picker answers only in
  its own state AND checks that state itself, so removing either layer alone
  changes nothing.
- **Gates.** Commits 1, 2 and C6–C8 each passed a full gate. With the
  owner's agreement, C9–C12 and the tenancy commit each passed a stage check
  instead -- lint, format, mypy, the shadow sweep (C9–C12, which add bot
  steps and a router), a fresh-database migration round trip, every test file
  of the share-page / web / bot-page area, and the stage's full mutation set
  -- and one full gate ran on the tip before any of them was pushed.
- **Stranded, then recovered (2026-10-08).** The next session's inventory
  found C9, C10 and C11 committed only on a DETACHED HEAD in a temporary
  worktree -- on no branch, not pushed, reachable from nothing but that
  worktree -- and C12 staged but uncommitted. Its last stage check had died
  with `MemoryError` inside pytest's own traceback formatter: the machine at
  its commit limit, not a test failing. The commits were put on a branch
  before anything else was touched.
- **C12's last stage found two gaps, both closed in C12 itself.** An edit
  that emptied the letter was refused only by the database CHECK; the
  service now refuses it (`EditRefused("invalid")`), and the test asserts the
  TYPE, so a CHECK firing behind a missing guard is a failed assertion. And
  nothing ever wrote a letterless Uzrnoma straight to Postgres, so a
  migration that made `ck_share_pages_apology_complete` vacuous (`OR true`)
  passed every test -- the CHECK guard compares quoted literals and that
  mutant has none (CONTRIBUTING, "What Alembic autogenerate does NOT
  catch"). A direct database test now asks Postgres.

**Mutation totals, all on assertions:**

| Stage | Mutants |
|---|---|
| Alert-key isolation | 1/1 |
| Health job skips a shop without a bot | 6/6 |
| C6 designs | 8/8 |
| C7 photos | 12/12 |
| C8 sections | 12/12 |
| C9 wishes | 12/12 |
| C10 seal + reveal | 12/12 |
| C11 music | 8/8 |
| C12 Uzrnoma | 14/14 |
| CP17 tables, database tenancy | 3/3 |

### Live evidence, 2026-10-08, through the real dev bot (@Flowersmarketcontroller_bot)

`scripts/live_cp17.py --shop-id 1 --customer-id 3`, against the dev database
(migrated to `c5a8e2d61f37` first, checked with `alembic current`) and the
local page server. The real dispatcher and the real Bot; the taps and typed
lines are synthetic, as in `live_pages.py`. The three photos are REAL
Telegram photos: the bot sends each to the customer's DM, and the file id it
gets back is what the "customer sent a photo" update carries. 91 messages
went out.

- A date invitation with two places and two times. A visitor pressed Ha and
  chose "Bog'da sayr, Yapon bog'i", 17 October 20:00. The creator got ONE
  message: "🎉 Ha! Joy: Bog'da sayr, Yapon bog'i. Sana: 17-oktabr, 20:00."
  The second attempt returned `nothing`.
- An Uzrnoma in Russian, Konvert. "Kechirdim" was pressed; the creator got
  "🕊 Kechirdi!" with the letter quoted back, once.
- A taklifnoma made, then edited at the same link: the link is unchanged,
  and the new title, a programme row, the music button and a guest's wish
  (escaped: `&lt;b&gt;Omad&lt;/b&gt;`) are absent before and present after.
  The seal shows S&M both before and after: a Konvert made without letters
  already takes the couple's initials, so that line proves the seal is
  there, not that the edit changed it.
- Three photos stored (13–16 KB each, 900×700); photos still carrying a GPS
  block: **0**.
- Screenshots: `docs/screenshots/share_pages/live-cp17-*.png`, and every one
  of the twenty designs at 360 px as `invite-*`, `yesno-*` and `apology-*`,
  plus `plan-*` (the date plan after Ha) and `*-konvert-opened`.

Found while gathering it, both in the script, not the product:
- **A tap needs a real message.** The colour picker edits the keyboard of the
  message that was tapped; a synthetic tap on message 1 got "message can't be
  edited" from Telegram. Taps now carry the id of the bot's last real message,
  as a person's would.
- **A refused creation was silently reused.** The second run hit the 5 pages
  per 24 hours limit, and "the newest invitation" picked up the first run's
  half-edited page, printing its state as new. The script now accepts only
  pages made by THIS run and stops with the reason otherwise. The five pages
  the two failed runs made were removed from the dev database before the run
  above.
- **A full-page screenshot is not evidence of a missing photo.** The
  beyond-viewport capture left the lazy gallery blank. A cold-cache headless
  probe (fresh profile, cache disabled) loaded all three photos on Konvert and
  on Milliy alike; the gallery shot is a viewport capture scrolled to it.

## What CP18 guarantees

The platform owner's admin panel, under `/admin` on the page server, and the
gift that unlocks premium share-page parts. The brief is
`docs/ADMIN_PANEL_SPEC.md`, copied unchanged; where the owner's CP18
instructions differ from it, the instructions win, and each difference is a
decision below.

**Only a listed admin gets in, only through the platform bot.**
- `/admin` in the PLATFORM bot, from an id in `PLATFORM_ADMIN_TELEGRAM_IDS`,
  answers with a one-time link: 10 minutes, one use, link preview off, at
  most 5 per 10 minutes. Any other id gets nothing -- "/admin" falls through
  to onboarding, so a shop owner learns nothing about a panel.
- Opening the link shows a "Kirish" button; only the POST spends it, by
  compare-and-swap. A link-preview fetcher must never be what logs in.
- The admin list is checked when the link is minted, when it is spent, and
  on every request: removing an id ends its sessions at once.
- The session cookie is HttpOnly, Secure, SameSite=Strict, Path=/admin, and
  lasts one hour, absolutely. Link and session tokens are stored as SHA-256
  only.
- ONE gate for every /admin route (a middleware): no live session gives 401
  or 403, and every POST also needs the session's CSRF token. A test walks
  the router, so a route added later cannot be forgotten.
- Login is rate-limited per address. The panel has its own CSP, the pages'
  policy plus `form-action 'self'`.
- Production refuses to start with an empty or unparsable admin list. One
  typo empties the whole list rather than letting a wrong id in.

**Every admin action is recorded, and the record cannot be rewritten.**
`admin_audit_log` holds every login, refusal, CSRF refusal, logout, pause,
resume, payment, gift switch and hide. Each entry has before -> after, the
reason and the address, written in the action's own transaction. A trigger
refuses UPDATE, DELETE and TRUNCATE: the log is append-only in the database,
not only in the UI.

**Pause stops real work** (`shops.status`). For a paused shop:
- the reminder tick skips its rows, which stay pending;
- its bot answers a customer with one line and creates no customer row;
- its pages stay up without the "order flowers" link.

Its group still works, so orders already placed can be confirmed. On resume,
the ordinary 6-hour staleness rule expires what is too late rather than
firing a backlog, and the resume's audit entry says how many will expire.

**Every order says where it came from** (`orders.source`):
- **reminder**: the reminder's button, which wins over any page visit;
- **page**: the latest page through which the customer reached THIS shop's
  bot, within 30 days, named in `source_page_id`;
- **direct**: anything else.

Older orders stay NULL, shown as "before CP18". The page FK is
same-shop by construction.

**The gift: premium unlocks per shop, after a confirmed order.**
- Premium is defined in one place (`services/premium.py`): the ten CP17
  designs, music, and photos. Every kind of page and everything else stays
  free.
- The unlock is written in the transaction that confirms the customer's
  order at THAT shop, only when the confirmation happened, and only while
  the shop's rule is on.
- The walls are in the service: create, edit to a premium design, music on,
  any photo. Turning a premium part off never needs the gift.
- The bot marks premium designs with ⭐ and says how to unlock them.
- The same person, a customer of two shops, ordering at A unlocks nothing
  at B. The composite FKs make a cross-shop unlock unrepresentable.

**Moderation is reversible and total.**
- A hidden page answers as gone on EVERY public route, found by walking the
  router, and records nothing a visitor does. The creator's text is kept,
  and showing the page again restores it.
- A wish hidden by moderation cannot be un-hidden by its page's creator.
- A hide always has a reason, in the service and in a CHECK.

**Photo files of gone pages are dropped; the rows stay.** The nightly scrub
and the creator's delete null the bytes and set `purged_at`, so the counts
and the per-shop disk figures stay true. A CHECK allows only "purged" or
"not purged", never half.

**The panel never calls Telegram.**
- Bot health comes from a snapshot the worker takes every 10 minutes through
  each shop's own bot: getMe, then the bot's standing in the channel and the
  group. It never posts.
- Every periodic task writes a heartbeat. The page server's `/healthz/jobs`
  answers 503 when the ticks stop. It runs in the web process, so it works
  when beat or the worker is what died: the hook for an external
  dead-man's-switch monitor (AUDIT.md section 3, B).

**Counts before personal data.**
- No screen shows a customer's phone or name, the owner's whole phone (it
  is masked, e.g. +998 90 *** ** 12), or a page token. A page's link is its
  secret, so pages are shown by internal id.
- A test renders every screen with all three planted and greps for them.

### Decisions made during CP18, each with its reason

- **Login by a one-time link, not the spec's password + TOTP.** The owner
  asked for it. It also removes a password to phish or reuse: holding the
  listed Telegram account IS the credential.
- **The gift unlocks everything premium.** The spec said "one premium
  design"; the owner's brief said music, gallery and premium designs. The
  brief wins.
- **The rule defaults ON.** The brief describes it as the product's rule;
  the panel switches it off per shop. Off means no NEW gifts; granted ones
  are kept.
- **Premium = the ten CP17 designs.** The ten CP16 designs stay free, so
  every shop has a full free set.
- **Grandfathering.** A page that already has a premium part keeps it. Only
  turning a part ON needs the gift.
- **No backfill of gifts from past confirmations.** No real customer has
  any yet (the pilot has not run in production), and a backfill in the same
  transaction as DDL is against CONTRIBUTING.
- **The order source is recorded, not derived.** The spec allowed a
  derived "approximate" stopgap. Recording it at submit costs one lookup and
  is exact.
- **Pause uses the existing 6-hour staleness rule**, not the spec's 24
  hours. It is stricter, already proven, and one rule instead of two.
- **"Overdue" is a badge.** Nothing pauses a shop automatically: billing
  is manual, as the spec's MVP says.
- **Alerts are computed when the page loads**, from the data, with no
  alerts table and no acknowledge. The spec's acknowledge/resolve and
  owner-Telegram push are deferred.
- **No "Add shop" form and no editable config.** Shops come from the
  platform bot's onboarding; the spec puts both later.
- **The panel is in Uzbek**, the owner's language. Times are shown in UTC,
  labelled.

### Found while building, each fixed and tested

- `record_cta` counted a tap on a deleted, expired or hidden page, and on a
  paused shop's page. It now counts only a tap that can go somewhere. The
  moderation test found it.
- `scheduled_notifications` has no `updated_at`. The panel's first queries
  assumed one. The screen tests found it.
- CP17's music, photo and section tests act as customers who have the gift
  (an explicit fixture), since they test how those parts work. The gating
  is proven only in `test_premium_gift.py`.
- `test_order_status`'s committed-world cleanup was blocked by the unlock's
  FK to the order. It is now `ON DELETE CASCADE`: an unlock never outlives
  the order that granted it.
- On a phone, the audit log and two tables were unreadable. They are cards
  and narrow tables now, found by looking at the live screens.

**Mutation totals, all caught on assertions:**

| Stage | Mutants |
|---|---|
| A pause | 7/7 |
| H login, sessions, audit | 16/16 |
| B subscriptions | 9/9 |
| C order source | 9/9 |
| D gift | 12/12 (one more judged equivalent: the unlock lookup without its shop) |
| E moderation | 12/12 |
| F photo purge | 6/6 |
| G health, heartbeats | 9/9 |
| I screens | 10/10, + 1/1 for "no usable bot" |

### Live evidence, 2026-10-09, against the dev database and the local page server

`scripts/live_cp18.py --admin-id <id> --link-file <path>`, run with
`PLATFORM_ADMIN_TELEGRAM_IDS=<id>` for the page server and the script.
The dev database was migrated to `d5e841dbb2be` first (after a dump) and
checked with `alembic current`.

- **Bot health, through the real dev bot (read-only):** shop 1 has
  token_valid=True, @Flowersmarketcontroller_bot, group_ok=True, and its
  channel unchecked because the pilot shop has no `channel_id` recorded
  (DEPLOY step 0c).
- **The login link:** "/admin" went to the REAL platform dispatcher from
  the admin id. The handler, the database and the link are real.
  **Synthetic part: delivery.** There is no `PLATFORM_BOT_TOKEN` on this
  machine (a BotFather step), so the reply was captured by a recording
  session instead of sent. It carried the link with the preview off.
- **Login and the screens:** headless Chrome at 360 px opened the link,
  pressed "Kirish", and was redirected to `/admin`. Before that, `/admin`
  without a session answered 401. All six screens were captured to
  `docs/screenshots/admin/`.
- **Pause and resume of the dev shop, through the panel's own buttons:**
  the shop went active -> paused -> active. The audit log holds
  `login_link_sent`, `login`, `shop_pause` ("live CP18 evidence",
  127.0.0.1) and `shop_resume`, each with the admin id; see
  `admin-9-audit.png`.
- **`/healthz/jobs` answered 503**, naming the send ticks and the health
  check, because no worker runs on this laptop. That is the endpoint doing
  its job.

**Still to do with a real platform bot (an owner's step):** set
`PLATFORM_BOT_TOKEN` and `PLATFORM_ADMIN_TELEGRAM_IDS`, send /admin, and
confirm the link arrives in the DM. The handler path is the one above.

## What CP19 guarantees

Code-only hardening; the owner could not test anything by hand, so every
claim below is a test, a measurement or a mutation.

**The product's name is one setting.** `Settings.brand_name` (`BRAND_NAME`,
default the working name "Gulbot", undecided) is the only place it is
written. Bot texts say `{brand}` and `t()` fills it; the admin templates call
`brand()`; the gone page, the calendar file's PRODID and the dev seed ask
`gulbot.brand.brand_name()`. `tests/test_brand.py` fails the build on the
name typed anywhere a person reads it: Python literals (not docstrings), every
catalog value, every template, the pages' JS and CSS. Lowercase `gulbot` in
code is the package, logger, task and Redis-key namespace and is exempt; so
are the music license records (provenance). The setting refuses `< > & { }`,
empty, and over 40 characters.

**A staff list decides who may confirm and reject orders** (AUDIT.md
section 3, A, closed). `shop_staff`, managed by the owner with `/staff` on the
platform bot. No list = anyone in the shop's group, exactly as before; one
person on it = only the list and the owners. Checked on the tapper for
confirm, reject, abort and the typed reason, after the chat check.

**The dev scripts are under the gate.** All seven already named their shop
and used per-shop bots (CP-MT2, L1); none was tied to the single bot. They
were outside ruff and mypy and had drifted (16 mypy errors, one real dormant
bug: a sync lambda where an async scheduler is awaited). Now linted and
typechecked with everything else.

**The lock-hold test asks the lock, not a stopwatch; the race tests say why
they fail.** See CONTRIBUTING, "A stopwatch in a test measures the machine",
and the test_concurrency section's CP19 entry.

### Decisions made during CP19, each with its reason

- **An empty staff list keeps today's rule**, rather than "owners only". The
  brief asked that nothing break today; every existing shop's group is its
  staff. The admin panel's shop screen warns while a shop has no list.
- **Owners always decide and cannot be listed.** An owner who lists a clerk
  must not lock themself out, and a listed owner would be a second source of
  truth about who owns the shop.
- **The list is managed on the platform bot, not in the shop's group.** The
  group is exactly where the people the list is meant to exclude can read
  everything; the platform bot already knows owners.
- **Telegram's user picker first, a typed id as the fallback.** The picker
  hands back the id an owner cannot easily find. A label is kept for the
  owner's own list only; the admin panel shows a count, never who.
- **At most 20 people per shop.** A list is a shop's handful of people, not a
  second group; the cap also bounds the owner's screen.
- **`{brand}` is filled by plain replacement, not `format`,** so a catalog
  string with literal braces and no arguments still comes back unchanged.
  Uzbek suffixes attach directly ("{brand}ga"): right for a name ending as
  the working name does; a name ending in k or q would want "-ka"/"-qa".
- **The calendar UID keeps "@gulbot".** It is an identifier a phone already
  holds; changing it with the brand would make old events unmatchable.
- **The stale `origin/mt2-audit` branch was deleted** after checking every
  commit is on main (eight by patch id, H5 as `aa9d2da` after a rebase, its
  test file identical).

### Found by the gate during CP19

- **Four tests compared a sent message with the RAW catalog string,** which
  after CP19.1 holds `{brand}` while the bot sends the name. Three went red.
  The fourth was worse: `test_chat_gate` asserts the welcome is NOT sent to a
  group, and against a string that can never be sent that assertion could
  never fail -- a guard gone vacuous without a sound. All four now compare
  with `t()`, which is what the bot sends. The targeted runs before the
  commit had not included those files; the full gate did.
- `.env.example` must name every setting as a real key (a commented-out
  `BRAND_NAME` did not count); `test_infrastructure` caught it.

**Mutation totals, all caught on assertions:**

| Item | Mutants |
|---|---|
| 1 brand | 13/13 |
| 2 staff allowlist | 21/21 |
| 4 lock hold | 2/2 |

## What CP20 guarantees

Two features a shop pays for. Code-only again: proved by tests, mutations and
screens rendered by the real page server at 360 px against a throwaway
database of synthetic data (`docs/screenshots/shop/`), then dropped.

**A shop owner's panel that sees one shop and nothing else (`/shop`).**
- The way in mirrors `/admin`, bound to one shop: `/panel` in THAT shop's
  bot, from one of its owners, answers with a one-time link (10 minutes, one
  use, preview off, at most 5 per 10 minutes). Opening it shows a button;
  only the POST spends it. Cookie HttpOnly, Secure, SameSite=Strict,
  Path=/shop, one hour. Ownership is checked at minting, at spending and on
  every request; removing an owner ends their sessions at once.
- `/panel` is answered by an update middleware ahead of the pause check and
  the customer middleware: a paused shop's owner still gets in, and an owner
  asking for the panel is never registered as a customer. Anyone else's
  `/panel` passes through untouched.
- ONE gate for every `/shop` route; every POST needs the session's CSRF
  token. NO ROUTE TAKES A SHOP: every screen reads the session's shop, and
  the test walks every route as shop A's owner with shop B's data planted --
  also with `?shop=<B>` -- and finds none of it.
- Customers (phones in full: they are the shop's own), saved dates in the
  next 30 days, orders filtered by status, source and dates, CSV exports
  (audit-logged, formula cells neutralised). The log (`shop_audit_log`) is
  append-only by trigger.

**Holiday campaigns.** Three conditions, all required: the shop runs the
holiday (`/shop/holidays`), the customer opted in (Settings, "Bayram
tabriklari"; `consent_events`, default off), and for a lunar holiday the
platform admin entered that year's date (`/admin/holidays`). A holiday is one
more date in the same per-customer plan (a stable negative spec id in the
pure engine), so the send window, merging and the weekly cap cover it with no
second copy of any rule; its rows go through the existing outbox. Opting out
or switching a holiday off drops what was planned at once. An order from the
holiday's bouquet button is `source = holiday`.

### Decisions made during CP20, each with its reason

- **`/panel` lives in the shop's bot, as a middleware.** Only that bot knows
  which shop is asking, and a router handler would run after the customer
  middleware had already registered the owner as a customer.
- **The CRM shows full phone numbers; `/admin` masks them.** These are the
  shop's own customers, whom it calls; the platform admin is a third party
  to them.
- **Saved dates show the customer's own label and the date only.** Nothing
  else about the person is stored, and the panel adds nothing.
- **The panel is in Uzbek**, like `/admin`; bot texts keep their languages.
- **New Year is 31 December.** The evening people buy flowers for, not the
  morning after.
- **Holidays use the customer's own offsets and send time.** The same
  preference that governs their personal reminders; no second setting.
- **A tie for "soonest line" goes to the person.** A merged reminder whose
  earliest line is a birthday keeps the person's button; the date the
  customer saved outranks the shop's campaign.
- **A new callback prefix for holiday orders**, not a field on OrderStartCB:
  reminder buttons already in customers' chats keep their shape.
- **The new CHECKs on `scheduled_notifications` were added validated**, not
  in CONTRIBUTING's NOT VALID / VALIDATE steps: existing rows satisfy them
  trivially and no production database exists yet (DEPLOY has never been
  run), so there is no table to lock.
- **Owner-facing CRM routes are not IP-restricted** (DEPLOY step 9): shop
  owners log in from their own phones.

### Found while building, each fixed and tested

- **A message of only whitespace crashed the `/panel` check** --
  `split()[0]` on nothing -- in front of every handler, for every customer.
  The order-flow tests type blank answers on purpose and found it; it has
  its own commit and test.
- **"Planned, then pruned in the same run" hid a mutant.** Planning
  holidays for everyone was invisible because the same materialize run's
  prune deleted the rows again; the test now pins what the run inserted,
  not only what remains.
- **The full gate found seven fakes shaped like the pre-CP20 row.** The
  addressed-label tests built reminder rows without the new `holiday`
  column, which render now reads first. Fixed in the fakes (real rows always
  carry it), in its own commit; the gate then passed, 2064 tests.

**Mutation totals, all caught on assertions:**

| Feature | Mutants |
|---|---|
| 1 shop panel | 20/20 (+1 judged equivalent: the orders query's shop WHERE, behind its JOIN to the shop's own customers) |
| 2 holiday campaigns | 18/18 |

## What CP21 guarantees

The runbook has been run -- not on a VPS, which does not exist yet, but on a
stand-in built by following it: Ubuntu 24.04 with systemd as PID 1, Python
3.11 from deadsnakes, Caddy and Docker from their own repositories, the code
from a `git archive` of the tracked tree, `/etc/gulbot/gulbot.env` root:gulbot
0640, Postgres and Redis on the server's own 127.0.0.1 and nowhere else
(`deploy/rehearsal/`). `rehearse.sh` drives it and tears it all down; the
full transcript, token redacted, is `docs/rehearsal/cp21-transcript.txt`.

**The rehearsal, 2026-10-11 (second run; exit 0):**

| DEPLOY step | Result |
|---|---|
| 5 | the prod override publishes Postgres and Redis on 127.0.0.1 only |
| 6 | `environment=production database=gulbot_prod`; without the env file every process REFUSES TO START, naming all five problems |
| 7 | `current` = `heads` = `8f2d6c41b9a3` on an empty database |
| 7b (new) | pilot seeded, its bot stored encrypted; a rerun changes nothing |
| 8 | `systemd-analyze verify` clean on all four units; worker `concurrency: 2 (prefork)`; beat processes: exactly 1, also at the end; 0 restarts on every unit, twice checked |
| 9 | the repo's Caddyfile validates; internal TLS, verified against Caddy's own root CA |
| 10 | `/healthz` 200 with CSP, noindex and HSTS; `/admin` 401; `/shop` 401; `/demo/yesno` 200; a real share page 200 over HTTPS; `/healthz/jobs` `ok` after the first health check |
| reminders | a row due a minute ago, for a chat no bot can reach: beat ticked, the prefork worker took it (`groups: 1, sent: 0`) through the pilot's own bot, and the row went `failed`, attempts 1, kept for retry -- processed, and nobody messaged |
| 13 | backup units verify clean; timer armed for 03:10 Tashkent; one backup; restore drill PASS, 32/32 tables, revision equal; no drill database left |
| teardown | containers, volumes, image, env file and CA removed; 0 left running |

**The restore drill, also against the dev database:** 26/26 tables (photos
included), revision `d5e841dbb2be` both sides, PASS. A tampered count and a
table missing from the counts each made it FAIL with exit 1.

### Found by the rehearsal, each fixed

- **The pilot shop had no bot on a fresh server** (first run). `BOT_TOKEN`
  serves only the shop the per-shop-tokens migration flagged, and on an empty
  database it flags none; the seeded pilot was "not the legacy shop allowed
  to use BOT_TOKEN". The bot refused to start and systemd restarted it every
  ten seconds, while `list-units` said `active running`; every reminder
  failed "no usable bot". DEPLOY step 11 ("the pilot may keep using
  BOT_TOKEN") was true only of the dev database. Fixed: `seed
  --store-bot-token` and DEPLOY step 7b (CP21.1, 9/9 mutants).
- **An instant "active" hid that crash loop.** The rehearsal and DEPLOY step
  8 now read `NRestarts`, which must stay 0.
- **The backup hung after a complete dump.** Closing the duplicated fd is
  not EOF while the coproc's own copy of the pipe is open; psql is now told
  to quit, and the rehearsal bounds the run at five minutes.
- **Every unit file was executable** (systemd warned). Not a repo defect --
  git has them 0644 -- but a Windows working tree copied as-is; the image is
  now built from `git archive`, and a test pins the scripts' 0755 in git.

### Decisions made during CP21, each with its reason

- **The pilot's token is stored from the environment, never an argument.**
  The same rule as onboarding's: a token on a command line ends up in shell
  history and in `ps`.
- **The backup unit `Wants=` Docker rather than `Requires=` it.** If Docker
  is down the script fails loudly on its own; `Requires=` only made the unit
  unloadable wherever `docker.service` is not a unit.
- **The rehearsal mounts this machine's Docker socket into the stand-in.**
  The backup must `docker exec` into the Postgres container as root does on
  the VPS; a second Docker daemon inside the container would rehearse nothing
  more. Its one other difference from production -- the container is called
  `gulbot-rehearsal-postgres`, because the dev machine already runs a
  `gulbot-postgres` -- is a systemd drop-in, visible in the script.
- **Copying dumps off the server stays the owner's.** It needs credentials
  for a machine that does not exist yet; DEPLOY step 13 says so plainly.
- **Not rehearsed, because a container cannot show them:** ufw, real DNS and
  a public certificate, unattended upgrades, Telegram from the VPS's network.

**Mutation totals, all caught on assertions:**

| Change | Mutants |
|---|---|
| 1 `seed --store-bot-token` | 9/9 |
| 3 deploy-file guards | 10/10 (9 text mutants, plus the script's exec bit cleared in git) |
| 2 restore drill | 2/2, run by hand: a wrong count, a missing table -> FAIL, exit 1 |

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

**Per-person permission on the order card.** BUILT AT CP19 as the staff
list (see "What CP19 guarantees"); kept here as the record of why.
Deliberately not built before; recorded so it was a decision rather than a
rediscovery. Today **any member of
the shop's group can confirm or reject any order.** Permission is by CHAT, not
by person: `routers/admin_orders.py` checks that a tap came from one of the
chats `ping_targets` sent the card to, and never asks who tapped. That is
correct for a shop whose group is exactly its staff, and wrong the day a shop
adds a courier, a supplier or a relative who should see orders without deciding
them. Found and written down in the pre-deployment audit, pass 4.

A per-admin allowlist would need, roughly:

* a list of who may decide -- `shops.admin_telegram_ids` alongside the existing
  `owner_telegram_ids`, or a small `shop_admins` table if roles are expected;
* the check in `confirm`, `ask_for_a_reason` and `enter_reason` against
  `callback.from_user.id` / `message.from_user.id`, with a clear refusal to a
  member who is not on it (answered as an alert, so the group is not spammed);
* a way for the owner to manage that list without psql -- the same gap as the
  shop settings flow above, and the reason this is not a one-line change;
* a decision on what the owner-fallback path means when there is no group (the
  owners' own DMs are already the only chats allowed, so it is safe as is).

**An external dead-man's switch for beat.** Deliberately not built; **needed
before a real production launch beyond the pilot, not before the pilot
itself.** If the beat process dies, nothing enqueues a tick, and nothing says
so. The health check cannot catch it, for two reasons:

* it is itself a beat task, so it stops with beat;
* it alerts through Telegram, so it is also blind during a Telegram outage.

No code change inside the bot fixes either one. The shape is a monitor outside
the deployment: each tick pings a URL, and the monitor pages someone when the
pings stop. That needs a conversation, not a commit: which service, what
interval, and who gets paged. Found in the pre-deployment audit, pass 5. Until
then, see docs/DEPLOY.md for the pilot's manual check.

**CP18 built the hook.** Every periodic task writes a heartbeat, and the page
server's `/healthz/jobs` answers 503 when the ticks stop -- from the web
process, so it still answers when beat is what died. What remains is the
external monitor itself: `docs/DEPLOY.md`, step 12.

**The health check on its own queue.** Deliberately not built. The worker runs
one task at a time, so the five-minute health check waits behind whatever tick
is running. Pass 5 measured an outage tick at up to 100 minutes. That is what
made this matter, and the bound the fix put on a tick removes most of it:

* the circuit breaker ends an outage tick after about 45 s;
* a 240 s soft time limit catches anything else.

A dedicated queue with its own worker would make the health check independent
of the ticks entirely. That is real infrastructure — a second worker process,
routing, one more thing to deploy and watch — for a benefit that only bites at
volumes the pilot will not reach soon. Revisit with the dead-man's switch above.

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


## CP22 — announcement authoring (code and text live proof complete)

### CP22.1 — preparation port

Started only after origin/main and local HEAD were verified at `85bfebe`,
containing the completed CP20 and CP21 commits, with a clean working tree.
The standalone numeral parser and isolated flower/colour matcher are ported
to `gulbot.announcements`; the preparation design is `docs/CP22_DESIGN.md`.
The source uses Decimal for scale bounds as well as arithmetic: no binary
float comparison in the migrated parser. Exact numerals are protected before
domain matching; fuzzy matches and conflicting aliases remain owner-review
candidates. No bot behaviour is changed by this phase.

Preparation evidence: 167 unit tests, 8/8 assertion-only mutant catches,
10/10 text-only sample prompts. Integration gate evidence is recorded after
the repository gate below; preparation evidence is not a substitute for it.

Repository gate: `make.ps1 check` passed: lint/format, strict mypy (145 source
files), shadow sweep zero in shop and platform, **2253 tests passed** in
2936.77 seconds. Sleep was inhibited for the long gate. Free RAM before it
was 0.89 GiB; no speech model was downloaded or loaded. Ported code separately
retained **8/8 assertion-only mutation catches, zero errors**, and 10/10
text prompt checks (`cp22-parser-proof.json`). A configured-secret scan passed
on every phase file before commit/push.

### CP22.2 — local authoring, review and publication

Implementation includes 1–10 photos/albums, Uzbek voice or text, corrected
field review and edits, explicit confirmation, 20 Latin-Uzbek captions,
10 original Pillow overlays plus no overlay, shop favourites, an exact
Telegram preview, channel publication and link. Picker labels are Uzbek;
internal style IDs stay stable. All captions use a controlled CP8 name,
labelled CP7 integer price before owner strings, and canonical hashtags.
All 20 styles are tested with three prices and hostile worst-case owner text,
HTML escaping and the stricter 1024 UTF-16-unit budget including entities.

Announcement publishing requires an explicit owner or ShopStaff membership
in an active shop. CP19's empty-list permission for order cards cannot authorize
publishing to a channel; that legacy behaviour is intentionally not reused.
Every callback/service/worker result rechecks actor, shop and draft revision.
Customer/foreign-owner callbacks and a shared owner's draft from another shop
are refused for every action. The two new tables have root shop FKs; favourites
and alias reads are shop scoped. Migration `9c22e4d87b10` is additive and has a
fresh named-revision downgrade/upgrade test, in addition to existing full-chain
round-trip and model-drift checks.

Every edit clears confirmation/preview. A text replacement supersedes queued
speech. The publication claim is committed BEFORE Telegram I/O and returned
receipts BEFORE indexing. Successful retries index without reposting; an
ambiguous timeout/crash requires inspecting the channel, never a blind resend.
The final send uses the exact preview caption and Telegram file IDs, including
the uploaded first-photo overlay. Indexing calls the SAME CP8 ingest/finalize
functions, always, so it does not rely on Telegram delivering an own-post
update. Real-dispatcher tests feed later own-post updates too and prove one
finalized catalog row for 1-, 2- and 10-photo posts.

STT uses local-only paths, CPU/int8/Uzbek, two threads and one resident model.
Missing paths fail to text entry; no runtime model download. The dedicated
`stt` queue/unit is concurrency 1, prefetch 1, soft/hard 360/420 seconds; the
normal worker consumes only `celery`. The longer bounds replace the prep
proposal because the recorded Uzbek fine-tune clip already took about twice
audio duration. Task-owned DB/Bot clients close per run; only synchronous
weights are cached. Audio is erased before text persistence/notification;
an independent private-directory guardian handles hard-killed workers. No
audio or voice file IDs are stored in the new tables. Optional Gemini is off
and requires a flag, key and explicit reviewed model, with changing free-tier
terms documented. A timeout error callback runs on the normal queue; a queued
job that expires before execution may need the owner's always-available text
replacement rather than an automatic timeout edit.

The spelling data is unmodified u2b3k/uz-hunspell GPL-3.0 at
`a27cccf4f7dd06734b0bc66d56ce759f9fc28b61`; both `.dic/.aff`, licence/readme,
hashes and source link are committed. The original corrector uses unique
one-edit root suggestions, preserves punctuation/order and protects domain,
number, URL/email/handle/tag spans and capitalized proper names. Corrections
are shown beside raw text before confirmation. Missing dictionary data leaves
text/domain extraction usable. Common negated colour/flower mentions are
excluded with a warning, not silently chosen. Noto Sans Regular/Semibold and
OFL licence are pinned to `ffebf8c1ee449e544955a7e813c54f9b73848eac`; glyph tests
cover Uzbek Latin/Cyrillic. No editor-pro source, media or model was copied.

STT comparison and provisional choice (no new speech run on this laptop):

| Candidate | Licence / planned download | CPU/RAM evidence | Bouquet accuracy / latency | Decision |
|---|---|---|---|---|
| Generic multilingual faster-whisper small | MIT, ~486 MB | upstream int8 ~1.48 GB; reserve 1.5–2.5 GiB | not measured; recorded editor-pro Uzbek 61.372 s clip: load 5.06 s, inference 79.38 s | baseline |
| yuldashev222 Uzbek small CT2 / OvozifyLabs parent | Apache-2.0, ~972 MB, existing cache metadata | int8 CPU budget 1.5–2.5 GiB, not newly measured | not measured; same recorded clip: load 5.9 s, inference 127.24 s; project reported better Uzbek text | provisional primary |
| navai-uz Uzbek small | Apache-2.0, source ~0.98 GB; CT2 int8 estimate 250–350 MB | same small-model planning budget; conversion needs another capable host | not measured; publisher corpus WER is not bouquet field accuracy | independent comparator |
| Vosk small Uzbek 0.22 | Apache-2.0, 49 MB ZIP | generic small-model guidance ~300 MB; plan 0.3–0.6 GiB | no local bouquet accuracy/timing | low-memory comparator |

Sources/licence links and the precise read-only editor-pro evidence are in
`CP22_DESIGN.md`. Choose finally by exact price correctness, then flower/count,
then latency/RAM on the owner's ten recordings. The fine-tune is provisional,
not a completed accuracy evaluation. DEPLOY recommends 2 vCPU/4 GiB minimum,
8 GiB preferred for this stack with small Whisper. No large model download or
recognition benchmark was run. The benchmark's no-recordings path returns 2
without loading a model; its real path records CPU, decode settings, local
model metadata/revision, load time, p50/p95 latency, peak RSS, field accuracy and
normalized WER. Run one engine per process/command, serially.

Evidence: the first integrated contract test failed on an assertion before
router installation. Further regression reds covered description references,
missing dictionary data and negation. Fake STT covers success/error, FFmpeg
mono 16 kHz PCM arguments, queue boundaries, exact ack edit and audio cleanup;
hard-kill cleanup uses a real killed child process. Guard proof is in
`cp22-guard-proof.json`: **31/31 CP22.2 assertion-only catches, zero errors**,
with original sources restored and a green final baseline. Including CP22.1,
this feature has **39/39** assertion-only mutations. The configured-secret
scan is also mutation-proven: even a fake-looking configured credential is
refused, with only its file path printed. Exact synthetic CP21 fixture tokens
are exempted by hash; no file is exempted. Git preserves vendored asset bytes
and tests verify every upstream licence/font/dictionary hash.

Gallery: `cp22-gallery/index.html`, 20 caption screenshots, 10 image screenshots,
no-overlay screenshot and overview under `cp22-gallery/screenshots/`. The
sample bouquet is original schematic artwork for demonstration, not a real
stock photo. The in-app browser tool could not initialize its installed
assets, so screenshots were rendered with existing Chrome/Playwright in a
fresh headless profile; no browser download or personal profile access.
Every overlay was visually inspected in a contact sheet; premium caption and
gold-corner card inspected at full resolution. Reproduce with
`scripts/gallery_cp22.py` and `scripts/capture_cp22_gallery.cjs`.

Final CP22.2 repository gate: **passed**. `make.ps1 check` completed with
lint/format (351 files), strict mypy (161 source files), zero shop/platform
shadow violations, and **2429 tests passed in 4661.58 seconds (1:17:41)**.
The whole gate took 5174.20 seconds, exited 0, and was sleep-inhibited.
Free RAM before this corrected run was 1.74 GiB; no large speech model was
downloaded, loaded or benchmarked. The configured-secret scan passed across
all 662 tracked files, including the live proof. Only documentation recording
these results changed after the green gate; gated sources stayed frozen.
The next full run lost its log handle while the D: workspace volume was
temporarily unavailable. Its wrapper exit was not accepted as green evidence
without the final pytest summary. Once D: returned, `gulbot_test` alone was
dropped again and the entire gate restarted with sleep inhibition and a log
under the system TEMP directory. No application/test source changed between
these runs; no other project's processes were stopped.
The first integration gate exposed the existing exact Celery task inventory
and `.env.example` setting inventory: both required CP22 additions. That failed
run was stopped before the slow shadow-mutant tests; only its verified process
tree was stopped, and `gulbot_test` was dropped immediately. The repaired
inventory/deployment tests pass against a newly rebuilt test DB. No test was
weakened: both bounded STT task names and all seven settings are now explicit.

The stable-log full run reached completion: 2428 passed, one assertion failure
in the existing CP9 reminder import-boundary guard. Shared keyboards imported
the announcement menu context, whose eager permission-service import pulled
CP8's indexer into CP9's read-only reminder path. The permission import now
occurs only during the middleware's private bot-update authorization check.
The existing guard was reproduced red unchanged, then the reminder-scope and
menu tests passed (13 tests), with strict mypy clean. Reintroducing the eager
import was separately mutation-proven: one assertion failure, zero errors,
with a green restored baseline. The corrected full gate is rerun below.

Live evidence passed using the channel supplied by the user, `@guldokonkanal`
(`-1003987514504`). Bot API confirmed `@Flowersmarketcontroller_bot` is an
administrator with posting permission; the channel creator was used as the
dev owner after verifying their private chat is accessible to that bot.
Only the empty local Shop 1 wiring was populated. Its dev database was upgraded
from `d5e841dbb2be` through the additive chain to `9c22e4d87b10`.

`scripts/live_cp22.py` exercised the production parse/review confirmation,
premium caption, gold-corner exact preview, channel publication and SAME CP8
indexing services. Actual post: `https://t.me/guldokonkanal/13`; finalized
catalog Product 23 is "Atirgul buketi — 51 dona", 450000 UZS. Receipt and
catalog evidence are in `cp22-live-proof.json`; the actual returned Telegram
photo and post/catalog evidence page are `cp22-live-post.jpg` and
`cp22-live-evidence.html`. These are real Bot API/channel results with choices
supplied by the CLI, not a claim of human Telegram taps. No voice recording
was supplied, so the explicitly allowed text fallback was used.

No own `channel_post` update arrived during the measured 8.5-second observation
window; zero updates were pending before and after, and none were acknowledged
or dropped. This is an observation, not a Telegram delivery guarantee. The
catalog entry was finalized independently of own-post update delivery.
Real STT accuracy/latency evaluation still awaits the owner's ten recordings;
the one-command benchmark and sample manifest are ready.

## CP23 — flower templates (150), Instagram Story images (150), Instagram publishing (off)

### What CP23 guarantees

**150 post templates, built as a system** (`announcements/themes.py`,
`layouts.py`, `flower_templates.py`, `designs.py`). Template =
`<theme>.<layout>`: ten layouts (classic, minimal, festive, premium, playful,
short sale, gift, new arrival, price-first, story card) x fifteen flower themes
(atirgul, kust atirgul, lola, xrizantema, gerbera, liliya, pion, gortenziya,
eustoma, chinnigul, orxideya, alstromeriya, mimoza, aralash buket, qutidagi
gullar). Each theme: 2-3 palettes after real varieties -- the bouquet's colour
picks one -- emoji, an ORIGINAL line-art motif (`assets/motifs/*.svg`, drawn by
`scripts/motifs_cp23.py`; a test regenerates them and fails on any
difference), hashtags the alias fixture resolves, and wording for the flower's
occasions. Uzbek Latin and Russian are written; Uzbek Cyrillic is derived
(`script.py`), so the two Uzbek scripts never disagree.

- **Every caption, whatever the template, keeps the catalogue header**: line 1
  the controlled title (CP8's product name), line 2 the labelled price CP7
  reads with HIGH confidence, before any owner text; hashtags last. Price-first
  makes the price bold and prominent but never moves it above the title.
- **Every overlay text is fitted into a declared panel** -- the font shrinks to
  a floor, then a name gets an ellipsis; a price is never cut -- and every box
  is recorded, so overflow is tested as geometry. Text is drawn only on solid
  panels, in colour pairs whose contrast (WCAG >= 4.5) is tested per palette.
- **Selection**: after confirmation the draft gets the shop's favourite layout
  FOR THAT FLOWER; else, if the shop saved a CP22 style, the CP22 family
  unchanged (saved defaults keep working); else the flower's classic. "🌸" shows
  the detected flower's ten as previews on the owner's own photo; "Boshqa
  shablonlar" lists all fifteen flowers and the CP22 styles. Mixed flowers are
  "aralash buket"; flowers in a box are the box theme. "⭐" saves per flower.

**150 Instagram Story images** (`announcements/stories.py`): ten story layouts
x fifteen themes, 1080x1920 from the post's first photo, with the flower's
name, the price and the shop. Every text container lies between y=250 and
y=1580 (Instagram covers the top ~250 px and the bottom ~340 px). Offered
after publication; sent as a DOCUMENT (no recompression) and as a photo, with
how to share it from the phone. Author among owners/staff only, published
posts only, own shop only.

**Instagram auto-publishing, built and OFF** (`services/instagram*.py`,
`worker/instagram_tasks.py`, `/shop/instagram`, `/ig/...`). See DEPLOY 18 for
what only the owner can do. Tested against a fake Graph server only.

### Decisions made during CP23, each with its reason

- **A box is not a flower.** CP22's tests keep "quti"/"box" out of the lexicon
  deliberately (packaging, not content), so the box theme is read from the
  owner's own words, not added to the lexicon.
- **New lexicon flowers** (kust atirgul, mimoza; "liliya" as an alias of
  nilufar) and alias fixture v2, so every theme's hashtag resolves. Seeding
  aliases was in no DEPLOY step at all; it now is (7b and 14). Nothing seeds a
  NEWLY ONBOARDED shop's aliases on its own -- recorded as an open item below.
- **No SVG library.** The motifs use a small, refused-outside-it SVG subset
  rasterised by Pillow (three-times supersampled, cached per size and colour).
- **Price-first keeps the title first.** CP8 names a product after its first
  line; a price line there would name every product "Narxi: ...".
- **The template choice survives a re-confirm once the owner made it**; until
  then a re-confirm re-derives it from the (edited) flowers.
- **The Instagram connect is a LINK, not a redirect**, and its callback lives
  outside /shop: the panel's CSP allows forms only to itself, and its
  SameSite=Strict cookie is not sent on a navigation that began at
  instagram.com -- the one-time state is the authority there.
- **The story URL token rides in the task arguments** (Redis on loopback, 15
  minutes); only its hash is stored. Meta must fetch the image, so the URL has
  to exist for a while; the image is wiped the moment the attempt ends.
- **A token Meta rejects retires the connection** rather than being retried.

### Found while building, each fixed and tested

- **The page server's no-access-log rule had no test.** Every `/p/` and now
  `/ig/` path is a secret; a test now runs the entrypoint and requires
  `access_log=None` (mutation-proven).
- **Two Phase 1 mutants first survived**: own-text escaping (no project line
  contains `&` or `<` yet -- a test now injects one) and a hashtag test that
  compared against the function under test (now independent).
- **One CP22 test assumed the CP22 default style**: a new shop now previews a
  flower template, which needs the photo; its fake bot hands one over.

### Evidence

- Tests added: 2,317 (1,920 template/caption/overlay/motif, 36 selection,
  2 migration round-trips, 322 story, 37 Instagram). Captions: all 150 x 3
  languages x 3 prices; overlays: all 150 x 3 photo shapes with a 9-digit price
  and a long shop name; stories: all 150 x 2 photo shapes.
- Mutations, all caught on assertions: templates/selection **21/21**, stories
  **8/8**, Instagram **20/20** -- 49/49.
- Render timings (`docs/cp23-render-timings.json`; this laptop, measured while
  a full gate ran beside it, so pessimistic): post at full size median ~0.1 s
  warm, ~0.13 s cold; story median ~0.23 s warm. Motif rasters are cached per
  process; template previews render at 720 px and story previews at 270x480,
  both off the event loop.
- Gallery: `docs/cp23-gallery/index.html` -- every post template (with its exact
  caption) and every story layout for all fifteen flowers at phone width.
  Sample photos are schematic drawings of each flower's motif, not real
  bouquets or stock images.
- **Live, through the dev bot and the dev channel @guldokonkanal**
  (`docs/cp23-live-proof.json`, images `docs/cp23-live-rose.jpg`,
  `cp23-live-tulip.jpg`): a rose announcement ("Qizil atirgul, ellik bitta dona,
  narxi to'rt yuz ellik ming so'm") detected as atirgul, published with
  `atirgul.premium` -> https://t.me/guldokonkanal/14, catalogue Product 24
  "Atirgul guldastasi — 51 dona", 450 000; a tulip announcement ("Sariq lola
  yigirma besh dona...") detected as lola, published with `lola.festive` ->
  https://t.me/guldokonkanal/15, Product 25 "Lola guldastasi — 25 dona", 300 000.
  A story image (arch, magazine) for each was sent to the owner as a document
  and a photo. Choices were supplied by the script through the same functions
  the buttons call -- not human taps -- and the text path was used (no voice).
  The dev database was upgraded through the additive chain to `d23b4e8f1a26`.

### Open

- A newly onboarded shop gets no hashtag aliases until `seed_aliases` is rerun
  (pre-existing; DEPLOY now says so). Seeding at onboarding is the fix.
- Instagram publishing has never met the real Meta API (fake server only).

## CP23 addendum — fixing what was heard, editing what was posted, the shop's logo

### What the addendum guarantees

**Audit first.** CP22 already had: per-field edit buttons (all five fields,
description included), the raw text beside the parsed fields, warnings, a
text replacement that re-ran extraction, and a new voice that replaced the
result. It lacked: marks on the UNSURE fields, a preview of the post on the
review screen, explicit "Matnni tuzatish" / "Qaytadan gapirish" / "Bekor
qilish", any learning, and any way to touch a post after publication.

- **The confirmation screen** shows what was heard, what was understood (⚠
  on a guessed flower or colour, an unlabelled or ambiguous price, a missing
  count), what was learned or applied, and the post EXACTLY as the channel
  would get it -- after every fix. Voice and text share it.
- **Four ways to fix**, each returning to that screen with the corrected
  values: "✏️ Matnni tuzatish" (the corrected text through the SAME
  extraction), the field buttons, "🎤 Qaytadan gapirish" (a new voice replaces
  the result), "❌ Bekor qilish" on every step before publication (the draft
  is deleted; a post that went out is never touched by it). Nothing publishes
  without confirmation.
- **Learning, per shop** (`announcement_corrections`): a short mishearing
  the owner fixes -- at most 3 words / 40 characters a side -- is applied
  before the general lexicon next time, for THAT shop only. A change of mind
  (words the bot understood) and a rewritten description are never learned;
  a button teaches only when it replaces a wrong GUESS. 200 a shop, least
  recently used dropped; "🧠 O'rganilganlar" lists them, each deletable.
- **"📋 Mening e'lonlarim"** (owners and staff): a published post's price,
  count or description (editMessageCaption), its flower template
  (editMessageMedia), its story image again, or deletion. The catalogue
  follows through the SAME `apply_edit` an edited channel post uses (now
  also following a replaced photo's file id); a deleted post goes through
  the new `deactivate_post`.
- **The shop's logo** (the owner's request): sent with /logo by an owner,
  stamped on every photo of every announcement and every story, never over
  text or a panel, switchable per announcement.
- **Type** (the owner's request): the same Noto Sans, set better -- size caps
  per role (price, then name, then shop), lines set as one centred block,
  tracked badges.

### Decisions, each with its reason

- **Learning only mishearings.** A correction that would rewrite understood
  words would turn every future rose into a tulip.
- **The bot calls `apply_edit` itself after its own edits.** Live, Telegram
  delivered the bot NO `edited_channel_post` for its own caption edit within
  10.5 s (recorded below), the same as CP22 saw for own posts.
- **Owners, not staff, set the logo.** Staff publish; the brand is the
  owner's.
- **No new font.** Asked whether a handwriting font should be downloaded, the
  owner answered that clean, better-set computer type was meant.

### Found while building

- **CP22's vendored dictionary was stored in git with LF**, unlike its pinned
  upstream CRLF bytes: the CP23 gate's fresh worktree failed CP22's own hash
  test. Re-stored; a new test asks git itself (commit 6c68257).
- **The CP23 Phase 1 gate**: 4,386 passed, that one failure.
- Three addendum mutants and one logo mutant first survived; each exposed a
  test that looked through the wrong window (a capped read, an error instead
  of an assertion, a second guard, text-only overlap) and was fixed.

### Evidence

- Mutations, all on assertions: fixing/learning 13/13, published posts 8/8,
  logo and type 11/11 -- 32/32. CP23 in all: 49 + 32 = 81/81.
- Live, through the dev bot and channel (`docs/cp23-addendum-live-proof.json`):
  "Qizil atirgil, o'n bitta dona..." -- "atirgil" marked unsure -- fixed with
  "Matnni tuzatish", learned atirgil -> atirgul; the next announcement "Oq
  atirgil yigirma bitta dona..." was corrected automatically (no field
  unsure) and published at https://t.me/guldokonkanal/16 with a SAMPLE logo,
  removed afterwards; its price edited 300 000 -> 350 000 from "Mening
  e'lonlarim" and the catalogue's Product 26 shows 350 000. No speech model
  runs on this machine: the "heard" text stands in for the recogniser's
  output, said so in the proof.
