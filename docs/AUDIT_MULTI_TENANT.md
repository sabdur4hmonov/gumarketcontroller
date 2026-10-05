# Multi-Tenant Conversion Audit

> **Status, 2026-10-05.** This is the audit as written, unchanged below this
> box. The fixes landed in four commits, then one commit per remaining finding;
> see `docs/CHECKPOINTS.md`, "CP-MT" and "CP-MT2".
>
> | Finding | Status |
> |---|---|
> | C1, C2: global outbox drain through one bot | **fixed**: every row is sent through its own shop's bot |
> | C3: FSM keys without the bot id | **fixed**: reproduced first, then fixed |
> | C4: `verify_group.py` UPDATE with no WHERE | **fixed**: `--shop-id` is required |
> | H1: one global token | **fixed**: per-shop Fernet-encrypted tokens |
> | H2: `resolve_single_shop` | **fixed**: one process polls every shop |
> | H5: one breaker across shops | **fixed** (CP-MT2): a breaker per shop; a failing shop's rows are handed back while the others send. A shop with no usable bot fails alone, as before |
> | H3: `shops.channel_id` never read by the indexer | **open** |
> | H4: global 28 msg/s limiter | **fixed** (CP-MT2): the global and per-chat buckets are per shop's bot |
> | M1, M3, L1 (scripts other than verify_group), L2, L3 | **open** |

**Target:** convert Gulbot from one flower shop to ~1000 independent shops, each
with its own bot token, catalogue channel and admin group.

**Scope:** complete inventory only. No solutions proposed, no code changed.

**Audited:** 2026-09-23 against the working tree at `C:\dev\gulbot`
(`src/` 13,628 LOC, 12 tables, 866 tests).

---

## Headline: the premise of question 1 is wrong, in your favour

The brief asks for "every database table that currently has no shop/tenant
concept." **There are none.** Every table in this schema already carries
`shop_id`, and the tenant boundary is enforced by Postgres rather than by
application code.

This is not an accident. `CONTRIBUTING.md:267` states the standing convention —
"`shop_id` is on every table from day one, even with one shop" — and
`models/shop.py:3-5` records the reasoning: *"Retrofitting tenancy is a data
migration; carrying it from day one is a column."* `tests/test_tenancy.py`
exists to prove it holds at the database level.

So the expensive, dangerous half of a multi-tenant conversion — the schema
migration and the backfill — **is already done.** What remains is concentrated
in a much smaller area: the **process/transport layer**, which genuinely does
assume one bot token and drains one global outbox.

The real risk in this project is therefore *not* "we forgot a `shop_id` filter
on a query." It is **"the right row was selected and then sent through the
wrong bot."** The inventory below is ordered accordingly.

---

## Risk ranking summary (question 7)

| # | Finding | Tier | Leakage type |
|---|---|---|---|
| C1 | Global outbox drain, single bot — reminders | **CRITICAL** | Customer of shop A messaged by shop B's bot |
| C2 | Global outbox drain, single bot — order pings | **CRITICAL** | Shop A's order card posted into shop B's group |
| C3 | FSM Redis keys carry no bot id | **CRITICAL** | Mid-order state shared across shops; **reproduced** writing a shop-B order with shop A's product/price |
| C4 | `verify_group.py` UPDATE with no WHERE | **CRITICAL** | All 1000 shops repointed to one admin group |
| H1 | `bot_token` is one global setting | HIGH | Blocks per-shop bots entirely |
| H2 | `resolve_single_shop` refuses >1 shop | HIGH | Hard startup block; zero test coverage |
| H3 | `shops.channel_id` is never read | HIGH | Any channel the bot joins fills that shop's catalogue |
| H4 | Global 28 msg/s rate limiter | HIGH | Fleet throughput collapse |
| H5 | Per-tick circuit breaker spans all shops | HIGH | One dead token stalls the fleet |
| M1 | 14 derived-scope queries (no `shop_id` in the query itself) | MEDIUM | Safe today; caller-dependent |
| M2 | Celery: 2 of 5 tasks cannot loop over shops | MEDIUM | Structural, not leakage |
| M3 | Admin chat gate does not check the shop's own group id | MEDIUM | Defence-in-depth gap |
| L1 | Dev scripts hardcode `shop_id = 1` / `LIMIT 1` | LOW | Dev-only |
| L2 | Shop-facing language hardcoded `"uz"` | LOW | Cosmetic |
| L3 | Seed CLI creates one named dev shop | LOW | Cosmetic |

---

# TIER 1 — CRITICAL

These cause **cross-shop data leakage or misdelivery** if missed. All four are
in the transport layer, and none of them are caught by the existing tenancy
tests, because those tests verify the *database*, which is not where these
live.

## C1 — The reminder tick drains a global outbox through one bot

**File:** `src/gulbot/sending/dispatcher.py`

