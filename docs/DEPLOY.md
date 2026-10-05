# Deploy runbook

Steps that a code change cannot take effect without, or that only the deploy
host can verify. Each one says why it is here, so it is not skipped as ritual.

Started by the pre-deployment audit, pass 5. Add to it whenever a fix needs the
deploy to finish it.

## 0. The production environment. Get this wrong and nothing else matters.

Every production process refuses to start unless it runs with
`ENVIRONMENT=production` and these four are **real environment variables**,
exported for that process. They must not come from a `.env` file or a
built-in default:

```
ENVIRONMENT=production
BOT_TOKEN=<the production bot's token, never the dev one>
POSTGRES_HOST=<production database host>
POSTGRES_DB=<production database name>
POSTGRES_PASSWORD=<not "gulbot">
```

A process with the wrong config dies at startup with
`ProductionConfigError: REFUSING TO START`, followed by the name of every
problem. That is the guard working. Fix the environment; do not work around it.

### STOP. Check `ENVIRONMENT` with your own eyes before starting anything.

**The guard cannot protect a process that never sets `ENVIRONMENT=production`.**
Without it, the process is "local" and runs on dev defaults, silently, by
design. No code can catch this, so a person has to. Do it at every deploy,
before every start.

1. In the shell session that will launch the bot, the worker and beat, run:

   ```
   echo "$ENVIRONMENT"
   ```

2. It must print exactly:

   ```
   production
   ```

   If it prints a blank line, or anything else, **stop**. Start nothing. Set
   the variable, then go back to step 1.

3. Do this check in **that same shell session**. Not in another terminal, and
   not assumed from a script that "already set it" earlier.

4. Only then start the processes, from that session.

If a service manager (systemd, supervisor) starts the processes instead of this
shell, the `echo` proves nothing about them. Check the environment in the
service's unit or config file.

After start, the bot logs `environment=production` on its `starting as @...`
line. Check that the bot name on that line is the production bot.

Do not copy a dev `.env` onto the server. The guard refuses a `.env`-supplied
token or database, but a `.env` can still supply the settings it does not
check, such as ports and Redis.

## 0b. Per-shop bot tokens and the platform bot

Since CP-MT every shop speaks through its own bot. Its token is stored in
`shops.bot_token_encrypted`, encrypted with a key that is only ever an
environment variable:

```
SHOP_TOKEN_ENCRYPTION_KEY=<Fernet key; generate with the command in .env.example>
PLATFORM_BOT_TOKEN=<the onboarding bot's token; leave unset to run without onboarding>
```

- **Back the key up with the database credentials, never inside the
  database.** Lose it and every stored shop token is unreadable: each shop
  would have to hand over its token again.
- **Rotating the key.** Set `SHOP_TOKEN_ENCRYPTION_KEY=<new>,<old>`. The first
  key encrypts and every listed key decrypts. Drop the old key only once
  every token has been re-stored.
- **The platform bot.** With `PLATFORM_BOT_TOKEN` set, the bot process
  refuses to start without a usable encryption key. The platform bot must be
  a bot of its own, never a shop's bot and never `BOT_TOKEN`'s.
- **The pilot shop** may keep using `BOT_TOKEN`, and the bot logs a WARNING
  every time it does. Store its own token to retire the fallback.

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
| Circuit breaker | per shop: 3 consecutive network failures hand back that shop's rows; 3 different shops unanswered in a row end the tick | `sending/transport.py` |
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
## 6. Public pages (Ha/Yo'q, taklifnoma): going live

The page server (`python -m gulbot.web.run`) is built and tested, but it is
only reachable on this machine until these steps are done. **Until
`PUBLIC_BASE_URL` is https, a production bot answers the pages menu with
"coming soon"** (`gulbot.web.links.pages_available`). That is deliberate: a
customer must never be handed an http:// link or a 127.0.0.1 one.

Do these in order.

1. **A domain.** Pick a hostname for the pages, for example
   `pages.<your-domain>.uz`. Point an `A` record (and `AAAA` if the server has
   IPv6) at the VPS. Check it with `nslookup pages.<your-domain>.uz` before
   going on.

2. **HTTPS in front of the page server.** The page server listens on
   127.0.0.1 only; a reverse proxy terminates TLS for it. Caddy is the least
   work, because it obtains and renews the certificate itself:

   ```
   pages.<your-domain>.uz {
       reverse_proxy 127.0.0.1:8088
   }
   ```

   With nginx instead, use certbot for the certificate and
   `proxy_pass http://127.0.0.1:8088;` with
   `proxy_set_header X-Forwarded-For $remote_addr;`.

   Ports 80 and 443 must be open to the internet. Port 8088 must NOT be.

3. **The environment.** Set these for the page-server process, AND for the
   bot and worker processes, which build the links:

   ```
   PUBLIC_BASE_URL=https://pages.<your-domain>.uz   # an origin: no path, no trailing slash
   WEB_HOST=127.0.0.1
   WEB_PORT=8088
   WEB_TRUST_PROXY=true                             # only because a proxy sets X-Forwarded-For
   ```

   Step 0 applies to this process too: check `ENVIRONMENT=production` with
   your own eyes in the shell or unit file that starts it.

