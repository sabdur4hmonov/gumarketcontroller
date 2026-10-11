#!/usr/bin/env bash
# gulbot-backup.sh -- a dump of the production database, with every table's
# row count taken IN THE SAME SNAPSHOT, and 14 days' retention.
#
#   /opt/gulbot/deploy/backup/gulbot-backup.sh        (root, nightly: gulbot-backup.timer)
#
# Writes BACKUP_DIR/gulbot-<UTC stamp>.dump (pg_dump custom format) and
# gulbot-<stamp>.counts ("table count" per line). The counts are what the
# restore drill (restore-drill.sh) compares a restore against: exact, even on
# a busy database, because they were counted in the very snapshot that was
# dumped -- one REPEATABLE READ transaction exports it, counts in it, and
# pg_dump --snapshot dumps it.
#
# It does NOT copy the dump off the server: that is yours (rsync, rclone,
# scp -- docs/DEPLOY.md step 13). Nor the env file and the encryption key:
# those go in a password manager, never next to the dump.
set -euo pipefail
# One byte order for every sort, here and in the drill that compares.
export LC_ALL=C

ENV_FILE=${ENV_FILE:-/etc/gulbot/gulbot.env}
BACKUP_DIR=${BACKUP_DIR:-/var/backups/gulbot}
KEEP_DAYS=${KEEP_DAYS:-14}
CONTAINER=${CONTAINER:-gulbot-postgres}

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
: "${POSTGRES_USER:?} ${POSTGRES_DB:?}"

stamp=$(date -u +%Y%m%dT%H%M%SZ)
# Root-only from the first byte, partial files included.
umask 077
mkdir -p "$BACKUP_DIR"
chmod 0700 "$BACKUP_DIR"
part="$BACKUP_DIR/.partial-$stamp"
trap 'rm -f "$part.dump" "$part.counts"' EXIT

# One session holds the snapshot open for the whole backup.
coproc PSQL { docker exec -i "$CONTAINER" psql -X -q -A -t -v ON_ERROR_STOP=1 \
  -U "$POSTGRES_USER" -d "$POSTGRES_DB"; }
exec 3>&"${PSQL[1]}" 4<&"${PSQL[0]}"
say() { printf '%s\n' "$1" >&3; }
read_until_end() { local line; while IFS= read -r line <&4; do
  [ "$line" = "__END__" ] && return 0; printf '%s\n' "$line"; done; return 1; }

say "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;"
say "SELECT pg_export_snapshot(); SELECT '__END__';"
snapshot=$(read_until_end)
[ -n "$snapshot" ] || { echo "no snapshot exported" >&2; exit 1; }

# Every base table in public, counted in the exported snapshot.
say "SELECT string_agg(format('SELECT %L || '' '' || count(*) FROM %I', table_name, table_name), ' UNION ALL ' ORDER BY table_name) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'; SELECT '__END__';"
count_sql=$(read_until_end)
say "$count_sql; SELECT '__END__';"
read_until_end | sort > "$part.counts"

docker exec "$CONTAINER" pg_dump -U "$POSTGRES_USER" -Fc --snapshot="$snapshot" "$POSTGRES_DB" \
  > "$part.dump"
say "COMMIT;"
# Tell psql to quit. Closing fd 3 alone is not EOF, because the coproc's own
# copy of the pipe stays open -- the first rehearsal hung right here.
say '\q'
exec 3>&- 4<&-
# Bash unsets PSQL_PID once the coproc has gone; -u must not trip on that.
wait "${PSQL_PID:-}" 2>/dev/null || true

[ -s "$part.dump" ] || { echo "the dump is empty" >&2; exit 1; }
mv "$part.counts" "$BACKUP_DIR/gulbot-$stamp.counts"
mv "$part.dump" "$BACKUP_DIR/gulbot-$stamp.dump"
chmod 0600 "$BACKUP_DIR/gulbot-$stamp.dump" "$BACKUP_DIR/gulbot-$stamp.counts"
trap - EXIT

# Retention: dumps and their counts older than KEEP_DAYS.
find "$BACKUP_DIR" -maxdepth 1 -name 'gulbot-*.dump' -mtime +"$KEEP_DAYS" -print -delete
find "$BACKUP_DIR" -maxdepth 1 -name 'gulbot-*.counts' -mtime +"$KEEP_DAYS" -print -delete

size=$(du -h "$BACKUP_DIR/gulbot-$stamp.dump" | cut -f1)
tables=$(wc -l < "$BACKUP_DIR/gulbot-$stamp.counts")
echo "backup: $BACKUP_DIR/gulbot-$stamp.dump ($size, $tables tables counted in its snapshot)"