| Line | What it does |
|---|---|
| 156-175 | `select_due_rows()` — selects due `scheduled_notifications` **with no `shop_id` predicate at all**. Filters only on `state` and `due_at_utc`. |
| 178-196 | `_load_group_context()` — loads `Occasion`, `Recipient`, `Customer` by id sets only, no shop filter. |
| 199-235 | `group_due_rows()` — *derives* `shop_id` from `customer.shop_id` (line 222) but only for the `DueGroup` record. |
| 425+ | `run_tick()` — receives ONE `transport`, built from ONE bot, and sends every group through it. |
| 511, 514 | The actual sends. `chat_id=group.telegram_user_id`, using the single transport. |

**Why this is critical.** The `DueGroup` knows its `shop_id`. The transport does
not. In a fleet, one tick pulls shop A's and shop B's due reminders into the
same batch and pushes all of them through whichever single bot token
`build_bot()` returned. Every customer of every shop receives their reminder
**from one shop's bot account** — the shop's name, avatar and @username are
wrong on every message, and replies land in the wrong shop's inbox.

**Aggravating factor.** `worker/tasks.py:43` builds the bot **outside** the
session loop, so there is no seam where a per-shop bot could currently be
selected without restructuring.

## C2 — The order-ping tick has the identical defect, with worse blast radius

**File:** `src/gulbot/sending/order_pings.py`

| Line | What it does |
|---|---|
| 166-205 | `claim_due_pings()` — claims due `order_reminders` **with no `shop_id` predicate**. Only `due_at_utc`, `state`, and stale-claim recovery. |
| 207-212 | The claiming UPDATE — `WHERE OrderReminder.id.in_(due)`, no shop scope. |
| 106-151 | `load_card()` — `SELECT ... FROM orders JOIN customers WHERE orders.id = :id`. **No `shop_id`.** Safe *only* because the composite FK `(customer_id, shop_id)` guarantees the joined customer is same-shop. |
| 231 | Per-ping resolve UPDATE, `WHERE id = :id`, no shop scope. |
| 432 | Hand-back UPDATE, `WHERE id = :id`, no shop scope. |
| 335 | `breaker = CircuitBreaker()` — one breaker for the whole cross-shop batch. |

**Why this is worse than C1.** `ping_targets()` (lines 88-103) correctly resolves
the destination **per shop** from `shops.group_chat_id`, falling back to
`shops.owner_telegram_ids`. So the *chat id* is right. But the *bot* sending to
it is the single global one.

A bot can only post into a group it is a member of. In a fleet this produces
one of two failures, both bad:

- If shop B's bot is not in shop A's group → the ping fails, is retried 5 times,
  and dead-letters. **The shop never learns an order was placed** — which
  `order_pings.py:26-29` itself identifies as "the worst failure this system
  has."
- If one bot *is* in several groups (a plausible support/ops arrangement) →
  **shop A's order card, with the customer's name, phone number and delivery
  address, is posted into shop B's admin group.** That is a direct PII breach
  across tenants.

## C3 — FSM state keys do not include the bot id

**File:** `src/gulbot/bot/factory.py:63-65`

```python
def build_storage() -> RedisStorage:
    settings = get_settings()
    return RedisStorage(redis=Redis.from_url(settings.redis_url(settings.redis_db_fsm)))
```

No `key_builder` is passed, so aiogram 3.31.0 uses `DefaultKeyBuilder`, whose
signature (`aiogram/fsm/storage/base.py:58`) defaults to **`with_bot_id=False`**.
The resulting key (verified in `build()`, lines 75-99) is:

```
fsm:<chat_id>:<user_id>[:<part>]
```

Combined with `FSMStrategy.USER_IN_CHAT` (`factory.py:82`) and the fact that in a
**private chat `chat_id == user_id`**, the key for a given person is effectively
`fsm:<uid>:<uid>` — **identical across every shop's bot**, because all shops
share one Redis instance and one FSM database (`redis_db_fsm = 2`,
`config.py:42`).

**REPRODUCED 2026-09-26, and worse than first written.** Two real `Bot`s
(ids 111111 and 222222), two real `build_dispatcher()`s, each with its own
`build_storage()` call, one Redis. Both storages reported
`DefaultKeyBuilder(prefix='fsm', with_bot_id=False)`, and both bots built the
same key for the same person:

```
fsm:7770001:7770001:state   = PlaceOrder:entering_address
fsm:7770001:7770001:data    = {"product_id": ..., "product_name": "Oq atirgul (SHOP A)",
                               "price_uzs": 450000, "telegram_file_id": "file-Shop A ...", ...}
```

What happened, in order:

1. The user ordered from shop A and stopped at "type your address".
2. Shop B's bot, **before the user had said anything to it**, read that exact
   state and data (`identical to shop A's view: True`).
