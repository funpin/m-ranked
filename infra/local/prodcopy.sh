#!/usr/bin/env bash
# Bring the local review stand up on a restored production database copy.
#
#   infra/local/prodcopy.sh /path/to/m-ranked-pgcopy /path/to/credentials.env
#
# The copy is a pg_basebackup directory ("pgdata") plus meta/container-inspect.json.
# The script copies it into a Docker volume, leaving the source untouched, starts
# the stand, provisions the analytics_worker role and replays missing deltas of
# operations/sql/transition-production-to-final.sql when the restored cluster
# still carries the base final contract.
set -euo pipefail

COPY_DIR=${1:?usage: prodcopy.sh <copy directory> <credentials env file>}
ENV_FILE=${2:?usage: prodcopy.sh <copy directory> <credentials env file>}
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
VOLUME=${PRODCOPY_VOLUME:-mranked-local-pgdata}
PROJECT=${PRODCOPY_PROJECT:-mranked-local}
CONTRACT=storage-publisher-final-2026-09-08-r4

[ -d "$COPY_DIR/pgdata" ] || { echo "no $COPY_DIR/pgdata" >&2; exit 1; }
[ -f "$ENV_FILE" ] || { echo "no $ENV_FILE" >&2; exit 1; }

compose() {
  docker compose --env-file "$ENV_FILE" \
    -f "$ROOT/infra/compose.yaml" -f "$ROOT/infra/compose.local.yaml" \
    -f "$ROOT/infra/compose.prodcopy.yaml" -p "$PROJECT" "$@"
}

if ! docker volume inspect "$VOLUME" >/dev/null 2>&1; then
  echo "restoring $COPY_DIR/pgdata into volume $VOLUME"
  docker volume create "$VOLUME" >/dev/null
  docker run --rm -v "$COPY_DIR/pgdata:/src:ro" -v "$VOLUME:/dst" alpine:3 \
    sh -c 'cp -a /src/. /dst/ && chown -R 999:999 /dst && chmod 700 /dst'
else
  echo "volume $VOLUME already exists, reusing it"
fi

compose up -d --build

set -a; . "$ENV_FILE"; set +a
psql_super() {
  docker compose --env-file "$ENV_FILE" -p "$PROJECT" \
    -f "$ROOT/infra/compose.yaml" -f "$ROOT/infra/compose.local.yaml" \
    -f "$ROOT/infra/compose.prodcopy.yaml" \
    exec -T -e PGPASSWORD="$POSTGRES_SUPERUSER_PASSWORD" postgres \
    psql -U mranked_bootstrap -d "${LOCAL_DATABASE_NAME:-mranked}" -v ON_ERROR_STOP=1 "$@"
}

echo "waiting for postgres"
until psql_super -At -c 'SELECT 1' >/dev/null 2>&1; do sleep 2; done

# Production can retire the bridge login after migration. The schema deltas
# still name it in grants, so a restored copy needs the role to exist. Keep it
# unable to log in: this stand never runs the migration bridge or SQLite import.
psql_super -At <<'SQL' >/dev/null
SELECT 'CREATE ROLE migration_bridge NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'migration_bridge') \gexec
SQL

if [ "$(psql_super -At -c "SELECT count(*) FROM pg_roles WHERE rolname='analytics_worker'")" = "0" ]; then
  echo "provisioning analytics_worker"
  psql_super -At -c "CREATE ROLE analytics_worker LOGIN PASSWORD '${ANALYTICS_WORKER_DB_PASSWORD}'" >/dev/null
fi
psql_super -At \
  -c "ALTER ROLE analytics_worker WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT PASSWORD '${ANALYTICS_WORKER_DB_PASSWORD}'" \
  -c "GRANT CONNECT ON DATABASE ${LOCAL_DATABASE_NAME:-mranked} TO analytics_worker" >/dev/null

apply_delta() {
  delta=$(mktemp)
  { echo 'BEGIN;'
    awk -v from="-- $1-delta:begin" -v upto="-- $1-delta:end" \
      '$0==from{on=1;next} $0==upto{on=0} on' \
      "$ROOT/operations/sql/transition-production-to-final.sql"
    echo 'COMMIT;'; } > "$delta"
  psql_super -f - < "$delta" >/dev/null
  rm -f "$delta"
}

# The deltas form a chain. Replay only the ones the restored copy is missing,
# in order, so a copy taken at any released contract reaches the current one.
current=$(psql_super -At -c 'SELECT contract_id FROM ops_and_admin.schema_contract')
case "$current" in
  "$CONTRACT")
    echo "schema contract already $CONTRACT" ;;
  storage-publisher-final-2026-09-08)
    echo "upgrading schema contract $current -> $CONTRACT"
    apply_delta r3
    apply_delta r4
    echo "contract is now $(psql_super -At -c 'SELECT contract_id FROM ops_and_admin.schema_contract')" ;;
  storage-publisher-final-2026-09-08-r3)
    echo "upgrading schema contract $current -> $CONTRACT"
    apply_delta r4
    echo "contract is now $(psql_super -At -c 'SELECT contract_id FROM ops_and_admin.schema_contract')" ;;
  *)
    echo "restored copy carries an unsupported schema contract: $current" >&2
    exit 1 ;;
esac

compose restart api >/dev/null
echo
echo "stand is up:"
echo "  interface  http://localhost:3000"
echo "  api        http://localhost:8080/api/v1/health/ready"
