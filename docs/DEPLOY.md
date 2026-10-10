# Deploy runbook: from an empty VPS to a running Gulbot

One ordered path. Do the steps in order; each says why it is there, so none is
skipped as ritual. Started by the pre-deployment audit (pass 5) and rewritten
for CP18 as a single runbook. **The code side has been proven on the dev
machine; no step below has yet been run on a real server** -- the first deploy
is also this document's first run, so note anything that differs.

The files referred to are in the repo:

| File | Goes to |
|---|---|
| `deploy/gulbot.env.example` | `/etc/gulbot/gulbot.env`, filled in |
| `deploy/docker-compose.prod.yml` | used from the repo with `docker-compose.yml` |
| `deploy/systemd/*.service` | `/etc/systemd/system/` |
| `deploy/Caddyfile` | `/etc/caddy/Caddyfile`, hostname edited |

What runs where: **Postgres and Redis in Docker** (bound to 127.0.0.1);
**four Python processes under systemd** -- the bots, the Celery worker, Celery
beat, and the page server; **Caddy** in front of the page server for HTTPS.

## 0. Before you start: what only the owner can provide

- **A VPS**: Ubuntu 24.04 LTS, 2 vCPU / 2 GB RAM / 40 GB disk is enough for
  the pilot and the first tens of shops. Root SSH access.
- **A domain**, and one hostname for the pages and the panel, e.g.
  `pages.<your-domain>.uz`, with an `A` record (and `AAAA` if the server has
  IPv6) pointing at the VPS. Check: `nslookup pages.<your-domain>.uz`.
- **Two bot tokens from @BotFather**: the pilot shop's bot (`BOT_TOKEN`) and
  the **platform bot** (`PLATFORM_BOT_TOKEN`) -- a bot of its own, never a
  shop's. Shops onboarded later bring their own bots through the platform bot.
- **The admins' Telegram user ids** (`PLATFORM_ADMIN_TELEGRAM_IDS`): who may
  log into `/admin`. (@userinfobot shows your id.)

## 1. The server

```
apt update && apt -y upgrade
apt -y install ufw unattended-upgrades git ca-certificates curl
dpkg-reconfigure -plow unattended-upgrades
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw enable
adduser --system --group --home /opt/gulbot gulbot
```

Only 22, 80 and 443 are open. **Never open 5433, 6380 or 8088.**

Journald must not fill the disk: in `/etc/systemd/journald.conf` set
`SystemMaxUse=500M`, then `systemctl restart systemd-journald`.

## 2. Software

- **Docker** with the compose plugin (2.24+), from Docker's own apt
  repository (docs.docker.com/engine/install/ubuntu).
- **Python 3.11** exactly (`requires-python = ">=3.11,<3.12"`). Ubuntu 24.04
  ships 3.12, so: `add-apt-repository ppa:deadsnakes/ppa && apt -y install
  python3.11 python3.11-venv`.
- **Caddy** from its apt repository (caddyserver.com/docs/install).

## 3. The code

```
sudo -u gulbot git clone https://github.com/sabdur4hmonov/gumarketcontroller.git /opt/gulbot
cd /opt/gulbot
sudo -u gulbot python3.11 -m venv .venv
sudo -u gulbot .venv/bin/pip install -e .
sudo -u gulbot .venv/bin/python -c "import PIL, jinja2, aiogram; print('ok')"
```

That pulls in Pillow (CP17 photos) and Jinja2 (pages). **There must be no
`.env` file in `/opt/gulbot`**: docker compose and the app would both read it.

## 4. The production settings

```
mkdir -p /etc/gulbot
cp /opt/gulbot/deploy/gulbot.env.example /etc/gulbot/gulbot.env
chown root:gulbot /etc/gulbot/gulbot.env && chmod 0640 /etc/gulbot/gulbot.env
```

Fill it in. Every variable is commented there. The essentials:

- `ENVIRONMENT=production` -- arms the guard (step 6).
- `BOT_TOKEN`, `PLATFORM_BOT_TOKEN`, `PLATFORM_ADMIN_TELEGRAM_IDS`.
- `SHOP_TOKEN_ENCRYPTION_KEY`: generate once with the command in the file.
  **Back it up with the database password, never inside the database**: lose
  it and every stored shop token is unreadable. To rotate, set
  `<new>,<old>` (the first encrypts, all decrypt) and drop the old one only
  once every token has been re-stored.
- `POSTGRES_PASSWORD`: long and random. The guard refuses `gulbot`.
- `PUBLIC_BASE_URL=https://pages.<your-domain>.uz` (an origin: no path, no
  trailing slash). Until it is https, the bots answer the pages menu with
  "coming soon" and the platform bot sends no admin link -- deliberately.