3. The user sent an address to **shop B's** bot. Shop B consumed it as the
   address for shop A's order and asked for a landmark.
4. Continuing on shop B through landmark → recipient → submit, bot B showed the
   customer `Oq atirgul (SHOP A) — 450 000 so'm` and wrote this row:

```
orders: shop_id = <shop B>, product_id = NULL,
        product_name_snapshot = 'Oq atirgul (SHOP A)', price_uzs_snapshot = 450000,
        telegram_file_id_snapshot = 'file-Shop A ...'
```

**The composite FKs did not stop it.** `create_order`
(`services/orders.py:156-164`) looks the product up scoped to the current shop,
correctly misses, and then **falls back to the snapshot fields carried in the
FSM draft**, writing `product_id = NULL`. A NULL FK is not checked, and the
snapshot columns (`product_name_snapshot`, `price_uzs_snapshot`,
`telegram_file_id_snapshot`) are plain values that no constraint relates to any
shop. The result is a shop-B order for shop A's bouquet at shop A's price with
shop A's photo — a real cross-tenant row, not just a confused conversation.

Control: the same run with `DefaultKeyBuilder(with_bot_id=True)` produced keys
`fsm:111111:7770002:7770002:*` and shop B saw `(None, {})`.

It produces no error, no log line, and no failed constraint. It is **not
covered by any existing test**: the whole suite runs one shop, so the keys never
collide.

## C4 — `verify_group.py` updates every shop row

**File:** `scripts/verify_group.py:108`

```python
rows = conn.execute(
    "UPDATE shops SET group_chat_id = %s RETURNING id, name", (chat_id,)
)
```

**No `WHERE` clause.** Today this is harmless — there is one row. Run once
against a 1000-shop database and **every shop's order cards, health alerts and
daily summaries are redirected into a single admin group.** There is no undo;
the previous `group_chat_id` values are not recorded anywhere.

Line 110-111 even iterates the returned rows (`for shop_id, name in rows`),
which shows the script was written knowing it could match several — it just
never restricts to one.

---

# TIER 2 — HIGH

Structural blockers and fleet-wide availability risks. These do not leak data
between shops, but they make the fleet non-functional or fragile.

## H1 — One global bot token

**File:** `src/gulbot/config.py:45` — `bot_token: SecretStr = SecretStr("")`

Read at exactly one place: `src/gulbot/bot/factory.py:57`.

`get_settings()` is `@lru_cache`d (`config.py:139`), so the token is
process-global and immutable for the process's life. `Shop` has columns for
`channel_id`, `group_chat_id` and `owner_telegram_ids` but **no token column** —
the one piece of per-shop Telegram wiring that is missing from the model.

`config.py:84-89` also lists `BOT_TOKEN` in `PRODUCTION_REQUIRED_ENV`, so the
production guard currently *requires* a single global token to be set.

**Call sites that would each need a per-shop bot:**

| File | Line | Context |
|---|---|---|
| `src/gulbot/bot/run.py` | 40 | Long-polling entrypoint |
| `src/gulbot/worker/tasks.py` | 43 | Reminder tick |
| `src/gulbot/worker/tasks.py` | 84 | Order-ping tick |
| `src/gulbot/worker/tasks.py` | 120 | Health check + daily summary |
| `src/gulbot/cli/force_reminder.py` | 180 | Ops CLI |
| `scripts/live_browse.py` | 65 | Dev script |
| `scripts/live_confirm.py` | 266 | Dev script |
| `scripts/live_order.py` | 103 | Dev script |
| `scripts/verify_group.py` | 64 | Dev script |

## H2 — The startup check that refuses more than one shop

**File:** `src/gulbot/bot/run.py:19-29`

```python
async def resolve_single_shop(session_factory) -> int:
    """v1 runs one shop. Fail loudly rather than guessing which one."""
    async with session_factory() as session:
        ids = list(await session.scalars(select(Shop.id).order_by(Shop.id)))
    if len(ids) != 1:
        raise RuntimeError(
            f"expected exactly one shop, found {len(ids)}. Run: python -m gulbot.cli.seed"
        )
    return int(ids[0])
```

This is the explicit single-shop gate the brief asks about, and the **only** one
in `src/`. It is called once, at `run.py:38`, and the resolved id is passed to
`build_dispatcher(shop_id=...)` at line 42.

**Two things worth flagging:**

1. **It has zero test coverage.** `grep -rn "resolve_single_shop"` returns only
   its definition and its one call site. Nothing in the 866-test suite asserts
   the >1 behaviour, so there is no test that will go red when it changes.
2. **`run.py` is the only entrypoint.** There is no webhook server, so this
   function is the single process-level chokepoint — which is good news for the
   conversion.

## H3 — `shops.channel_id` is declared but never read

`grep -rn "channel_id"` across `src/` returns exactly **one** hit outside the
model: the column definition itself (`models/shop.py:49`).