4. **Migrate, and check.** The pages add migration `1897629a71dc`:

   ```
   alembic upgrade head
   alembic current
   alembic heads
   ```

   `current` and `heads` must print the same revision.

5. **Install the new dependency** (`jinja2`), with `pip install -e .` on the
   server.

6. **Start the page server** under the service manager, next to the bot,
   worker and beat:

   ```
   python -m gulbot.web.run
   ```

   It logs `pages: serving on 127.0.0.1:8088 for https://pages.<your-domain>.uz
   (environment=production)`. It writes **no access log on purpose**: every
   page's address is its secret. Do not turn one on in the proxy either, or
   configure the proxy not to log paths.

7. **Restart the worker and beat.** That registers the two new tasks,
   `gulbot.notify_page_answer` and `gulbot.scrub_expired_pages`. Beat's
   startup should list `scrub-expired-pages` (03:30).

8. **Verify, from outside the server:**
   - `curl -I https://pages.<your-domain>.uz/healthz` returns 200, with
     `Content-Security-Policy`, `X-Robots-Tag: noindex` and
     `Strict-Transport-Security` in the headers.
   - On a phone, open `https://pages.<your-domain>.uz/demo/yesno` and
     `/demo/invite`, and tap through a few designs.
   - In a shop's bot, make a Ha/Yo'q page. The reply must now carry
     **🔗 Ochish** and **📤 Ulashish** buttons (they appear only on https).
     Open the link, press Ha, and check that the "they said Ha" message
     arrives in the bot.
   - Tap "Gul buyurtma qilish" on the page. It must open THAT shop's bot.

**Backups.** The new tables (`share_pages`, `share_page_rsvps`,
`share_page_referrals`) are in the normal database dump. Nothing is stored on
disk.

## 7. CP17: date plans, Uzrnoma, editable pages, photos, sections, music

Everything in section 6 still holds. On top of it:

1. **A new dependency: Pillow** (`pillow>=11,<12`), for the page photos. It is
   in `pyproject.toml`; install with `pip install -e .` on the server, then
   check it imports in the SAME environment the bot and page server run in:

   ```
   python -c "import PIL; print(PIL.__version__)"
   ```

   Pillow ships binary wheels for Linux; nothing else needs installing. The
   bot needs it (it re-encodes photos as they arrive); the page server only
   serves what is already stored.

2. **Ten migrations, all forward-only in normal use**, from `1897629a71dc`
   (CP16) to the new head `c5a8e2d61f37`:

   | Revision | What it adds |
   |---|---|
   | `360f0694be06` | `en` as a customer language |
   | `83ca22ed6f83` | the editable taklifnoma text blocks (title, dress code, programme, contact, closing) and an edit stamp |
   | `878bc32b72d4` | the date plan: `share_page_options`, the chosen place and time |
   | `797f8207081f` | the ten new designs in the template CHECK |
   | `86570def06eb` | `share_page_photos` (stored in Postgres, 1.5 MB cap each) |
   | `cf7aa499fe45` | the countdown and gallery switches, and the dress-code colours with a shape CHECK |
   | `541afb7b8568` | `share_page_wishes` |
   | `9d2e41c07a5b` | the Konvert seal's letters |
   | `b3f7a90c2e14` | `music`, with a CHECK naming our three tracks |
   | `c5a8e2d61f37` | the `apology` kind (Uzrnoma) |

   ```
   alembic upgrade head
   alembic current      # must print c5a8e2d61f37 (head)
   alembic heads
   ```

   All are additive: no column is dropped, no existing row changes. **Two
   downgrades change data**, because the old CHECKs cannot hold it: going
   below `c5a8e2d61f37` deletes every Uzrnoma page, and going below
   `360f0694be06` turns every English-speaking customer back into an Uzbek
   one. Back up first if you ever need to roll back past them.

3. **Restart the bot, the worker and the page server** -- all three, since
   each imports the new code. The worker must be running: the "they said Ha
   -- here is the place and time they picked" message, and the "nothing chosen
   yet" follow-up ten minutes later, are queued with a Celery countdown.

4. **Backups grow with photos.** Photos live in `share_page_photos` (at most
   six per invitation, each re-encoded to ≤ 1.5 MB, usually a few hundred
   KB), so they are in the normal dump and are deleted with their page by the
   nightly scrub. Watch the dump size for the first weeks.

5. **Verify, from outside the server**, after section 6's checks:
   - `/demo/apology/konvert` and `/demo/invite/oltin` open on a phone.
   - Make a Ha/Yo'q page with a date plan, press Ha, pick a place and time:
     the creator gets ONE message naming both.
   - Edit a taklifnoma's title from "Mening sahifalarim": the same link
     shows the new title.
   - Send the bot a photo for an invitation's gallery, then download it from
     the page and check it has no EXIF (`exiftool` shows only JPEG basics).
