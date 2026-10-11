#!/usr/bin/env bash
# The staging rehearsal (CP21): docs/DEPLOY.md, step by step, against a
# stand-in server in local Linux containers -- then torn down.
#
#   bash deploy/rehearsal/rehearse.sh <dev .env with BOT_TOKEN> [keep]
#
# Run from anywhere; it works from the repo root. Memory-heavy: run nothing
# else heavy beside it. The transcript goes to deploy/rehearsal/out/transcript.txt
# with the bot token redacted; `keep` leaves the stack up for a look around
# (tear it down later with `docker compose -p gulbot-rehearsal down -v`).
set -u
# Git Bash on Windows would rewrite /etc/... arguments into Windows paths
# before docker sees them. Harmless on Linux.
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/../.." || exit 1
DEV_ENV=${1:?give the dev .env that holds BOT_TOKEN}
KEEP=${2:-}
OUT=deploy/rehearsal/out
ENV_FILE=$OUT/gulbot.env
COMPOSE=(docker compose -f deploy/rehearsal/compose.yml --env-file "$ENV_FILE")
SERVER=gulbot-rehearsal-server
mkdir -p "$OUT"
PY=${PY:-python}
UNITS=(gulbot-bot gulbot-worker gulbot-beat gulbot-web)

X() { docker exec "$SERVER" "$@"; }
# A command as the gulbot user with the production environment -- exactly
# what DEPLOY steps 6 and 7 run, and what the units get from EnvironmentFile.
AS_GULBOT() {
  X sudo -u gulbot bash -c "set -a; . /etc/gulbot/gulbot.env; set +a; cd /opt/gulbot; $1"
}
step() { echo; echo "== $*"; }
# systemd-analyze verify prints nothing and exits 0 for a clean unit.
verify() {
  local said rc
  said=$(X systemd-analyze verify "$@" 2>&1); rc=$?
  [ -n "$said" ] && echo "$said"
  echo "systemd-analyze verify $(printf '%s ' "${@##*/}"): exit $rc"
}

teardown() {
  step "teardown"
  "${COMPOSE[@]}" down -v --remove-orphans 2>&1 | tail -3
  docker image rm gulbot-rehearsal-server >/dev/null 2>&1 && echo "image removed"
  rm -f "$ENV_FILE" "$OUT/root.crt" "$OUT/Caddyfile"
  echo "env file and CA removed"
  echo "left running: $(docker ps -q --filter name=gulbot-rehearsal | wc -l) rehearsal container(s)"
}

run() {
  step "0. the env file, filled as DEPLOY step 4 says (values never printed)"
  "$PY" deploy/rehearsal/make_env.py deploy/gulbot.env.example "$DEV_ENV" "$ENV_FILE" || return 1

  step "5'. the production compose override, checked as written (ports on 127.0.0.1 only)"
  docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml --env-file "$ENV_FILE" \
    config --format json | "$PY" -c "import json,sys; d=json.load(sys.stdin); print({n: [p.get('host_ip', '') + ':' + str(p['published']) for p in s.get('ports', [])] for n, s in d['services'].items()})"

  step "1-3. build the server by DEPLOY's steps from the tracked tree, start it, and Postgres + Redis on its loopback"
  # What a clone would hold: the tracked files (staged and unstaged edits
  # included, untracked ones not), with git's file modes.
  local tree; tree=$(git stash create); tree=${tree:-HEAD}
  git archive --format=tar "$tree" \
    | docker build -q -t gulbot-rehearsal-server -f deploy/rehearsal/Dockerfile.server - >/dev/null \
    || { echo "image build FAILED"; return 1; }
  echo "image built from $(git rev-parse --short HEAD)$([ "$tree" = HEAD ] || echo ' + working-tree edits')"
  "${COMPOSE[@]}" up -d 2>&1 | grep -E "Started|Created|ERROR|error" | tail -8
  for _ in $(seq 1 60); do
    state=$(X systemctl is-system-running 2>/dev/null)
    case "$state" in running|degraded) break ;; esac
    sleep 2
  done
  echo "systemd: $(X systemctl is-system-running 2>&1)"
  X python3.11 --version
  echo "free on the server: $(X free -m | awk '/Mem:/ {print $7}') MB available"

  step "4. /etc/gulbot/gulbot.env: root:gulbot 0640"
  docker cp "$ENV_FILE" "$SERVER:/etc/gulbot/gulbot.env" >/dev/null
  X chown root:gulbot /etc/gulbot/gulbot.env && X chmod 0640 /etc/gulbot/gulbot.env
  X stat -c '%U:%G %a %n' /etc/gulbot/gulbot.env
  echo "a .env in /opt/gulbot: $(X test -e /opt/gulbot/.env && echo PRESENT -- WRONG || echo none, as step 3 requires)"

  step "5. Postgres and Redis: listening on the server's 127.0.0.1 only"
  for _ in $(seq 1 30); do X pg_isready -h 127.0.0.1 -p 5433 -q && break; sleep 2; done
  X pg_isready -h 127.0.0.1 -p 5433
  X ss -ltn | grep -E ':(5433|6380|443|8088) ' | awk '{print "listening:", $4}'

  step "6. the production guard, checked by eye"
  AS_GULBOT ".venv/bin/python deploy/rehearsal/inside.py guard"
  echo "-- and with the env file NOT loaded (a process that forgot it):"
  X sudo -u gulbot bash -c "cd /opt/gulbot && ENVIRONMENT=production .venv/bin/python -c 'from gulbot.config import get_settings; get_settings()'" 2>&1 \
    | grep -E "REFUSING|^  - " | head -6

  step "7. migrations: current must equal heads"
  AS_GULBOT ".venv/bin/alembic upgrade head" 2>&1 | tail -1
  echo "current: $(AS_GULBOT '.venv/bin/alembic current' 2>/dev/null | tail -1)"
  echo "heads:   $(AS_GULBOT '.venv/bin/alembic heads' 2>/dev/null | tail -1)"

  step "7b. the pilot shop, with BOT_TOKEN as its own bot"
  AS_GULBOT ".venv/bin/python -m gulbot.cli.seed --name 'Rehearsal Shop' --store-bot-token" 2>&1 | tail -2
  echo "-- and again (idempotent):"
  AS_GULBOT ".venv/bin/python -m gulbot.cli.seed --name 'Rehearsal Shop' --store-bot-token" 2>&1 | tail -2

  step "8. the units: verified, enabled, started"
  verify $(for u in "${UNITS[@]}"; do echo "/etc/systemd/system/$u.service"; done)
  X systemctl daemon-reload
  X systemctl enable --now "${UNITS[@]}" 2>&1 | tail -4
  sleep 40
  X systemctl --no-pager --plain list-units 'gulbot-*' | grep gulbot
  # "active" at one instant hides a crash loop (the first rehearsal's bot
  # restarted every ten seconds and looked active): count the restarts.
  local restarts=0 u n
  for u in "${UNITS[@]}"; do
    n=$(X systemctl show -p NRestarts --value "$u"); restarts=$((restarts + n))
    echo "$u: restarted $n time(s)"
  done
  [ "$restarts" -eq 0 ] || echo "UNITS RESTARTING -- see journalctl"
  echo "-- bot:";    X journalctl -u gulbot-bot --no-pager -o cat | grep -E "serving|environment|polling|ERROR|Traceback" | head -5
  echo "-- worker:"; X journalctl -u gulbot-worker --no-pager -o cat | grep -E "concurrency|ready|ERROR|Traceback" | head -3
  echo "-- beat:";   X journalctl -u gulbot-beat --no-pager -o cat | grep -iE "beat: Starting|Scheduler|ERROR|Traceback" | head -3
  echo "-- web:";    X journalctl -u gulbot-web --no-pager -o cat | grep -E "serving|ERROR|Traceback" | head -2
  echo "beat processes: $(X pgrep -fc 'celery -A gulbot.worker.app beat')  (must be exactly 1)"
  echo "worker pool processes: $(X pgrep -fc 'celery -A gulbot.worker.app worker')  (1 parent + 2 prefork children)"

  step "9. HTTPS: Caddy with the repo's Caddyfile, hostname put in, internal TLS"
  sed -e 's/^pages\.example\.uz {/localhost {\n\ttls internal/' deploy/Caddyfile > "$OUT/Caddyfile"
  docker cp "$OUT/Caddyfile" "$SERVER:/etc/caddy/Caddyfile" >/dev/null
  X caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile 2>&1 | tail -1
  X systemctl restart caddy && sleep 5 && X systemctl is-active caddy
  docker cp "$SERVER:/var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt" "$OUT/root.crt" >/dev/null
  echo "Caddy's internal root CA copied out, to verify TLS for real"

  step "a due reminder: planted a minute ago, for a chat no bot can reach"
  ROW=$(AS_GULBOT ".venv/bin/python deploy/rehearsal/inside.py plant" | tail -1)
  echo "planted scheduled_notifications.id=$ROW; waiting for beat's tick and the worker"
  STATE=""
  for _ in $(seq 1 18); do
    STATE=$(AS_GULBOT ".venv/bin/python deploy/rehearsal/inside.py reminder $ROW" | tail -1)
    case "$STATE" in state=pending\ attempts=0*) sleep 10 ;; *) break ;; esac
  done
  echo "$STATE"
  X journalctl -u gulbot-worker --no-pager -o cat | grep -E "send_due|send-due|reminder" | tail -3

  step "10. from outside the server, over HTTPS"
  PAGE=$(AS_GULBOT ".venv/bin/python deploy/rehearsal/inside.py page" | tail -1)
  "$PY" deploy/rehearsal/smoke.py https://localhost:8443 "$OUT/root.crt" "$PAGE"
  SMOKE=$?

  step "the heartbeats beat and the worker wrote"
  AS_GULBOT ".venv/bin/python deploy/rehearsal/inside.py jobs"
  echo "beat processes now: $(X pgrep -fc 'celery -A gulbot.worker.app beat')"
  for u in "${UNITS[@]}"; do
    n=$(X systemctl show -p NRestarts --value "$u"); restarts=$((restarts + n))
    echo "$u: restarted $n time(s) since start"
  done

  step "13. backups: the units verified, the timer armed, one backup run, the restore drill"
  X cp /opt/gulbot/deploy/backup/gulbot-backup.service /opt/gulbot/deploy/backup/gulbot-backup.timer /etc/systemd/system/
  # The one rehearsal-only difference: this Postgres container has its own
  # name, because the dev machine already runs one called gulbot-postgres.
  X mkdir -p /etc/systemd/system/gulbot-backup.service.d
  X bash -c 'printf "[Service]\nEnvironment=CONTAINER=gulbot-rehearsal-postgres\n" > /etc/systemd/system/gulbot-backup.service.d/rehearsal.conf'
  verify /etc/systemd/system/gulbot-backup.service /etc/systemd/system/gulbot-backup.timer
  X systemctl daemon-reload
  X systemctl enable --now gulbot-backup.timer 2>&1 | tail -1
  X systemctl list-timers --no-pager gulbot-backup.timer | head -2
  # Bounded: the first rehearsal's backup hung here, holding the run forever.
  X timeout 300 systemctl start gulbot-backup.service || echo "BACKUP DID NOT FINISH within 5 minutes"
  echo "backup unit: $(X systemctl show -p Result --value gulbot-backup.service)"
  X journalctl -u gulbot-backup --no-pager -o cat | grep -E "backup:|error|ERROR" | tail -3
  X ls -l /var/backups/gulbot
  DUMP=$(X bash -c 'ls -1t /var/backups/gulbot/gulbot-*.dump | head -1')
  X env CONTAINER=gulbot-rehearsal-postgres /opt/gulbot/deploy/backup/restore-drill.sh "$DUMP"
  DRILL=$?
  echo "restore drill exit: $DRILL"
  echo "drill databases left behind: $(set -a; . "$ENV_FILE"; docker exec gulbot-rehearsal-postgres \
    psql -X -A -t -U "$POSTGRES_USER" -d postgres \
    -c "SELECT count(*) FROM pg_database WHERE datname LIKE 'gulbot_restore_drill_%'")"

  return $(( SMOKE || DRILL || restarts ))
}

TOKEN=$(grep -E '^BOT_TOKEN=' "$DEV_ENV" | head -1 | cut -d= -f2- | tr -d '"\r')
{ run; echo "rehearsal exit: $?"; } 2>&1 | sed "s|${TOKEN:-__no_token__}|<BOT_TOKEN>|g" | tee "$OUT/transcript.txt"
[ "$KEEP" = keep ] || teardown 2>&1 | tee -a "$OUT/transcript.txt"