**What this means.** `bot/channel.py:72-113` (`on_channel_post`) takes `shop_id`
from the dispatcher-bound `CustomerMiddleware` (`middlewares.py:194`), **not**
from the chat the post arrived in. `as_channel_post()` (`channel.py:58-69`)
stores `message.chat.id` as `channel_chat_id` but **nothing ever compares it to
`shops.channel_id`.**

So the indexer's rule is currently "whatever channel this bot can see is this
shop's catalogue." In a fleet, if a shop's bot is added to any second channel —
by mistake, by a reseller, or maliciously — **that channel's posts are ingested
as that shop's products**, with prices, and become orderable.

The composite FK cannot catch this: the row is written with a valid `shop_id`.
It is a *correct-looking* row with wrong provenance.

## H4 — The rate limiter's global bucket is per-process, not per-bot

**File:** `src/gulbot/sending/rate_limit.py:23-26`

```python
GLOBAL_RATE_PER_SECOND = 28.0
PER_CHAT_RATE_PER_SECOND = 1.0
```

The module docstring (line 5) is explicit: *"GLOBAL ~30 messages/second across
the whole bot."* Telegram enforces that limit **per bot token**. A fleet of 1000
bots has a real budget of ~30,000 msg/s, but the limiter instantiated once per
tick (`worker/tasks.py:44`) would throttle the entire fleet to **28 msg/s
combined** — roughly 0.03 msg/s per shop.

The nightly materializer can queue thousands of reminders. At 28/s shared
across 1000 shops, the evening send window would not clear.

## H5 — One circuit breaker per tick, spanning every shop

**Files:** `src/gulbot/sending/dispatcher.py:479`,
`src/gulbot/sending/order_pings.py:335`

Both do `breaker = CircuitBreaker()` once per tick, then abandon the **whole
remaining batch** after 3 consecutive network failures
(`transport.py:65`, `BREAKER_THRESHOLD = 3`).

The design is sound for one shop — `transport.py:84-86` documents it as "per
tick, never shared," with the next tick as the recovery path. In a fleet the
batch is cross-shop, so **three consecutive network failures caused by one
shop's bot** (revoked token producing timeouts, a bot deleted by its owner)
hand back every other shop's claimed rows. Those shops' reminders are delayed
by a full tick, every tick, for as long as the bad token exists.

---

# TIER 3 — MEDIUM

## M1 — Derived-scope queries: 14 statements with no `shop_id` in the query itself

These reach rows via a parent key (`customer_id`, `recipient_id`,
`occasion_id`, `order_id`, or a PK) that the **caller** has already
shop-validated. **All 14 are safe as currently called** — I traced each one.
They are listed because they encode their safety in caller discipline rather
than in the query, which is exactly the class of code that breaks when a new
caller is added.

Grouped by file, as requested:

### `src/gulbot/services/recipients.py`

| Line | Statement | Scope relied on |
|---|---|---|
| 63-68 | `SELECT Occasion WHERE recipient_id = :r AND active` | Caller passed a `recipient_id` from `get_recipient()`, which *is* shop+customer scoped (lines 30-42) |
| 100-104 | `UPDATE Occasion SET label, type WHERE recipient_id = :r` | Guarded by the shop-scoped `UPDATE Recipient` at 86-96 returning a row first |
| 126-131 | `UPDATE Occasion SET active = false WHERE recipient_id = :r` | Same guard, lines 112-122 |
| 25 | `session.add(recipient)` | `shop_id` is set on the object at line 24 |

### `src/gulbot/services/occasions.py`

| Line | Statement | Scope relied on |
|---|---|---|
| 99 | `session.get(Occasion, new_id)` | `new_id` was just returned by the shop-scoped INSERT at 80-96 |
| 102-127 | `DELETE ScheduledNotification WHERE occasion_id IN (...)` | Caller supplies ids from shop-scoped queries |
| 164-169 | `SELECT ConsentEvent.id WHERE customer_id = :c AND type = :t` | `customer_id` came from the shop-scoped middleware |

### `src/gulbot/services/orders.py`

| Line | Statement | Scope relied on |
|---|---|---|
| 198 | `session.get(Order, order_id)` | Id from the `(shop_id, submit_token)` INSERT at 166-189 |
| 220-230 | `INSERT OrderReminder ... ON CONFLICT` | `shop_id` taken from `order.shop_id` (line 222) |

### `src/gulbot/services/preferences.py`

| Line | Statement | Scope relied on |
|---|---|---|
| 66-70 | `SELECT reminder_count, preferred_send_time WHERE Customer.id = :c` | `customer_id` from the middleware. **The only service function in the package whose signature omits `shop_id` entirely.** |

### `src/gulbot/services/materializer.py`