- `WEB_TRUST_PROXY=true`, only because Caddy is in front.
- `BRAND_NAME`: the product's name in every bot text, the panel and the
  pages. Leave it unset for the working name until the brand is decided.

## 5. Postgres and Redis

```
cd /opt/gulbot
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml \
    --env-file /etc/gulbot/gulbot.env up -d --wait
```

The override takes the database credentials from the env file (a missing one
stops compose with its name) and binds both ports to 127.0.0.1. Data lives in
the named volumes `gulbot_pgdata` and `gulbot_redisdata`; Redis runs with
`appendonly yes`, so queued Celery work survives a restart.

Verify, per container -- it must show the limits, not `map[]`:

```
docker inspect -f "{{.HostConfig.LogConfig}}" gulbot-postgres
docker inspect -f "{{.HostConfig.LogConfig}}" gulbot-redis
ss -ltnp | grep -E ':5433|:6380'     # both on 127.0.0.1 only
```

Expected: `{json-file map[max-file:3 max-size:10m]}`. Docker applies logging
only when a container is CREATED: when upgrading a server whose containers
predate the limits, add `--force-recreate postgres redis` once (data survives).

## 6. STOP. Check the production guard with your own eyes.

Every process refuses to start (`ProductionConfigError: REFUSING TO START`,
followed by the name of every problem) unless `ENVIRONMENT=production` and
`BOT_TOKEN`, `POSTGRES_HOST`, `POSTGRES_DB` and `POSTGRES_PASSWORD` are real
environment variables, the password is not the dev one, and
`PLATFORM_ADMIN_TELEGRAM_IDS` is a usable list. That is the guard working: fix
the environment, never work around it.

**The guard cannot protect a process that never sets
`ENVIRONMENT=production`.** Without it the process is "local" and runs on dev
defaults, silently, by design. So check, with the exact environment the
services will get:

```
cd /opt/gulbot
sudo -u gulbot bash -c 'set -a; . /etc/gulbot/gulbot.env; set +a; \
  .venv/bin/python -c "from gulbot.config import get_settings; s = get_settings(); print(s.environment, s.postgres_db)"'
```

It must print `production` and your production database name. Anything else:
**stop**, fix the env file, check again. The systemd units read the same file
(`EnvironmentFile=`), so this is what they will see.

## 7. Migrations

```
sudo -u gulbot bash -c 'set -a; . /etc/gulbot/gulbot.env; set +a; \
  .venv/bin/alembic upgrade head && .venv/bin/alembic current && .venv/bin/alembic heads'
```

`current` and `heads` must print the same revision (`0956590ccce1` at CP19).
**A report of "applied" is not evidence** -- on this project it has been wrong
twice; read it here. Every migration is additive. Four DOWNGRADES change data,
because the old CHECKs cannot hold it -- back up before ever going below them:

| Below | What the downgrade does |
|---|---|
| `360f0694be06` | English-speaking customers become Uzbek |
| `c5a8e2d61f37` | Uzrnoma pages are deleted |
| `b996b9032869` | purged photo rows are deleted |
| `4b6e1d9c2a07`, the CP18 revisions and `0956590ccce1` | their columns and tables are dropped (CP19: every shop's staff list) |

## 8. The processes

```
cp /opt/gulbot/deploy/systemd/gulbot-*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now gulbot-web gulbot-worker gulbot-beat gulbot-bot
systemctl status 'gulbot-*'
```

Check each one's log (`journalctl -u gulbot-bot -n 50`):

- **bot**: `serving N shop(s); platform bot on; environment=production`, and
  the bot names on the `starting`/`polling` lines are the production bots.
- **worker**: the banner reads `concurrency: 2 (prefork)`. **Prefork, never
  solo**: the task time limits (`worker/app.py`) are enforced only by the
  prefork pool, and one hung task would otherwise hold the worker forever.
- **beat**: lists `send-due-reminders`, `send-order-pings`, `health-check`,
  `snapshot-shop-health`, `daily-summary`, `materialize-nightly`,
  `scrub-expired-pages`. **Run beat exactly once**, on one machine.
- **web**: `pages: serving on 127.0.0.1:8088 for https://pages... (environment=production)`.
  It writes no access log, on purpose: every page path is a secret.

## 9. HTTPS

Copy `deploy/Caddyfile` to `/etc/caddy/Caddyfile`, put your hostname in, and
`systemctl reload caddy`. Caddy obtains and renews the certificate itself. The
pages and `/admin` share the one hostname. **Do not add a `log` directive**
(see the file). Recommended: uncomment the block that lets only your own IP
addresses reach `/admin` at all.

## 10. Verify from outside the server

- `curl -I https://pages.<domain>/healthz` -> 200 with
  `Content-Security-Policy`, `X-Robots-Tag: noindex` and
  `Strict-Transport-Security`.
- `curl https://pages.<domain>/healthz/jobs` -> `ok` once the worker has run
  for two minutes (`stale: ...` names any job that is not finishing).
- `curl -I https://pages.<domain>/admin` -> 401.
- On a phone: `/demo/yesno`, `/demo/invite`, `/demo/apology/konvert`.
- In the pilot shop's bot: make a Ha/Yo'q page. The reply carries **Ochish**
  and **Ulashish** buttons (https only). Open it, press Ha: the "they said Ha"
  message arrives once. "Gul buyurtma qilish" opens THAT shop's bot.
- In the platform bot, from an admin id: `/admin` -> a link in your DM
  (preview off). Open it, press **Kirish** -> the panel. Within 10 minutes the
  shop shows a bot-health snapshot. From any other id, `/admin` does nothing.

## 11. The pilot shop's wiring

- **Its catalogue channel (CP-MT2, H3).** A shop with no `shops.channel_id`
  indexes nothing; the pilot shop predates onboarding and may not have one.
  Post anything with a photo in the channel; the bot logs
  `shop N has no channel_id ... set shops.channel_id = <id>`. Then:
  `UPDATE shops SET channel_id = <id> WHERE id = <pilot id> AND channel_id IS NULL;`
  Verify a new hashtagged post is `indexed`, not `ignored`.
- **Its own token.** The pilot may keep using `BOT_TOKEN`; the bot logs a
  WARNING each time. Storing its own token retires the fallback.
- **Its language** (`shops.lang`, default `uz`): `UPDATE shops SET lang = 'ru'
  WHERE id = ...` for a Russian-speaking shop.

## 12. The dead-man's switch (do it now, it takes five minutes)

If beat or the worker dies, nothing inside the deployment can say so -- the
health check is itself a beat task. `/healthz/jobs` is answered by the page
server, so it still answers when they are dead. Point an external uptime
monitor at `https://pages.<domain>/healthz/jobs` every 5 minutes, alerting on
anything but 200, to your phone. Also monitor `/healthz` (the page server
itself). See the owner's checklist for the choice of service.

## 13. Backups

- Nightly, as root: `docker exec gulbot-postgres pg_dump -U <user> -Fc <db> >
  /var/backups/gulbot/gulbot-$(date +%F).dump`, keep 14 days, and copy them
  OFF the server. Photos are in the database (CP17), so the dump grows with
  them; the nightly purge drops expired pages' photo bytes.
- The env file and above all `SHOP_TOKEN_ENCRYPTION_KEY`: in a password
  manager, never only on the server.
- Once, before going live: restore a dump into a scratch database and run
  `alembic current` against it. A backup never restored is a hope.

## 14. Upgrading to a new version

```
cd /opt/gulbot && sudo -u gulbot git pull
sudo -u gulbot .venv/bin/pip install -e .
# step 7: migrations, then current == heads
systemctl restart gulbot-worker gulbot-beat gulbot-bot gulbot-web
```

Read the new commits' notes in `docs/CHECKPOINTS.md` first: a step that needs
the deploy to finish it is recorded there and added here.

## 15. Know it is there, do not "fix" it at deploy time

| Bound | Value | Where |
|---|---|---|
| Bot API request timeout | 15 s | `bot/factory.py` |
| Circuit breakers | per shop; a fleet trip after 3 different shops fail in a row | `sending/transport.py` |
| Postgres `statement_timeout` | 30 s | `db/session.py` |
| Tick expiry / limits | 55 s; soft 240 s, hard 300 s | `worker/app.py` |
| Health snapshot | every 10 min, soft 240 s, never posts | `worker/app.py` |

**Do NOT set `idle_in_transaction_session_timeout`**: several paths correctly
hold a transaction open across a Telegram call.

## 16. Known gaps, accepted -- and what is still open

Recorded in `docs/AUDIT.md` section 3 and `docs/CHECKPOINTS.md`; the owner's
checklist gives a recommendation for each.

- **Dead-man's switch**: the hook exists since CP18 (`/healthz/jobs`, step
  12); the external monitor is the owner's to set up.
- **The health check shares the worker's queue** with the ticks. Bounded by
  the breakers and the time limits; a dedicated queue is real infrastructure
  for a benefit that bites only at volume.
- **Order-card permission**: by chat until a shop's owner makes a staff list
  with `/staff` on the platform bot (CP19). The admin panel's shop screen
  warns for every shop still without one.
- **One late duplicate reminder** is possible after a database loss (CP6's
  deliberate trade).
- **One long-poll per shop** in one process: right for tens of shops; at the
  hundreds, webhooks are the better shape (`bot/run.py`).
- **Page rate limits are in memory, per page-server process**: right for one
  page server; more than one would want them in Redis.
