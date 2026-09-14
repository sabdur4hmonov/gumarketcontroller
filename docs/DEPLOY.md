# Deploy runbook

Steps that a code change cannot take effect without, or that only the deploy
host can verify. Each one says why it is here, so it is not skipped as ritual.

Started by the pre-deployment audit, pass 5. Add to it whenever a fix needs the
deploy to finish it.

## 1. Before stopping anything

- **Migrations at head, checked, not assumed.** Compare the database with the
  code:

  ```
  alembic current
  alembic heads
  ```

  The two must print the same revision. A report of "applied" is not evidence:
  it has been wrong twice on this project already.

## 2. Recreate Postgres and Redis so log rotation applies

`docker-compose.yml` sets `max-size: 10m`, `max-file: 3` on both containers.
Docker applies a logging config **only when a container is created**. A
container already running keeps the unbounded default forever, and `docker
compose up -d` does not recreate a container just because its logging changed
on every Compose version.

Stop the bot and the worker first, then:

```
docker compose up -d --force-recreate postgres redis
```

Data survives: both use named volumes (`gulbot_pgdata`, `gulbot_redisdata`).
Redis runs with `appendonly yes`, so queued Celery work survives too.

Verify, per container. It must show the limits, not `map[]`:

```
docker inspect -f "{{.HostConfig.LogConfig}}" gulbot-postgres
docker inspect -f "{{.HostConfig.LogConfig}}" gulbot-redis
```

Expected: `{json-file map[max-file:3 max-size:10m]}`.

## 3. The worker runs PREFORK, never solo

Every task carries `soft_time_limit` and `time_limit` (`worker/app.py`). **Celery
enforces them only in the prefork pool.** The solo pool used on the Windows dev
box silently ignores them. A solo worker on the VPS would put back the defect
pass 5 found: one hung task holds the worker forever.

```
celery -A gulbot.worker.app worker --pool=prefork --loglevel=info
celery -A gulbot.worker.app beat --loglevel=info
```

Verify: the worker's startup banner reads `concurrency: N (prefork)`.

**Run beat exactly once.** Two beats enqueue every tick twice. That is safe,
because the claims make it idempotent, but it is wasted work, and it doubles
the expired-tick noise in the log.

## 4. Nothing to configure, but know it is there

These are in code and need no environment variable. Listed so nobody "fixes"
them at deploy time:

| Bound | Value | Where |
|---|---|---|
| Bot API request timeout | 15 s | `bot/factory.py` `TELEGRAM_REQUEST_TIMEOUT` |
| Circuit breaker | 3 consecutive network failures end a tick | `sending/transport.py` |
| Postgres `statement_timeout` on app connections | 30 s | `db/session.py` |
| Tick expiry | 55 s (health check 290 s) | `worker/app.py` |
| Tick time limits | soft 240 s, hard 300 s | `worker/app.py` |

**Do NOT set `idle_in_transaction_session_timeout`**, not in `postgresql.conf`
and not on the role. Several paths correctly hold a transaction open across a
Telegram call. A limit below the request timeout kills them mid-send.

## 5. Known gaps, accepted for the pilot

Written down in `docs/CHECKPOINTS.md` under *Deliberately not built*:

- **No dead-man's switch.** If beat dies, nothing says so. The health check is
  itself a beat task, and it alerts through Telegram. **Needed before a real
  production launch beyond the pilot.** For the pilot, whoever runs the deploy
  checks the worker log for `tick:` lines daily.
- **The health check shares the worker's queue** with the ticks.
