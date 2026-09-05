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
op.execute("ALTER TABLE orders ADD CONSTRAINT ck_orders_total_positive "
           "CHECK (total > 0) NOT VALID")
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

## Tests

Real Postgres, never sqlite. Anything that must never regress goes in the
`check` target, which is the build gate.
