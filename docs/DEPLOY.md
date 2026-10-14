# Deploy runbook: from an empty VPS to a running Gulbot

One ordered path. Do the steps in order; each says why it is there, so none is
skipped as ritual. Started by the pre-deployment audit (pass 5) and rewritten
for CP18 as a single runbook. **No step below has yet been run on a real
server.** CP21 rehearsed steps 1-10 and 13 on a stand-in Ubuntu 24.04 server
in local containers (`deploy/rehearsal/rehearse.sh`; transcript in
`docs/rehearsal/cp21-transcript.txt`) and fixed what it found; what a
container cannot show -- the firewall, real DNS and certificates, Telegram
from a VPS -- the first deploy still is the first run of, so note anything
that differs.

The files referred to are in the repo:

| File | Goes to |
|---|---|
| `deploy/gulbot.env.example` | `/etc/gulbot/gulbot.env`, filled in |
| `deploy/docker-compose.prod.yml` | used from the repo with `docker-compose.yml` |
| `deploy/systemd/*.service` | `/etc/systemd/system/` |
| `deploy/Caddyfile` | `/etc/caddy/Caddyfile`, hostname edited |
| `deploy/backup/gulbot-backup.{service,timer}` | `/etc/systemd/system/` (step 13) |
| `deploy/backup/*.sh` | run from the repo (step 13) |
| `deploy/rehearsal/` | not installed: the local staging rehearsal of this runbook (CP21) |

What runs where: **Postgres and Redis in Docker** (bound to 127.0.0.1);
**four Python processes under systemd** -- the bots, the Celery worker, Celery
beat, and the page server; **Caddy** in front of the page server for HTTPS.

## 0. Before you start: what only the owner can provide

- **A VPS**: Ubuntu 24.04 LTS, 2 vCPU / 4 GB RAM (8 GB preferred with local STT) / 40 GB disk is enough for
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
  **Back it up OUTSIDE the server** (password manager), with the database
  password, never inside the database and never only on this server: lose
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

`current` and `heads` must print the same revision (`f23d7c2e5a41` at CP23).
**A report of "applied" is not evidence** -- on this project it has been wrong
twice; read it here. Every migration is additive. Five DOWNGRADES change data,
because the old CHECKs cannot hold it -- back up before ever going below them:

| Below | What the downgrade does |
|---|---|
| `360f0694be06` | English-speaking customers become Uzbek |
| `c5a8e2d61f37` | Uzrnoma pages are deleted |
| `b996b9032869` | purged photo rows are deleted |
| `4b6e1d9c2a07`, the CP18 revisions, `0956590ccce1`, `3c8e5a1f7d20` | their columns and tables are dropped (CP19: every shop's staff list; CP20: the shop panel's logins and audit log) |
| `8f2d6c41b9a3` | holiday reminder rows and holiday consent are deleted, holiday orders lose their source |
| `9c22e4d87b10`, `c23a1f5e7b90`, `d23b4e8f1a26` | announcement drafts and favourite styles are dropped (CP22; CP23: flower-template choices, per-flower favourites, Instagram connections and story uploads) |
| `e23c5a9d0b37` | every shop's learned speech corrections are dropped; posts deleted from "Mening e'lonlarim" become 'published' rows again (their channel posts stay deleted) |
| `f23d7c2e5a41` | every shop's logo is dropped |

## 7b. The pilot shop (a fresh database has none)

```
sudo -u gulbot bash -c 'set -a; . /etc/gulbot/gulbot.env; set +a; \
  .venv/bin/python -m gulbot.cli.seed --name "<the shop name>" \
    --owner-id <owner telegram id> --store-bot-token'
```

It prints `shop id=1 ... created` and `its own bot: id=<bot id> stored,
encrypted`. `--store-bot-token` makes the `BOT_TOKEN` of the env file the
shop's OWN bot, encrypted with `SHOP_TOKEN_ENCRYPTION_KEY` exactly as the
platform bot's onboarding stores one; the token is read from the environment,
never typed on the command line. Safe to rerun ("already stored"); it never
overwrites a shop's bot. Add `--channel-id` / `--group-chat-id` now if you
know them (step 11 shows how to find them).

**Why this step exists (CP21).** The staging rehearsal found that without it
the pilot has no bot on a fresh server: `BOT_TOKEN` alone serves only a shop
that existed before per-shop tokens, which a fresh database does not have. The
bot then refuses to start ("no shop has a usable bot") and systemd restarts it
every ten seconds. Shops after the pilot onboard through the platform bot.

