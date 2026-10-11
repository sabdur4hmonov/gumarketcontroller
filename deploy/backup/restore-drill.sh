#!/usr/bin/env bash
# restore-drill.sh -- restore a backup into a THROWAWAY database and prove it
# holds what was dumped: every table's row count against the counts the backup
# took in its own snapshot, and the migration revision against the live one.
#
#   /opt/gulbot/deploy/backup/restore-drill.sh /var/backups/gulbot/gulbot-<stamp>.dump
#
# Touches nothing live: it creates gulbot_restore_drill_<stamp> beside the
# production database, restores into it, compares, and drops it. A backup
# that was never restored is a hope (docs/DEPLOY.md step 13). Exit 0 only
# when every table matches.
set -euo pipefail
export LC_ALL=C

DUMP=${1:?give the .dump to drill}
COUNTS=${DUMP%.dump}.counts
ENV_FILE=${ENV_FILE:-/etc/gulbot/gulbot.env}
CONTAINER=${CONTAINER:-gulbot-postgres}

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a
[ -s "$DUMP" ] && [ -s "$COUNTS" ] || { echo "need $DUMP and $COUNTS" >&2; exit 2; }

drill="gulbot_restore_drill_$(date -u +%Y%m%d%H%M%S)"
psql_on() { docker exec -i "$CONTAINER" psql -X -q -A -t -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1"; }
cleanup() { echo "DROP DATABASE IF EXISTS $drill;" | psql_on postgres >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "CREATE DATABASE $drill;" | psql_on postgres
started=$(date +%s)
docker exec -i "$CONTAINER" pg_restore --no-owner --no-privileges --exit-on-error \
  -U "$POSTGRES_USER" -d "$drill" < "$DUMP"
echo "restored $(basename "$DUMP") into $drill in $(( $(date +%s) - started ))s"

restored=$(mktemp)
echo "SELECT string_agg(format('SELECT %L || '' '' || count(*) FROM %I', table_name, table_name), ' UNION ALL ' ORDER BY table_name) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE';" \
  | psql_on "$drill" | psql_on "$drill" | sort > "$restored"

mismatches=0
printf '%-34s %10s %10s\n' table dumped restored
while read -r table expected; do
  got=$(awk -v t="$table" '$1 == t {print $2}' "$restored")
  mark=""
  [ "$got" = "$expected" ] || { mark="  <-- MISMATCH"; mismatches=$((mismatches + 1)); }
  printf '%-34s %10s %10s%s\n' "$table" "$expected" "${got:-missing}" "$mark"
done < "$COUNTS"
extra=$(comm -13 <(cut -d' ' -f1 "$COUNTS") <(cut -d' ' -f1 "$restored") || true)
[ -z "$extra" ] || { echo "tables in the restore but not in the backup's counts: $extra"; mismatches=$((mismatches + 1)); }

live_rev=$(echo "SELECT version_num FROM alembic_version;" | psql_on "$POSTGRES_DB")
drill_rev=$(echo "SELECT version_num FROM alembic_version;" | psql_on "$drill")
echo "alembic revision: restored $drill_rev, live $live_rev"
rm -f "$restored"

if [ "$mismatches" -eq 0 ]; then
  echo "RESTORE DRILL PASS: $(wc -l < "$COUNTS") tables, every row count matches the backup's snapshot"
else
  echo "RESTORE DRILL FAIL: $mismatches mismatch(es)"
  exit 1
fi