| Line | Statement | Scope relied on |
|---|---|---|
| 207-212 | `SELECT Customer WHERE id IN (grouped.keys())` | Keys come from `_active_occasions_by_customer()`, which *is* shop-scoped (line 79) |

### `src/gulbot/services/indexer.py`

| Line | Statement | Scope relied on |
|---|---|---|
| 341-346 | `DELETE ProductHashtag WHERE product_id = :p AND hashtag NOT IN (...)` | `product` was loaded by a shop-scoped query (259 or 367) |
| 314 | `session.delete(product)` | Same |

**Note on false positives.** A naive `grep` for `shop_id` near a query
**overstates** this list badly. `services/bouquets.py` lines 140, 213 and 222
look unscoped but are not — they use the `sellable(shop_id)` helper
(`bouquets.py:63-82`), whose first element is `Product.shop_id == shop_id`.
Likewise `indexer.py:259` and `:367` build `query = select(Product).where(
Product.shop_id == shop_id)` on a preceding line. I verified these by reading,
not by pattern matching.

## M2 — Celery tasks: 3 of 5 already loop over all shops (question 5)

**File:** `src/gulbot/worker/app.py:65-98` (beat schedule),
`src/gulbot/worker/tasks.py`

| Task | Beat name | Schedule | Loops over shops today? |
|---|---|---|---|
| `gulbot.materialize_all_shops` | `materialize-nightly` | 03:00 Tashkent | **YES** — `tasks.py:144-154`, `SELECT Shop.id` then `for shop_id in shop_ids` |
| `gulbot.check_health` (stall/dead-letter alerts) | `health-check` | every 300 s | **YES** — via `_for_every_shop("check")`, `tasks.py:104-141` |
| `gulbot.send_daily_summary` | `daily-summary` | 21:00 Tashkent | **YES** — via `_for_every_shop("summary")`, same helper |
| `gulbot.send_due_reminders` | `send-due-reminders` | every 60 s | **NO** — drains the global outbox (see **C1**) |
| `gulbot.send_order_pings` | `send-order-pings` | every 60 s | **NO** — drains the global outbox (see **C2**) |
| `gulbot.finalize_album` | *(on demand)* | — | **N/A** — already takes `shop_id` as its first argument (`tasks.py:263`) |

The helper's own docstring (`tasks.py:107-110`) states the intent outright:

> *"v1 has exactly one shop, so this is a loop over one row — written as a loop
> anyway because both jobs are shop-scoped in every query, and a second shop
> should not need this file edited."*

That promise holds for the three health/materialize tasks. It does **not** hold
for the two send ticks, which were built around a single outbox rather than a
per-shop one.

**Secondary concern (not leakage):** `_for_every_shop` and `_materialize_all_shops`
iterate shops **serially inside one transaction** and commit once at the end
(`tasks.py:138`, `tasks.py:152`). At 1000 shops that is one very long
transaction; `MATERIALIZE_SOFT_LIMIT = 1500` seconds (`app.py:50`) is the
current ceiling, sized for one shop.

## M3 — The admin chat gate does not verify the group belongs to this shop

**File:** `src/gulbot/bot/middlewares.py:85-130` (`_is_shop_action`)

The gate lets a group update through on two conditions: the callback payload
starts with `ordadm:` (line 118), or the sender is in
`AdminOrder.entering_reject_reason` (line 130). **Neither checks
`shops.group_chat_id`.**

The real check lives one layer down, in the router:
`bot/routers/admin_orders.py:68-75` (`_acting_in_the_shops_own_chat`), which
calls `ping_targets(session, shop_id=shop_id)` and tests membership — and it is
enforced at both lines 192 and 250 before any transition. So **the order path is
correctly protected today.**

The gap is that the middleware's contract is "the shop acting on its own order
card" while what it actually verifies is "someone in *a* group tapped a button
with our prefix." Any future group-reachable handler that forgets the router-level
check inherits no protection from the gate.

---

# TIER 4 — LOW / COSMETIC

## L1 — Dev and ops scripts assume shop 1

| File | Line | Assumption |
|---|---|---|
| `scripts/live_browse.py` | 55 | `WHERE shop_id = 1` hardcoded in raw SQL |
| `scripts/live_browse.py` | 60, 106 | `list_bouquets(session, shop_id=1)` |
| `scripts/live_browse.py` | 70 | `build_dispatcher(..., shop_id=1, ...)` |
| `scripts/live_confirm.py` | 103-104 | `SELECT id, group_chat_id FROM shops ORDER BY id LIMIT 1` |
| `src/gulbot/cli/force_reminder.py` | 71-82 | `SELECT Shop` then filters by id **in Python**, not SQL |
| `src/gulbot/cli/force_reminder.py` | 101, 112, 116, 120 | Four `session.get()` PK fetches with no shop check; only a manual `occasion.customer_id != customer.id` guard at line 117 |
| `src/gulbot/cli/seed_aliases.py` | 18 | `SELECT Shop.id` — already loops over all shops |