Then the hashtag aliases (роза/rose -> atirgul, lola -> tyulpan, ...), which
let a customer's search find a shop's posts in any script and which every
flower template's hashtags resolve through (CP23):

```
sudo -u gulbot bash -c 'set -a; . /etc/gulbot/gulbot.env; set +a; \
  .venv/bin/python -m gulbot.cli.seed_aliases'
```

It prints one line per shop and is safe to rerun: it never overwrites an
alias someone edited by hand. **Rerun it after onboarding a new shop and
after every upgrade** (step 14) -- nothing seeds a shop's aliases on its own.

## 8. The processes

```
cp /opt/gulbot/deploy/systemd/gulbot-*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now gulbot-web gulbot-worker gulbot-beat gulbot-bot
systemctl status 'gulbot-*'
systemctl show -p NRestarts gulbot-bot gulbot-worker gulbot-beat gulbot-web   # a minute later: all 0
```

"active" at one instant can hide a crash loop (`Restart=always` brings a
failing unit back every five seconds): the restart counts must stay 0.
Check each one's log (`journalctl -u gulbot-bot -n 50`):

- **bot**: `serving N shop(s); platform bot on; environment=production`, and
  the bot names on the `starting`/`polling` lines are the production bots.
- **worker**: the banner reads `concurrency: 2 (prefork)`. **Prefork, never
  solo**: the task time limits (`worker/app.py`) are enforced only by the
  prefork pool, and one hung task would otherwise hold the worker forever.
- **beat**: lists `send-due-reminders`, `send-order-pings`, `health-check`,
  `snapshot-shop-health`, `daily-summary`, `materialize-nightly`,
  `scrub-expired-pages`, `instagram-upkeep` (CP23; a no-op while Instagram
  publishing is off). **Run beat exactly once**, on one machine.
- **web**: `pages: serving on 127.0.0.1:8088 for https://pages... (environment=production)`.
  It writes no access log, on purpose: every page path is a secret.

## 9. HTTPS

Copy `deploy/Caddyfile` to `/etc/caddy/Caddyfile`, put your hostname in, and
`systemctl reload caddy`. Caddy obtains and renews the certificate itself. The
pages, `/admin` and the shop owners' `/shop` (CP20) share the one hostname.
**Do not add a `log` directive** (see the file). Recommended: uncomment the
block that lets only your own IP addresses reach `/admin` at all. Never put
`/shop` behind that allow-list: shop owners log in from their own phones.

## 10. Verify from outside the server

- `curl -I https://pages.<domain>/healthz` -> 200 with
  `Content-Security-Policy`, `X-Robots-Tag: noindex` and
  `Strict-Transport-Security`.
- `curl https://pages.<domain>/healthz/jobs` -> `ok` once the worker has run
  for two minutes (`stale: ...` names any job that is not finishing).
- `curl -I https://pages.<domain>/admin` -> 401, and `/shop` -> 401 too.
- On a phone: `/demo/yesno`, `/demo/invite`, `/demo/apology/konvert`.
- In the pilot shop's bot: make a Ha/Yo'q page. The reply carries **Ochish**
  and **Ulashish** buttons (https only). Open it, press Ha: the "they said Ha"
  message arrives once. "Gul buyurtma qilish" opens THAT shop's bot.
- In the platform bot, from an admin id: `/admin` -> a link in your DM
  (preview off). Open it, press **Kirish** -> the panel. Within 10 minutes the
  shop shows a bot-health snapshot. From any other id, `/admin` does nothing.

## 11. The pilot shop's wiring

- **Its catalogue channel (CP-MT2, H3).** A shop with no `shops.channel_id`
  indexes nothing; a pilot seeded without `--channel-id` has none.
  Post anything with a photo in the channel; the bot logs
  `shop N has no channel_id ... set shops.channel_id = <id>`. Then:
  `UPDATE shops SET channel_id = <id> WHERE id = <pilot id> AND channel_id IS NULL;`
  Verify a new hashtagged post is `indexed`, not `ignored`.
- **Its own token.** Stored in step 7b. (Only a database that predates
  per-shop tokens has a shop allowed to borrow `BOT_TOKEN` without storing
  it; the bot logs a WARNING for each such use, and step 7b's command retires
  it there too.)
- **Its language** (`shops.lang`, default `uz`): `UPDATE shops SET lang = 'ru'
  WHERE id = ...` for a Russian-speaking shop.
