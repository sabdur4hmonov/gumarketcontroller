# Conventions

## Migrations are additive-only

Never edit a migration that has been applied anywhere but your own machine, and
never write a destructive `upgrade()`. Tightening a constraint is done in
**four steps**, which may span several releases:

1. **Add the column nullable** (or add the constraint as `NOT VALID`). Deploy.
   Old code keeps working because nothing requires the new shape yet.
2. **Backfill** in batches, in its own migration or a management command. Never
   in the same transaction as the DDL — a long backfill holding an
   `ACCESS EXCLUSIVE` lock takes the bot down.
3. **Add the constraint `NOT VALID`.** This is instant: it applies to new rows
   without scanning existing ones.
4. **`VALIDATE CONSTRAINT`** in a later migration. This scans, but takes only a
   `SHARE UPDATE EXCLUSIVE` lock, so writes continue.

```python
# Step 3
op.execute("ALTER TABLE orders ADD CONSTRAINT ck_orders_total_positive CHECK (total > 0) NOT VALID")
# Step 4, a later revision
op.execute("ALTER TABLE orders VALIDATE CONSTRAINT ck_orders_total_positive")
```

Dropping a column follows the same shape in reverse: stop writing it, ship,
*then* drop it — never in the release that stops using it.

## Any I/O client cached beyond one Celery task is a bug

Bitten once, at CP8, and audited across the whole codebase afterwards. Worth
stating as a rule because the broken version looks obviously correct.

`asyncio` clients bind to the event loop that opened them -- `redis.asyncio`
connections, `aiohttp.ClientSession`, asyncpg pools. Every Celery task here runs
`asyncio.run()`, which creates a loop and then CLOSES it. So a client that
outlives one task hands the NEXT task a dead socket:

```
RuntimeError: Event loop is closed
```

It fails on the SECOND task, never the first. **No test in this repo can catch
it by default**, because pytest-asyncio runs everything inside one event loop --
which is exactly why the 757-test suite was green while the debouncer was broken.

The rule: **a Celery task owns its clients for its own lifetime.** Either build
them inside the task (`build_bot()`, `build_session_factory()`) or take them from
an async context manager that closes them (`album_debouncer()`). Never a
module-level cache, never an `@lru_cache` on a factory that returns a client.
`get_settings()` is `@lru_cache`d and that is fine -- it holds no sockets.

To test it, write a SYNCHRONOUS test that calls `asyncio.run` twice and does real
I/O in both. See `tests/test_album_debounce.py` (Redis) and
`tests/test_send_loop_lifetime.py` (the Bot API, against a localhost stub).

Current status, all mutation-proven:

| Client | Owned by | Protected because |
|---|---|---|
| `redis.asyncio` (album debounce) | `album_debouncer()` | context manager closes it per call -- this is the one that broke |
| `aiohttp` (Bot API) | `_send_due_reminders` | `build_bot()` is uncached AND the session is closed in a `finally`; either alone suffices |
| asyncpg pool | `task_session_factory()` | a new engine per call, disposed in a `finally` |

`build_session_factory()` still does NOT dispose, and must not: `bot.run` holds
one engine for the life of the process, and disposing between updates would
throw the pool away every message. The distinction is the whole point --
`tests/test_task_engine_lifetime.py` pins both halves.

## What Alembic autogenerate does NOT catch

`test_models_match_migrations` runs autogenerate's comparison and asserts an
empty diff. It is a good guard, but it is not a complete one, and both gaps
found so far were found by a mutation test rather than by anyone reading the
code. They share a shape:

> **Autogenerate notices things APPEARING and DISAPPEARING. It is much weaker at
> noticing things CHANGING while keeping the same name.**

Assume that anything in this category needs a test that reads the real schema
out of Postgres and compares it to the model directly. Add to this list when the
next one turns up.

| Not caught | Found at | Closed by |
|---|---|---|
| Server defaults, unless `compare_server_default=True` | CP3.6 | enabled in `migrations/env.py` AND in the drift test's `MigrationContext` |
| CHECK constraint expression changes, when the constraint NAME is unchanged | CP6 | `tests/test_check_constraints.py`, which reads `pg_get_constraintdef` and compares literals |
| NUMERIC CHECK changes -- `> 0` to `>= 0` -- which the CP6 guard above SKIPS, because it compares quoted literals and a numeric check has none | CP10b | the same file's `test_every_numeric_check_compares_the_same_way_the_model_does`, which compares operators and bounds |