`scripts/verify_group.py` is **not** in this tier — see **C4**.

## L2 — Shop-facing language is hardcoded

`sending/alerts.py:39, 53, 64, 93, 116` all default `lang: str = "uz"`, and
`worker/tasks.py:129-136` never overrides it. `Shop` has a `timezone` column
(`models/shop.py:43`) but **no language column**, so a fleet spanning more than
one language has no place to record a shop's preference.

## L3 — The seed CLI creates one named dev shop

`src/gulbot/cli/seed.py:16` — `DEV_SHOP_NAME = "Gulbot Dev Shop"`, looked up by
name at line 23. Idempotent for one shop; there is no provisioning path for
creating a shop with a token, channel and group as a unit.

## L4 — `build_dispatcher` already takes `shop_id`

Worth recording as a **positive**: `bot/factory.py:68-107` already accepts
`shop_id: int` and threads it into `CustomerMiddleware(shop_id)` (line 92),
which stamps `data["shop_id"]` on every update (`middlewares.py:194`). The
shadow sweep passes `shop_id=0` (`bot/shadow_sweep.py:239`) purely as a
placeholder for static analysis.

The dispatcher is therefore **already per-shop by construction.** Only the
process that builds it assumes there is one.

---

# Requested inventories

## Q1 — Tables with no shop/tenant concept

**None.** Full enumeration, from `migrations/versions/*.py` and
`src/gulbot/models/`:

| Table | `shop_id` column | How the tenant boundary is enforced |
|---|---|---|
| `shops` | *n/a — tenancy root* | `models/shop.py:40` |
| `customers` | **yes** (`customer.py:62-63`) | Plain FK to `shops.id` `ON DELETE RESTRICT`; `UNIQUE(shop_id, telegram_user_id)` (line 86); `UNIQUE(id, shop_id)` (line 91) to support children |
| `recipients` | **yes** (`recipient.py:40`) | Composite FK `(customer_id, shop_id)` (59-65); `UNIQUE(id, shop_id)` (58) |
| `occasions` | **yes** (`occasion.py:91`) | Composite FK `(customer_id, shop_id)` (118-125); `UNIQUE(id, shop_id)` (146) |
| `orders` | **yes** (`order.py:125`) | Three composite FKs — customer (192-194), recipient (195-199), product (208-212); `UNIQUE(shop_id, submit_token)` (191) |
| `order_reminders` | **yes** (`order.py:252`) | Composite FK `(order_id, shop_id)` `ON DELETE CASCADE` (278-280) |
| `products` | **yes** (`product.py:57-58`) | FK to `shops.id`; `UNIQUE(shop_id, channel_message_id)` (132); `UNIQUE(id, shop_id)` (129) |
| `product_hashtags` | **yes** (`product.py:179`) | Composite FK `(product_id, shop_id)` (188-192) |
| `hashtag_aliases` | **yes** (`product.py:216-217`) | FK to `shops.id` `ON DELETE CASCADE`; `UNIQUE(shop_id, alias_normalized)` (231) |
| `scheduled_notifications` | **yes** (`notification.py:81`) | Two composite FKs — occasion (106-110), customer (111-115) |
| `consent_events` | **yes** (`consent.py:49`) | Composite FK `(customer_id, shop_id)` (62-68) |
| `message_log` | **yes** (`message_log.py:73`) | Composite FK `(customer_id, shop_id)` (96-100) |

*(`alembic_version` is migration infrastructure and carries no tenant data.)*

**The composite-FK pattern is the important detail — and it has a hole.**
Because every child declares `FOREIGN KEY (parent_id, shop_id) REFERENCES
parent(id, shop_id)`, a row whose `shop_id` disagrees with a **non-NULL**
parent reference is unrepresentable in Postgres.

That guarantee does **not** extend to:

- **Nullable references.** `orders.product_id` and `orders.recipient_id` are
  nullable, and Postgres does not check a composite FK when any of its columns
  is NULL.
- **Snapshot / free-text columns.** `product_name_snapshot`,
  `price_uzs_snapshot`, `telegram_file_id_snapshot`, `recipient_name` and the
  delivery fields are plain values with no relationship to any shop.

The C3 reproduction wrote exactly such a row: a shop-B order carrying shop A's
product name, price and photo, with `product_id = NULL`, because
`create_order` falls back to the FSM draft's snapshot when the shop-scoped
product lookup misses (`services/orders.py:156-164`). So the FKs cap the damage
from a missed filter **on the id columns**, but they do not make cross-tenant
rows impossible, and any path that feeds another shop's data into a snapshot
field bypasses them entirely.

## Q2 — Queries needing a `shop_id` filter

