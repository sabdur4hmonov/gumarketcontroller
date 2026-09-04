# Gulbot

Telegram reminder + ordering bot for a flower shop in Uzbekistan. Customers save
recurring personal dates; the bot reminds them ahead of each one, suggests
bouquets from the shop's Telegram channel, takes the order, and hands it to the
shop's group chat.

Standalone project. It shares no code, database, or container with anything else
on this machine.

## Pinned environment decisions

| Decision | Value | Why |
|---|---|---|
| Repo root | `C:\dev\gulbot` | No spaces in the path; not inside a Telegram download folder |
| Python | 3.11 | 3.14 is the machine default but wheel coverage for Celery/asyncpg is unproven there |
| Postgres | host port **5433** | 5432 is taken by an unrelated project |
| Redis | host port **6380** | 6379 is taken by an unrelated project |
| Compose project | `gulbot` | Namespaces containers, network, and volumes |
| Timezone | `zoneinfo("Asia/Tashkent")` | Never a hardcoded `+5` |

**Not using WSL2.** Docker Desktop runs on the WSL2 backend, but the only distro
present is `docker-desktop` (Docker's internal utility VM), not a distro to
develop in. The bind-mount slowness that would justify moving into WSL2 does not
apply here anyway: Postgres and Redis use *named volumes*, and the app and test
suite run on the Windows host against `localhost`. The repo is never bind-mounted
into a container. Keep it that way.

## Redis logical databases

`0` Celery broker · `1` Celery results · `2` aiogram FSM · `15` tests.
Separated so a broker purge can never wipe live FSM state.

## Getting started

```
.\make.ps1 install   # 3.11 venv + dependencies
.\make.ps1 up        # Postgres + Redis, waits for healthy
.\make.ps1 check     # lint + typecheck + tests -- the gate
```

`make` is not installed on the Windows dev box, so `make.ps1` mirrors the
`Makefile`. The Makefile is canonical; keep both in sync.

## The `check` target

`check` is the build gate: `lint -> typecheck -> shadow -> test`. It stops at the
first failure and exits 1. It must stay green on every commit.

## The handler-shadowing sweep

Handler shadowing is a **registration-order** bug: aiogram dispatches to the
first handler whose filters pass, so a handler registered earlier can make a
later one unreachable. Ordering exists only at registration time, which is why
`make shadow` walks the **live dispatcher** after every router is included. A
static scan of the source cannot see registration order and would not catch it.

The sweep probes every `(state, trigger)` pair the bot can receive -- every
button label in every language, plus free text and `/start`, in every declared
FSM state and at state `None` -- and evaluates the real filter chain of every
registered handler in order. It reports:

* `DUPLICATE` -- two or more non-fallback handlers match the same probe.
* `FALLBACK_FIRST` -- a handler flagged `fallback` matches before a real one,
  i.e. a catch-all is swallowing input meant for a flow.

A fallback matching *after* the real handler is correct and is not reported.

It probes both `message` and `callback_query`: message triggers come from the
i18n catalog, callback triggers from each `CallbackData` factory's `samples()`.
Adding a button or an inline factory therefore extends the gate automatically --
there is no list to keep in sync.

Two rules keep it meaningful:

1. Every text-waiting handler carries a state gate (`StateFilter(None)` counts).
2. Intentional catch-alls declare `flags={"catch_all": True}`. That covers the
   global unknown-text fallback AND any state that waits for free text, since
   such a state accepts anything by design. A catch-all may be shadowed, and may
   precede another catch-all; it may not precede a *specific* handler.

Routers are built by factory functions, not module-level singletons: an aiogram
`Router` can only be attached to one `Dispatcher`, so a singleton makes a second
dispatcher -- in tests, or in the sweep -- impossible to build.

## Tests

Tests run against real Postgres, never sqlite: this project depends on
`FOR UPDATE SKIP LOCKED`, `ON CONFLICT`, and `pg_trgm`, and a fake would prove
nothing. Each test runs inside a transaction that is always rolled back, so the
suite needs no reset between runs. `tests/test_harness_isolation.py` fails if
that rollback ever breaks.

Tests marked `infra` need `.\make.ps1 up` first.

## Celery on Windows (decided at CP5)

Celery's default **prefork pool does not work on Windows**. The VPS runs prefork;
locally the worker needs `--pool=solo` or `--pool=threads`.

This matters for CP6's concurrency test. The test proves that two workers racing
the same due notification row produce exactly one send. A solo pool across **two
separate worker processes** still races correctly and the test is meaningful. A
solo pool inside **one process** does not race at all, and the test would pass
vacuously while proving nothing. CP5 must document the exact local invocation,
and CP6's race test must assert it is running against more than one process.

## Running the worker locally

```
celery -A gulbot.worker.app worker --pool=solo --loglevel=info
celery -A gulbot.worker.app beat --loglevel=info
```

`--pool=solo` because prefork does not work on Windows (see above). Beat runs
the send tick every minute and the materializer nightly at 03:00 Tashkent.

A solo pool in ONE process cannot race with itself, which is why
`tests/test_concurrency.py` starts two separate worker PROCESSES and asserts
their PIDs differ.

**The worker is not optional once the channel indexer is live.** Beat's two jobs
are periodic, but CP8 adds an event-driven one: `gulbot.finalize_album`, sent by
the bot process a few seconds after an album arrives. With no worker running, an
album's row is still created and merged correctly -- nothing is lost -- but it
stays provisional (`finalized_at IS NULL`), so it has no price, no tags, and
CP9's search will not find it. Single photo posts do not depend on the worker:
they are finalized inline by the handler.