The CP10b one is worth dwelling on: **two guards agreed that nothing had
happened.** Autogenerate saw no diff because the constraint name had not
changed, and the CP6 guard skipped the constraint entirely because
`if not expected_literals: continue` -- a numeric check has no quoted values to
compare. Widening `ping_number > 0` to `>= 0` was therefore invisible to the
entire build. When you add a guard, check what it declines to look at.

Note also that Postgres does not store a CHECK as written: it stores the parsed
tree and prints it back canonically. `BETWEEN` comes back as `>= AND <=`, and
`IN (...)` as `= ANY (ARRAY[...])`. Any test comparing an expression to the
model must put the model through the same rewrites, or every `BETWEEN` in the
schema reports as drift.

Known to be shaky for the same reason, not yet bitten and not yet guarded:

* changing a column's type in place (`compare_type` helps, but is not exhaustive
  for parameterised types such as `String(64)` -> `String(128)`);
* index definition changes -- expression indexes, partial indexes, `WHERE`
  clauses -- when the index name does not change;
* foreign key `ON DELETE` / `ON UPDATE` action changes;
* anything expressed only in raw `op.execute(...)` SQL, which autogenerate has
  no model-side counterpart to compare against.

If you change one of those, write the direct assertion at the same time. Do not
rely on the diff being empty as evidence that the database agrees with you.

### The migration only runs correctly on a database that does not exist yet

This is now the third time autogenerate has produced a migration that runs
cleanly against a database which has already been migrated, and fails against a
genuinely empty one. It is a distinct failure from the CHANGING-vs-APPEARING
gap above, and it deserves its own name:

> **Autogenerate emits operations in MODEL order, not in DEPENDENCY order. The
> diff it computes is a set; the migration it writes is a sequence, and it does
> not sort that sequence.**

The symptom is always the same and always misleading: the migration passes for
the person who wrote it, because their database already contains the object the
new object depends on. It fails the first time it runs somewhere clean, which
is usually staging, or a colleague, or production.

| Occurrence | What was misordered |
|---|---|
| CP5 | `UNIQUE(recipients.id, shop_id)` emitted after the table whose FK targets it |
| CP8 | surfaced as a dev database silently a migration behind, so head "worked" |
| CP10 | same shape as CP5 -- the recipients UNIQUE after `orders`, and dropped BEFORE the tables on downgrade |

Note the downgrade half. Autogenerate reverses the operation list, which is the
right order for drops in most cases and the wrong one whenever the upgrade
order was already wrong. Fixing only the upgrade leaves a downgrade that fails,
and the round-trip test is the only thing that will tell you.

**The rule:** every migration is round-tripped `upgrade head` -> `downgrade` ->
`upgrade head` on a **throwaway database created for that run**, never on your
dev database and never on the test database. If it has ever been migrated
before, it cannot tell you whether the ordering is right.

### An edited migration does not re-apply

The sharper variant, found at CP10 and worth stating on its own because nothing
about it looks stale:

> **Alembic identifies a migration by its revision id, not by its contents.
> Editing a migration that has already been applied somewhere leaves that
> database holding the OLD definition, with `alembic current` reporting head
> and every test passing against a schema that no longer exists in the file.**

At CP10 the composite-FK `ON DELETE SET NULL` fix was made in a migration the
test database had already run. `upgrade head` was a no-op, the test database
kept the broken FK, and the failing test kept failing for a reason that had
already been fixed in the source.

**The rule:** whenever a committed migration is edited after being applied
anywhere, the local test database must be **rebuilt from scratch**, not
upgraded. Dropping it is the fix; there is no incremental one.

