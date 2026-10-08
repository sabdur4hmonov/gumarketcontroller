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

**Per-person permission on the order card.** Deliberately not built;
recorded so it is a decision rather than a rediscovery. Today **any member of
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