- **Its logo (CP23).** The owner sends `/logo` to the shop's bot, then the logo
  -- a PNG sent as a FILE keeps its transparency. From then on it is on every
  photo of every announcement and on every story image; it can be switched
  off per announcement ("🏷 Logo") and removed with `/logo` -> "🗑".

## 12. The dead-man's switch (do it now, it takes five minutes)

If beat or the worker dies, nothing inside the deployment can say so -- the
health check is itself a beat task. `/healthz/jobs` is answered by the page
server, so it still answers when they are dead. Point an external uptime
monitor at `https://pages.<domain>/healthz/jobs` every 5 minutes, alerting on
anything but 200, to your phone. Also monitor `/healthz` (the page server
itself). See the owner's checklist for the choice of service.

## 13. Backups

**First, before anything else: `SHOP_TOKEN_ENCRYPTION_KEY` is backed up
OUTSIDE the server** -- in your password manager, with the rest of the env
file. Never only on the server, never next to the dumps, never in the
database. A dump without its key restores every shop with an unreadable bot
token; a server lost with the only copy of the key loses every shop's bot.

The nightly backup (CP21; `deploy/backup/`):

```
cp /opt/gulbot/deploy/backup/gulbot-backup.service \
   /opt/gulbot/deploy/backup/gulbot-backup.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now gulbot-backup.timer
systemctl list-timers gulbot-backup.timer     # next run: 03:10 Tashkent
systemctl start gulbot-backup.service         # one now, to see it work
journalctl -u gulbot-backup -n 5              # "backup: /var/backups/gulbot/..."
```

