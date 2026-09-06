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

Note that the SAME full-suite loop turned up a real, reproducible flake in
`test_order_pings` (see the section above), which the isolated 100-run loop
never would have. Load-sensitive failures need the loaded workload.

## Time-dependent tests: never capture `now` before you insert the row

Found 2026-09-07, after a full-suite run on a loaded machine took 1818s instead
of the usual ~210s and one claim test failed:

```python
now = datetime.now(UTC)          # read 1
ping = await _ping(...)          # inserts due_at_utc = datetime.now(UTC), read 2
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