Full mechanical scan: **114 distinct query statements** across 22 files in
`src/gulbot/` (AST-based, outermost-statement only, models excluded).

- **Already `shop_id`-scoped in the query text:** 100
- **Genuinely missing a filter that matters:** see **C1** and **C2**
- **Derived-scope, safe as called:** 14 → itemized in **M1** above

The two outbox selects (`dispatcher.py:156`, `order_pings.py:166`) are the only
two that select **across shops by design** rather than by omission.

## Q3 — Places assuming exactly one shop

| Location | Line | Assumption |
|---|---|---|
| `src/gulbot/bot/run.py` | 19-29 | `resolve_single_shop()` — raises on ≠ 1 shop |
| `src/gulbot/bot/run.py` | 38-42 | One resolved id, one dispatcher, one bot |
| `src/gulbot/config.py` | 45 | One `bot_token` for the process |
| `src/gulbot/config.py` | 84-89 | Production guard requires one global `BOT_TOKEN` |
| `src/gulbot/config.py` | 139-150 | `get_settings()` is `@lru_cache`d — config is process-global |
| `src/gulbot/sending/rate_limit.py` | 23-26 | "across the whole bot" budget |
| `src/gulbot/cli/seed.py` | 16, 23 | One dev shop, found by name |
| `scripts/live_browse.py` | 55, 60, 70, 106 | `shop_id = 1` |
| `scripts/live_confirm.py` | 103-104 | `ORDER BY id LIMIT 1` |
| `scripts/verify_group.py` | 108 | `UPDATE shops` with no `WHERE` |

**Not on this list, deliberately:** `models/shop.py` carries `channel_id`,
`group_chat_id` and `owner_telegram_ids` as ordinary per-shop columns, and the
Redis namespaces are already per-shop — `worker/debounce.py:92-93`
(`gulbot:album:{shop_id}:{media_group_id}`) and `sending/health.py:225`
(`{ALERT_KEY}:{shop_id}:{kind}`), the latter commented at line 66 as
"Namespaced by shop so a second shop cannot silence the [alerts]".

## Q4 — Global `Bot` / `Dispatcher` assumptions

**`Bot` — 9 construction sites, all via `build_bot()` (`factory.py:55-60`):**
listed in full under **H1**.

There is **no module-level `Bot` singleton**, and this is load-bearing:
`worker/tasks.py:75-79` documents that `build_bot()` is deliberately uncached
because an `aiohttp` session outliving a Celery task hands the next task a
client bound to a closed event loop. So the bot is already built fresh per
task — **the seam for a per-shop bot exists**, it is simply not parameterized.

**`Dispatcher` — 5 construction sites:**

| File | Line | Context |
|---|---|---|
| `src/gulbot/bot/run.py` | 41-43 | Production long-polling; `shop_id` from `resolve_single_shop()` |
| `src/gulbot/bot/shadow_sweep.py` | 239 | `shop_id=0`, static analysis only, no DB |
| `scripts/live_browse.py` | 70 | `shop_id=1` |
| `scripts/live_confirm.py` | 286 | Dev script |
| `scripts/live_order.py` | 107 | Dev script |

**Shared-state audit of the module:** the only module-level mutable globals in
`src/gulbot/worker/` and `src/gulbot/sending/` are `settings = get_settings()`
and `app = Celery(...)` (`worker/app.py:24, 53`). No global bot, no global
dispatcher, no global session.

**The genuinely shared runtime resources** a fleet would contend on:
one Celery `app` and broker (`app.py:53-58`), one Redis FSM database
(`config.py:42`), one Postgres connection pool, and the rate limiter (**H4**).

## Q5 — Celery tasks, shop-looping status

See **M2** for the full table. Summary: **3 of 5 already loop; 2 cannot.**

## Q6 — Tests asserting single-shop behaviour

**Suite size:** 866 test functions across 74 files. **45 files** touch a
`shop_id` / `shop` fixture.

### Already multi-shop — these are assets, not liabilities

`tests/conftest.py:169-183` provides a single `shop_id` fixture, but **10 test
files already create a second shop** and assert isolation:

| Test | File:line |
|---|---|
| `test_same_telegram_user_may_exist_in_two_shops` | `test_tenancy.py:58` |
| `test_another_shops_catalogue_is_not_listed` | `test_browse.py:273` |
| `test_another_shops_product_is_never_chosen` | `test_bouquet_attachment.py:392` |
| `test_a_hashtag_cannot_reference_another_shops_product` | `test_catalog_schema.py:79` |
| `test_consent_cannot_reference_another_shops_customer` | `test_consent.py:146` |
| `test_another_shops_backlog_is_not_this_shops_problem` | `test_health.py:247` |
| `test_a_notification_cannot_reference_another_shops_occasion` | `test_materializer.py:145` |
| `test_an_occasion_cannot_be_claimed_by_another_shop` | `test_occasion_dates.py:177` |
| `test_another_shops_customer_cannot_be_ordered_for` | `test_order_schema.py:187` |
| *(plus uniqueness-scope cases)* | `test_catalog_schema.py:155, 197` |