Since the rule is easy to state and easy to forget, `tests/conftest.py` now
enforces it mechanically. `migrated_test_database` writes a fingerprint of every
file in `migrations/versions/` into an `alembic_version_fingerprint` table, and
on the next run compares it. A mismatch -- a file edited, added, or removed --
drops the database and rebuilds it. It costs one `sha256` over a dozen small
files per session, it is self-healing rather than advisory, and it makes the
failure mode impossible rather than documented. `tests/test_migration_fingerprint.py`
proves the detection by mutating a file's bytes.

That is worth having even for two people. A rule that says "remember to drop
your database" is a rule that works right up until the one time it matters.

### Related: never address a migration by counting steps

A round-trip test that calls `command.downgrade(cfg, "-1")` is testing whatever
happens to be head TODAY. CP7's catalogue round-trip did exactly that, and it
started failing the moment CP8 added a migration on top -- the `-1` reached
CP8's migration, not CP7's, so the test asserted the wrong thing and only
LOOKED like a real regression.

Address the revision by name, or look up its `down_revision` through
`ScriptDirectory`, so the test keeps meaning what it said when it was written.

## Changing what a state VALUE means is a non-local change

Same shape as the autogenerate list above: **a change that is locally correct
and has invisible consequences somewhere else.** The value keeps its name, so
nothing that filters on it looks affected.

> **When a fix changes what a status or state VALUE means -- not adding a new
> transition, not adding a new check, but changing what an existing value
> implies -- grep for every place that value is filtered, compared, counted or
> assumed, and review each one before the change is considered done.**

The pre-deployment audit made `NotificationState.FAILED` retryable. Before, a
failed reminder was terminal; after, it is still a schedule. Every line of that
fix was correct and mutation-proved, and it still left three places assuming
the old meaning:

| Place | Assumed | Consequence | Found |
|---|---|---|---|
| `select_due_rows` | only PENDING is sendable | the original defect: a failed reminder was never retried | audit pass 1 |
| `block_customer` | only PENDING is still live | a customer who blocked the bot after a failed attempt burned into `dead_letter`, and the shop was told sending had FAILED | audit pass 3 |
| `RECONCILABLE_STATES` | FAILED is history | the nightly prune skipped a failed reminder for a deleted person, and the tick retried it | audit pass 3 |

The last two were found only because pass 3 happened to walk those chains --
not because anything pointed at them. The fix for the third is the structural
one: `RECONCILABLE_STATES = SENDABLE_STATES`, one definition instead of two
tuples kept in step by hand.

**How to do the sweep:** grep for the enum member AND its string literal
(`NotificationState.FAILED`, `"failed"`, `'failed'`), and for every tuple or
set that groups states. Read each hit and write down, in the commit, what it
assumes. A group of states defined in two places is the thing most likely to
drift; prefer defining one in terms of the other.

## Enumerations are `text` + `CHECK`, not Postgres `ENUM`

Native enums cannot be extended inside a normal transactional migration without
awkwardness, and values can never be removed. A `text` column with a named
`CHECK` constraint is extended by dropping and recreating one small constraint,
which is a plain additive migration. The Python-side `StrEnum` stays the source
of truth for valid values; the `CHECK` is the database's own guarantee.

Every such constraint is named, so tests can assert on the name and prove that
Postgres — not the ORM — rejected the row.

## Constraint naming

`db/base.py` sets a `naming_convention`. Do **not** pass an explicit `name=` to
`UniqueConstraint` or `ForeignKeyConstraint`: an explicit name overrides the
convention and produces inconsistent identifiers. `CheckConstraint` is the
exception — its convention interpolates the name you give it, so pass a short
descriptive one (`status_known`, not `ck_customers_status_known`).

## Tenancy

`shop_id` is on every table from day one, even with one shop.

`shops` is the tenancy root, so `customers.shop_id` is a plain FK. Everything
one level down (`occasions`, `orders`, `scheduled_notifications`, …) declares a
**composite** foreign key:

```python
ForeignKeyConstraint(["customer_id", "shop_id"], ["customers.id", "customers.shop_id"])
```

which is what `UNIQUE(customers.id, customers.shop_id)` exists to support. This
makes a cross-tenant row *unrepresentable* rather than merely discouraged. See
`tests/test_tenancy.py` for the proof.

## The guard that searched for a string its own helper could never produce