Each run writes `/var/backups/gulbot/gulbot-<UTC stamp>.dump` (pg_dump custom
format) and `.counts` (every table's row count), both root-only, and deletes
those older than 14 days (`KEEP_DAYS`). The counts are taken in the very
snapshot that was dumped, so they are exact on a busy database: that is what
makes the restore drill a real comparison. 03:10 is after the 03:00
materializer and before the 03:30 page scrub. Photos are in the database
(CP17), so the dump grows with them; the nightly purge drops expired pages'
photo bytes.

**Copy the dumps OFF the server** (rsync/rclone/scp to another machine,
nightly). A backup on the disk it protects is not a backup. That copy is
yours to set up; the script deliberately holds no credentials for it.

**The restore drill, once before going live and after any Postgres upgrade:**

```
/opt/gulbot/deploy/backup/restore-drill.sh /var/backups/gulbot/gulbot-<stamp>.dump
```

It creates a throwaway database beside the live one, restores into it,
compares every table's row count with the backup's own counts, prints the
restored and live alembic revisions, and drops the throwaway database. It
exits 0 and prints `RESTORE DRILL PASS` only when every table matches. A
backup never restored is a hope.

**Restoring for real** (the drill rehearses this): stop the four units (plus `gulbot-stt` if installed),
`docker exec -i gulbot-postgres pg_restore --clean --if-exists --no-owner
-U <user> -d <db> < <dump>`, put the env file back from the password manager
(the same `SHOP_TOKEN_ENCRYPTION_KEY`), run step 7, start the units.

## 14. Upgrading to a new version

```
cd /opt/gulbot && sudo -u gulbot git pull
sudo -u gulbot .venv/bin/pip install -e .
# step 7: migrations, then current == heads
# step 7b's last command: the alias fixture may have grown (CP23 did)
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

## 17. CP22 local voice announcements

The bot processes no speech on its event loop. Install a separate speech
worker, even when it runs on the same server. The normal worker consumes only
`celery`; `gulbot-stt.service` consumes only `stt`, prefork concurrency **1**,
prefetch **1**, soft/hard limits **360/420 seconds**. Windows `solo` ignores
those limits; use Linux prefork in production. The normal-queue error callback
edits the acknowledgement after a killed speech task. Owners can type a text
description to supersede a queued/failed voice job at any time.

Plan **2 vCPU / 4 GiB RAM minimum, 8 GiB preferred** for small Whisper and the
rest of this stack. This replaces the earlier 2 GiB pilot recommendation when
local Whisper is enabled. Generic small int8 upstream uses about 1.48 GB for
recognition; budget **1.5–2.5 GiB for the speech worker** plus database, other
workers, bots and OS. Uzbek fine-tune RAM is a planning estimate until the
owner's bouquet recordings are measured. Vosk small Uzbek is a lighter option:
49 MB archive, roughly **0.3–0.6 GiB** recognition budget; verify domain accuracy
before switching. CPU latency depends on recording/model: the read-only
editor-pro results in `CP22_DESIGN.md` are supporting evidence, not a bouquet
accuracy benchmark. Do not promise real-time recognition from those results.

```
apt install ffmpeg
sudo -u gulbot .venv/bin/pip install -e '.[stt]'
free -h     # before any model download/load or benchmark; one heavy job at a time
```

Models are deliberately **never downloaded automatically**. Store an explicitly
reviewed, commercial-use-licensed model under `/opt/gulbot/models/` and set:

```
STT_ENGINE=faster-whisper
STT_MODEL_PATH=/opt/gulbot/models/whisper-small-uz-v1-ct2
STT_CPU_THREADS=2
STT_AUDIO_DIR=/run/gulbot-stt
STT_GEMINI_ENABLED=false
```

Provisional model: `yuldashev222/whisper-small-uz-v1-ct2` (Apache-2.0;
revision `2a14636265bdb33c58cbb7c5b16447882c6676f4`), about **972 MB** downloaded
including float32 weights/config/tokenizer; CPU execution converts to int8.
Keep its publisher/model licence and model card beside the installation.
Generic Systran small MIT alternative: about **486 MB**. Low-memory baseline:
`vosk-model-small-uz-0.22`, Apache-2.0, **49 MB** zip; unpack then choose
`STT_ENGINE=vosk`. The independent Apache-2.0 `navai-uz/whisper-small-uzbek`
candidate needs conversion to CTranslate2; budget about **0.98 GB source** plus
estimated **250–350 MB int8 conversion** and extra conversion RAM. Model cards,
provenance, licence scope and exact downloads are linked in the design.

Copy the new unit, then start it with the other services:

```
cp deploy/systemd/gulbot-stt.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now gulbot-stt
systemctl restart gulbot-worker
journalctl -u gulbot-stt -n 30
```

Add `gulbot-stt` to stop/start/restart commands for upgrades/restores. Audio is
downloaded only in the speech worker's private temporary directory and deleted
**before** results are stored or sent, including conversion/recognition errors.
A separate small guardian starts before download and removes that task's
directory within about **0.5 seconds** after the child dies or reaches its
deadline. It only deletes `cp22-audio-*` direct children of `STT_AUDIO_DIR`.
`/run` keeps temporary voice off durable disks; systemd removes the runtime
directory when the service stops. Never back up this directory. No audio or
voice file IDs are written to the announcement tables.

Deterministic tests use fake speech; real recognition is a separate command:

```
.venv/bin/python scripts/benchmark_stt.py --manifest docs/cp22-samples.json \
  --engine faster-whisper --model /opt/gulbot/models/whisper-small-uz-v1-ct2 \
  --output /tmp/cp22-whisper-benchmark.json
```

The ten prompts currently have `audio_path: null`, `reference_text: null`.
Supply the owner's recordings **outside Git** and fill those fields. The script
reports missing recordings and exits 2 without loading a model; with recordings
it measures load/transcription latency, peak process RAM, exact flower/count/
price/colour accuracy, and WER when a verbatim reference is supplied. Run serially
for each local engine/model. Never turn text-only prompt results into STT claims.

Gemini fallback is optional and off. It requires all three explicit settings:
`STT_GEMINI_ENABLED=true`, `GEMINI_API_KEY`, `STT_GEMINI_MODEL=<reviewed model>`.
Only a failed local recognition invokes it. No model ID is silently selected
because free-tier models, availability, limits and terms can change. Check the
[official audio docs](https://ai.google.dev/gemini-api/docs/audio) and pricing
before opting in. Enabling it sends voice to Google; it is not the local engine.
Keys remain SecretStr and are sent in a header, never URLs or task arguments.

The `u2b3k/uz-hunspell` dictionaries are unmodified GPL-3.0 data with licence,
source `.dic/.aff`, readme and pinned revision/hash manifest under
`announcements/assets/dictionary/`. Commercial use is allowed under that
licence; retain its notices/licence and corresponding source when distributing
the dictionary or derived data. The corrector deliberately handles roots with
unique one-edit suggestions; it does not claim full Hunspell affix processing.
Domain and number spans are protected; all changes and uncertainty appear in
review. Noto Sans fonts and their OFL licence/provenance are included separately.

Publication commits a claim before the Bot API call, persists its returned
messages before indexing, then uses CP8 `ingest_post`/`finalize_product`.
Successful callbacks can retry indexing without reposting. A timeout/crash can
leave `ambiguous`/`publishing`: inspect the channel before a new announcement;
there is deliberately no blind retry. Every edit invalidates confirmation and
preview; “Joylash” accepts only the current confirmed preview. Preview Telegram
file IDs are used for the final post, so the first-photo overlay is identical.

## 18. Instagram story publishing (CP23) -- built, OFF until you enable it

Without any of this, every published announcement already offers
"📸 Instagram istoriya": a 1080x1920 story image the owner saves and shares
from the phone. Nothing below is needed for that.

Automatic publishing (the "📲 Instagram'ga joylash" button) uses Meta's
official **Instagram API with Instagram Login**. It stays off until
`INSTAGRAM_PUBLISHING_ENABLED=true`, and the production guard refuses that
switch without an app id, an app secret and an https `PUBLIC_BASE_URL`.

**What only you can do, in this order:**

1. **A Meta developer account** at developers.facebook.com, and a **Meta app**
   of type *Business*. Add the product **Instagram** -> *API setup with
   Instagram login*.
2. **Business Verification** of your business in Meta Business Manager
   (company documents; it can take days). Advanced access requires it.
3. In the app's Instagram settings:
   - **Valid OAuth redirect URI:** `https://pages.<your-domain>/ig/callback`
     -- exactly, https, no trailing slash.
   - Copy the **Instagram app ID** -> `INSTAGRAM_APP_ID` and the **Instagram
     app secret** -> `INSTAGRAM_APP_SECRET` in `/etc/gulbot/gulbot.env`. The
     secret is a secret: password manager, never a chat.
4. **App Review** for the permissions `instagram_business_basic` and
   `instagram_business_content_publish`, with a screencast of the flow
   (owner connects in `/shop/instagram`; a story is published from the bot).
   Until approved, only the Instagram accounts you add as **testers** of the
   app can connect -- enough to try it on your own shop first.
5. Each shop's Instagram account must be a **Business or Creator** account.
6. Set `INSTAGRAM_PUBLISHING_ENABLED=true`, run step 6's check, then
   `systemctl restart gulbot-web gulbot-worker gulbot-beat gulbot-bot`.
7. Test: an owner opens `/shop/instagram`, presses **Instagram'ni ulash**,
   follows the link, allows; the page says "Instagram ulandi". In the bot,
   publish an announcement -> "📸 Instagram istoriya" -> a layout ->
   "📲 Instagram'ga joylash" -> within a minute "✅ Istoriya Instagram'ga
   joylandi" and the story is on the account.

**How it works, so you know what to look at.** The story image is stored
for 15 minutes behind `https://pages.<domain>/ig/<32 random bytes>.jpg` (only
a hash is stored); Meta fetches it from there, so Caddy must serve `/ig/`
publicly -- do not put it behind the `/admin` allow-list. The worker creates
a STORIES container, polls it, publishes it, then wipes the image (the URL
404s from then on) and tells the author the outcome in the shop's language.
Meta's own publishing limit is asked first, and a shop may queue at most 25
stories a day. Tokens are stored encrypted with `SHOP_TOKEN_ENCRYPTION_KEY`
(so step 13's backup rule covers them too), refreshed daily at 04:10 when
within 15 days of their 60-day end; a token Meta rejects retires the
connection and the owner is asked to reconnect. Tokens never appear in a
log. The endpoint version is `INSTAGRAM_GRAPH_VERSION` (default `v21.0`);
Meta retires versions about two years after release -- raise it then.

**Not verified against Meta.** Everything is tested against a fake Graph
server that answers the documented endpoints; no real Meta call was made
from this project. The first real connection (step 7) is also the first
check of the live API.

## CP25 connection and asset budgets (capacity measurements pending)

Each long-lived bot/web process defaults to `POSTGRES_POOL_SIZE=5` plus
`POSTGRES_POOL_OVERFLOW=10`. Each sequential Celery task defaults to
`POSTGRES_TASK_POOL_SIZE=1`, zero overflow, and disposes its engine on completion.
Multiply those maxima by deployed process counts when reserving Postgres
connections; these are connection budgets, not certified shop capacities.
Pool checkout waits at most5s; asyncpg connect at most10s; statements retain30s.
Do not shrink the bot pool based on the single-connection worker measurement.

After `pip install -e '.[dev]'` (or the normal application install), build public
text compression sidecars before restarting the web process:

```bash
cd /opt/gulbot
.venv/bin/python -m scripts.compress_static
sudo systemctl restart gulbot-web
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

The builder processes only public CSS/JS/SVG, limits each input to1MiB, refuses
symlink outputs, and replaces sidecars atomically. It does not process photos,
private HTML, tokens or fonts already compressed as WOFF2. Rebuild sidecars on
every asset release; do not retain stale sidecars. The script requires768MiB
actual free RAM and refuses once if unavailable. Generated files are ignored
by Git and rebuilt from tracked originals.

Stock [Caddy encode](https://caddyserver.com/docs/caddyfile/directives/encode)
supports gzip/zstd; the shipped proxy uses both. Brotli is built once using the
[Google Brotli codec](https://github.com/google/brotli), negotiated by aiohttp
FileResponse `.br` sidecars upstream, then forwarded through Caddy. This avoids
installing a custom Caddy encoder. Validate the deployed proxy and verify
`Content-Encoding: br` with `curl -H 'Accept-Encoding: br' -I` on a fingerprinted
static URL, and gzip with the equivalent header. A real proxy rehearsal is
still pending; local tests prove actual Brotli/gzip bytes and upstream HTTP.
Keep access logging disabled: private page/login paths contain secrets.

Only a static URL with the exact current content hash gets a year of immutable
caching; unversioned/stale URLs revalidate. Static ETags are provided by
FileResponse, with `Vary: Accept-Encoding`. Customer photos use private
`max-age=0, must-revalidate` and a SHA256 ETag; conditional requests still query
page liveness, moderation and ownership before returning304. Private HTML
remains no-store with the strict CSP.

The4/8/24GB guide and polling-to-webhook threshold await actual100/500/1000
before/after measurements. See CHECKPOINTS and CP25_STATUS; extrapolated values
are not deployment guarantees.

## CP25 capacity guide — pending measured runs

No server shop count is established yet. Historical pressure runs are NOT a
baseline; refused runs have no timing/RSS/CPU capacity result. Configuration
pool/timeout values above are actual settings, not capacity estimates.

|Server RAM|Polling shops|Bot RSS/shop|CPU/shop|Worker layout|Reply p95/p99|Tick budget|
|---|---|---|---|---|---|---|
|4 GB|TBD: pending measured run|TBD: pending measured run|TBD: pending measured run|TBD: pending measured run|TBD: pending measured run|TBD: pending measured run|
|8 GB|TBD: pending measured run|TBD: pending measured run|TBD: pending measured run|TBD: pending measured run|TBD: pending measured run|TBD: pending measured run|
|24 GB|TBD: pending measured run|TBD: pending measured run|TBD: pending measured run|TBD: pending measured run|TBD: pending measured run|TBD: pending measured run|

Reserve measured infrastructure/fixed-process memory separately before deriving
shops from a per-shop slope. An amortized RSS/shop observation includes fixed
overhead and is not that slope. Document measured scale, source commit/hash,
host RAM/CPU, free-RAM minimum, process layout, workload and safety margin for
every eventual estimate; label estimates as extrapolated, never measured.

### Polling versus webhook threshold

Switch threshold: **TBD: pending measured run**. Polling remains the default.
Compare healthy-shop latency under one failed shop, reply deadline failures,
poller restarts, DB pool waits and measured memory/CPU at each scale. If valid
measurements show polling fails below1000 shops, implement/test webhook mode
behind a configuration flag before recommending that capacity. Until then,
neither a webhook capacity number nor a polling fleet guarantee is supported.

### Harness limits and tonight admission

The fake Bot API adds5ms per RPC; customers send0.1 messages/s/shop, plus one
owner announcement per shop. Reminder/order task bodies run sequentially in
100-shop batches with fresh asyncio loops. Broker/prefork scheduling, sustained
production demand, real Telegram/network jitter and a distributed worker fleet
are NOT measured. Tick totals are single-process upper bounds, not measured
production Celery fleet throughput. Real fleet verification remains required.

Prepare Docker/WSL, Postgres and Redis BEFORE admitting the benchmark; record
free RAM and the top five working sets at each setup boundary. No RAM polling,
automatic retry or heartbeat restart in the daytime pass. For100+ shops the
startup floor remains3072MiB. For10/25/50, use that floor until a valid same-scale
measured process/infrastructure peak is available, then peak+1024MiB. Preserve
the512MiB runtime abort floor. Never infer a small-scale peak from2 shops or use
invalid pressure timing rows as capacity evidence.