`test_album_debounce.py:161` (`test_the_keys_are_namespaced_per_shop`) already
covers the Redis side.

### Tests that would need to change or be duplicated

| Area | Files | Why |
|---|---|---|
| **Send-path tests** | `test_dispatcher.py` (38 tests), `test_order_pings.py` (43), `test_send_loop_lifetime.py`, `test_sending_scope.py` | These are the tests for **C1** and **C2**. All currently feed a single-shop outbox to a single transport. Each would need a two-shop variant asserting that shop A's rows go through shop A's bot. |
| **Bot-harness flow tests** | `test_bot_flow.py`, `test_order_flow.py` (37), `test_occasions_flow.py` (30), `test_browse.py` (24), `test_admin_orders.py` | `tests/bot_harness.py` builds one bot + one dispatcher (`make_bot()`, line 69). A second shop's conversation needs a second harness instance. |
| **FSM tests** | anything driving `bot_harness.feed()` through a multi-step flow | **C3** is invisible until two bots share a Redis FSM db. No current test can catch it. |
| **Config / production-guard tests** | `test_audit_production_guard.py` (asserts `BOT_TOKEN` in `REQUIRED`, line 62), `test_audit_secrets.py` | These encode "one global token" as a *requirement*. They will go red by design when the token moves per-shop, and that is the correct signal. |
| **Rate-limit tests** | `test_rate_limit.py` | Assert the 28/s global bucket (**H4**). Semantics change to per-bot. |
| **Startup** | *(none exist)* | `resolve_single_shop` has **no test at all** — worth noting that removing it breaks nothing in the suite, which means the suite will not tell you if the replacement is wrong. |

### Test-infrastructure notes

- `conftest.py:126-150` — one session-scoped migrated test database, fingerprinted.
  Not a tenancy issue, but every new per-shop fixture shares it.
- `conftest.py:152-167` — each test runs inside a rolled-back transaction, so
  creating N shops per test is cheap and leaves no residue.
- `tests/bot_harness.py:116` — a single negative chat id stands in for "the
  shop's catalogue channel." Relevant to **H3**.

---

## Two things that are better than the brief assumes

1. **The schema needs no tenancy migration.** All 12 tables carry `shop_id`, and
   the composite-FK pattern makes a mismatched **non-NULL** parent reference
   unrepresentable at the database level. Question 1's answer is an empty set.
   (It does not cover nullable references or snapshot columns — see the
   correction under Q1 and the C3 reproduction.)

2. **The service layer is already written for multiple shops.** Nearly every
   function in `src/gulbot/services/` takes `shop_id` as a keyword-only
   argument and filters on it. Three of five Celery tasks already loop over
   `SELECT Shop.id`. `build_dispatcher` already takes `shop_id`.

**The conversion is therefore not a schema problem or a query problem. It is a
process-and-transport problem**, concentrated in five files:

- `src/gulbot/bot/run.py` (one process → many)
- `src/gulbot/bot/factory.py` (one token, one FSM keyspace)
- `src/gulbot/sending/dispatcher.py` (global outbox drain)
- `src/gulbot/sending/order_pings.py` (global outbox drain)
- `src/gulbot/config.py` (process-global settings)

Plus one destructive dev script (`scripts/verify_group.py`) that should be
fixed before anyone runs it against a fleet database.

---

## Method and caveats

**How this was produced.** Every model, service, sending module, worker task,
middleware and router in `src/gulbot/` was read. The query inventory came from
an AST pass over all non-model modules, extracting outermost
`select`/`update`/`delete`/`insert`/`session.*` calls, then **every result was
verified by reading the surrounding code** — a text scan alone produces heavy
false positives here (see the note in **M1**).

**Version facts verified against the installed tree, not assumed:**
aiogram 3.31.0; `DefaultKeyBuilder.__init__` defaults `with_bot_id=False`
(`.venv/Lib/site-packages/aiogram/fsm/storage/base.py:58`); `build()` omits the
bot id unless that flag is set (lines 75-99).

**Caveats.**

- **The original audit was static.** **C3** has since been reproduced live
  (2026-09-26, see its section) and turned out worse than predicted. **H4**
  (rate limiting) still follows from the library source and the config and has
  not been reproduced.
- **`shops.channel_id` being unread (H3)** is asserted from a whole-tree grep
  returning a single definition-site hit. I am confident in it, but it is the
  kind of claim worth re-checking if any dynamic attribute access is added.
- Risk tiers weigh **cross-shop data leakage** highest, per the brief's
  question 7. A different weighting — availability first, say — would promote
  **H5** above **C4**.