Found 2026-09-09, in `tests/test_order_scope.py`, live since CP10a.

`code_only()` strips comments and strings by tokenizing, then joins the
surviving tokens with `" "`. So `OrderStatus.CONFIRMED` comes out of it as
`OrderStatus . CONFIRMED`, with spaces around the dot.

`test_only_the_placed_status_is_ever_named` searched that output for
`f"OrderStatus.{status.name}"` -- the unspaced form. It could not match. Not
"did not happen to match": could not, for any input, ever. The test passed
continuously for three checkpoints while enforcing nothing, and it was cited by
name in two module docstrings as the thing keeping the order path honest.

It surfaced only because CP13 added a NEW test with the same bug, whose expected
answer was not empty -- it reported zero transition modules in a codebase that
had just gained one, which is a claim obviously false on its face. A guard whose
correct answer is "nothing" gives you no such signal.

**Then it got worse, which is the useful part.** Repairing the spacing made the
test fail -- correctly -- on `services/orders.py`, which has named
`OrderStatus.CANCELLED` and `REJECTED` since CP9 inside the daily-cap
`status.notin_([...])` filter. That is a READ. The fence's stated claim,
"the order path must not NAME a non-placed status", was therefore not merely
unenforced, it was **wrong**, and had it ever run it would have blocked correct
code. Two defects hiding each other: the claim was false, and the enforcement
was broken, so the suite stayed green.

The fence now classifies structurally instead of textually -- walk the AST, find
each `OrderStatus.X`, climb to the nearest construct that settles read from
write -- and unrecognised constructs count as WRITES, so a new shape trips the
alarm rather than quietly passing.

### How to not ship the next one

* **A guard whose passing condition is "found nothing" proves nothing by
  passing.** Mutate it once, at the time you write it, and watch it go red.
  Every fence in this repo now has a mutation recorded next to it for this
  reason.
* **Never hand-write the serialised form a helper produces.** Ask the helper.
  `names(status)` now exists solely so no one retypes the spacing, and its
  docstring says what went wrong the last time someone did.
* **When a repaired guard fails, suspect the claim before the code.** The first
  instinct was that CP13 had broken something. The code was right and the fence
  was wrong.

### And then the replacement over-claimed, which is the same mistake mirrored

The structural fence classified a status reference as a WRITE if it sat inside
any keyword argument. True while nothing but the database consumed a status.
False the moment CP13 added the two modules that TALK about outcomes:

* `routers/admin_orders.py` passes `status=OrderStatus.CONFIRMED` to the
  notifier and to the card renderer -- function arguments, not row values.
* `services/order_notify.py` uses the statuses as DICT KEYS, mapping an outcome
  to the copy the customer reads.

Neither writes anything, and both tripped the fence. That IS the fence working
-- it stopped the change and demanded a reason -- but the reason turned out to
be that "keyword argument" had only ever been a **proxy** for "database write",
and the proxy had drifted away from the thing it stood for.

The fix was not a cleverer proxy. It was to split the claim into the two it had
been conflating, and state each one directly:

| Claim | How it is enforced | What it stops |
|---|---|---|
| the MECHANISM | only `order_status.py` may `update(Order)` | nothing can transition what nothing updates |
| the BLAST RADIUS | the modules naming a non-placed status are a named list | a fifth module joining is a decision, not a slip |
| the CUSTOMER PATH | `services/orders.py` and `routers/orders.py` write only `placed` | a customer flow that could accept its own order |

Three narrow claims that are each exactly true beat one broad claim that is
approximately true. A bypass now has to fool two independent checks -- one reads
names, the other reads the operation.

**The general rule:** when a fence fires on code you believe is correct, the
question is not "how do I let this through". It is "what was this fence
actually trying to say, and does it still say it".

## The one unexplained failure: test_concurrency, 2026-09-06

Recorded rather than closed, because it has not reproduced and pretending
otherwise would be worse than saying so.

`test_two_processes_racing_a_merged_group_send_it_once_and_whole` failed once,
in a full-suite run, on `assert len(rows) == 3` with two rows present and both
`sent`. Since then:

| Attempt | Result |
|---|---|
| the file alone, 100 consecutive runs | 100 passes, 34-50s each |
| full suite, 6 runs (201s-1818s each) | the merged-group test passed every time |
| leftover due rows planted deliberately, to test the leading hypothesis | passed |

The leading hypothesis was pollution: `tests/worker_race.py` runs the real tick,
which is GLOBAL by design and picks up every due row in the database, so a row
left committed by another test is part of this test's world whether it wants to
be or not. Planting exactly such a row did not reproduce it.

Nor does anything in the send path explain a MISSING row: `run_tick` marks and
updates, and the only `DELETE FROM scheduled_notifications` in the codebase is
the materializer's prune, which the race worker never calls.

What exists now, so the next occurrence is not another dead end: an assertion
BEFORE the workers start, which separates "the fixture never planted three rows"
from "a row vanished while the tick ran" -- the bare count could not -- and a
`snapshot()` helper dumping this shop's rows, its `message_log`, and rows
belonging to other shops.

### A second occurrence, 2026-09-09 -- and this one was legible

A different test in the same file, `test_two_processes_racing_one_row_send_exactly_once`,
failed once in a full-suite run. The diagnostics added above did their job: the
failure was readable on sight, and it was **not the invariant failing**.

It failed at the `worker {marker} failed` branch -- the spawned subprocess exited
non-zero -- with `asyncpg` raising `TimeoutError` out of `connection.py:connect`.
The worker never reached the claim, never reached the transport, and sent
nothing. "Send exactly once" was never in question; a process could not open a
database connection.

Checked at the time: `max_connections` is 100 and exactly 2 were in use. So this
is not pool exhaustion. The engine in `db/session.py` sets no explicit connect
timeout, so asyncpg's default applies, and the two workers are deliberately
spawned as simultaneous fresh OS processes -- each paying Windows process start,
a full app import, and a connection through Docker Desktop's port proxy on 5433.

Re-run three times in isolation immediately afterwards: three passes.

**Why this is worth writing down rather than shrugging at.** A red suite whose
failure is "TimeoutError connecting" and a red suite whose failure is "the
message was sent twice" mean completely different things, and before CP10b's
diagnostics this test could only say `assert len(rows) == 3`. The lesson is not
about Postgres. It is that a concurrency test must fail in a way that
distinguishes *the invariant broke* from *the harness could not run*, or every
failure costs a day and settles nothing.

Still open: whether the 2026-09-06 occurrence had the same infrastructural
cause. It failed differently and left no stderr, so the honest answer is that
nobody knows.

Note that the SAME full-suite loop turned up a real, reproducible flake in
`test_order_pings` (see the section above), which the isolated 100-run loop
never would have. Load-sensitive failures need the loaded workload.

## Time-dependent tests: never capture `now` before you insert the row

Found 2026-09-07, after a full-suite run on a loaded machine took 1818s instead
of the usual ~210s and one claim test failed:

```python
now = datetime.now(UTC)  # read 1
ping = await _ping(...)  # inserts due_at_utc = datetime.now(UTC), read 2
claimed = await claim_due_pings(session, now_utc=now)
```

`due_at_utc` is strictly LATER than `now`, so `due_at_utc <= now_utc` is false
and the row is not due at all. The claim logic under test never runs.

It passes almost always because Windows' default clock granularity is about
15.6ms, so the two reads usually return the same value. It fails when the
machine is loaded enough for them to straddle a tick. Reproduced deterministically
by putting `await asyncio.sleep(0.05)` between them.

**The asymmetry is what makes it nasty.** In the straddle window a test that
asserts something WAS claimed fails loudly, and a test that asserts nothing was
claimed passes -- for the wrong reason, because the row was not due rather than
because the claim was fresh. Only the first kind ever reported anything, so the
second kind was quietly untested in exactly the runs that mattered.

**The rule:** a row a test expects to be due must be given a due time explicitly
in the past relative to the `now` the test passes in. Do not rely on two clock
reads being equal. `tests/test_order_pings.py::_ping` now defaults to one second
ago for that reason, so a caller cannot fall into it by omission.

## Tests

Real Postgres, never sqlite. Anything that must never regress goes in the
`check` target, which is the build gate.
