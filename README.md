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

`check` is the build gate and must stay green on every commit. It exits non-zero
on any failure. CP2 adds the aiogram handler-shadowing sweep to it.

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
