#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

mode=""
repo=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      mode="${2:-}"
      shift 2
      ;;
    --repo)
      repo="${2:-}"
      shift 2
      ;;
    *)
      echo "usage: $0 --mode latest|pitr --repo 1|2|3" >&2
      exit 64
      ;;
  esac
done
if [[ "$mode" != latest && "$mode" != pitr ]]; then
  echo "mode must be latest or pitr" >&2
  exit 64
fi
if [[ ! "$repo" =~ ^[123]$ ]]; then
  echo "repo must be 1, 2 or 3" >&2
  exit 64
fi

: "${PGBACKREST_CONFIG:?PGBACKREST_CONFIG is required}"
: "${PGBACKREST_STANZA:=m-ranked}"
: "${PG_BIN:=/usr/lib/postgresql/18/bin}"
: "${RESTORE_WORK_ROOT:=/var/lib/m-ranked/restore-verify}"
: "${RESTORE_REPORT_DIR:=/var/lib/m-ranked/restore-reports}"
: "${RESTORE_DATABASE:=mranked}"
: "${RESTORE_DATABASE_USER:=mranked_bootstrap}"
: "${RESTORE_PORT:=55439}"
: "${RESTORE_TARGET_LAG_MINUTES:=30}"
: "${RESTORE_RTO_SECONDS:=7200}"
: "${RESTORE_KEEP_FAILED:=false}"

if [[ "$RESTORE_WORK_ROOT" != /* || "$RESTORE_REPORT_DIR" != /* \
      || "$RESTORE_WORK_ROOT" == / || "$RESTORE_REPORT_DIR" == / \
      || "$RESTORE_WORK_ROOT" == /var/lib/postgresql* ]]; then
  echo "restore paths must be dedicated absolute non-PostgreSQL directories" >&2
  exit 64
fi
for value_name in RESTORE_PORT RESTORE_TARGET_LAG_MINUTES RESTORE_RTO_SECONDS; do
  value="${!value_name}"
  if [[ ! "$value" =~ ^[1-9][0-9]*$ ]]; then
    echo "$value_name must be a positive integer" >&2
    exit 64
  fi
done
if (( RESTORE_PORT < 1024 || RESTORE_PORT > 65535 )); then
  echo "RESTORE_PORT must be an unprivileged TCP port" >&2
  exit 64
fi
if [[ "$RESTORE_KEEP_FAILED" != false && "$RESTORE_KEEP_FAILED" != true ]]; then
  echo "RESTORE_KEEP_FAILED must be true or false" >&2
  exit 64
fi

for command_name in pgbackrest jq sha256sum flock install mktemp date find chmod mv sleep; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "required command is missing: $command_name" >&2
    exit 69
  fi
done
for postgres_command in pg_ctl pg_isready psql pg_checksums pg_amcheck; do
  if [[ ! -x "$PG_BIN/$postgres_command" ]]; then
    echo "required PostgreSQL 18 command is missing: $PG_BIN/$postgres_command" >&2
    exit 69
  fi
done
if [[ ! -r "$PGBACKREST_CONFIG" ]]; then
  echo "pgBackRest restore configuration is not readable" >&2
  exit 77
fi

install -d -m 0700 "$RESTORE_WORK_ROOT" "$RESTORE_REPORT_DIR"
exec 9>"$RESTORE_WORK_ROOT/.restore-verify.lock"
if ! flock -n 9; then
  echo "another restore verification is running" >&2
  exit 75
fi

started_epoch="$(date -u +%s)"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
work_dir="$(mktemp -d "$RESTORE_WORK_ROOT/verify.XXXXXX")"
pgdata="$work_dir/pgdata"
socket_dir="$work_dir/socket"
hba_file="$work_dir/pg_hba.verify.conf"
postgres_log="$work_dir/postgres.log"
started_postgres=false

cleanup() {
  local exit_code=$?
  trap - EXIT
  if [[ "$started_postgres" == true ]]; then
    if "$PG_BIN/pg_ctl" --pgdata="$pgdata" --mode=fast --wait stop >/dev/null 2>&1; then
      started_postgres=false
    else
      exit_code=1
      echo "ephemeral PostgreSQL could not be stopped; restore work is retained" >&2
    fi
  fi
  if [[ "$started_postgres" == false \
        && ( $exit_code -eq 0 || "$RESTORE_KEEP_FAILED" == false ) ]]; then
    case "$work_dir" in
      "$RESTORE_WORK_ROOT"/verify.*)
        find "$work_dir" -depth -delete
        ;;
      *)
        echo "refusing to clean unexpected restore work path" >&2
        ;;
    esac
  else
    echo "failed restore retained for investigation at $work_dir" >&2
  fi
  exit "$exit_code"
}
trap cleanup EXIT

info_json="$(
  pgbackrest --config="$PGBACKREST_CONFIG" --stanza="$PGBACKREST_STANZA" \
    --repo="$repo" --output=json info
)"
if ! jq -e '
    length == 1
    and .[0].status.code == 0
    and .[0].cipher == "aes-256-cbc"
    and (.[0].backup | length) > 0
  ' <<<"$info_json" >/dev/null; then
  echo "pgBackRest repository is unavailable, unencrypted or has no backup" >&2
  exit 65
fi

restore_arguments=(
  --config="$PGBACKREST_CONFIG"
  --stanza="$PGBACKREST_STANZA"
  --repo="$repo"
  --pg1-path="$pgdata"
  --process-max=2
)
target_time=""
if [[ "$mode" == pitr ]]; then
  target_time="$(
    date -u --date="$RESTORE_TARGET_LAG_MINUTES minutes ago" '+%Y-%m-%d %H:%M:%S+00'
  )"
  restore_arguments+=(--type=time --target="$target_time" --target-action=promote)
fi

pgbackrest "${restore_arguments[@]}" restore
"$PG_BIN/pg_checksums" --check --pgdata="$pgdata"

install -d -m 0700 "$socket_dir"
printf 'local all all trust\n' >"$hba_file"
chmod 0600 "$hba_file"

"$PG_BIN/pg_ctl" --pgdata="$pgdata" --wait \
  --options="-c listen_addresses='' -c port=$RESTORE_PORT -c unix_socket_directories='$socket_dir' -c hba_file='$hba_file' -c logging_collector=off" \
  --log="$postgres_log" start
started_postgres=true

for _ in {1..60}; do
  if "$PG_BIN/pg_isready" --host="$socket_dir" --port="$RESTORE_PORT" \
      --dbname="$RESTORE_DATABASE" --username="$RESTORE_DATABASE_USER" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
"$PG_BIN/pg_isready" --host="$socket_dir" --port="$RESTORE_PORT" \
  --dbname="$RESTORE_DATABASE" --username="$RESTORE_DATABASE_USER" --timeout=2

database_assertion="$(
  "$PG_BIN/psql" --host="$socket_dir" --port="$RESTORE_PORT" \
    --username="$RESTORE_DATABASE_USER" --dbname="$RESTORE_DATABASE" \
    --no-psqlrc --set ON_ERROR_STOP=1 --quiet --tuples-only --no-align <<'SQL'
DO $assertions$
DECLARE
    latest_revision bigint;
    ready_count integer;
    migration_count integer;
    latest_migration integer;
    migration_versions text[];
BEGIN
    IF current_setting('server_version_num')::integer <> 180006 THEN
        RAISE EXCEPTION 'restore verifier requires PostgreSQL 18.6, found %',
            current_setting('server_version');
    END IF;
    IF pg_is_in_recovery() THEN
        RAISE EXCEPTION 'restored database is still in recovery';
    END IF;
    SELECT count(*), max(version::integer), array_agg(version ORDER BY version::integer)
      INTO migration_count, latest_migration, migration_versions
      FROM flyway.flyway_schema_history
     WHERE version IS NOT NULL
       AND success;
    IF migration_count <> 8 OR latest_migration <> 8
       OR migration_versions IS DISTINCT FROM
          ARRAY['1', '2', '3', '4', '5', '6', '7', '8']::text[]
       OR EXISTS (
           SELECT 1 FROM flyway.flyway_schema_history
            WHERE version IS NOT NULL AND NOT success
       ) OR EXISTS (
           SELECT 1 FROM flyway.flyway_schema_history
            WHERE version IS NULL
       ) OR EXISTS (
           SELECT 1
             FROM (VALUES
                 ('1', 'V1__target_baseline.sql', -1636077697),
                 ('2', 'V2__rebuild_core_projections.sql', 839607018),
                 ('3', 'V3__collector_observation_times_and_identity_grants.sql', -1456658399),
                 ('4', 'V4__admin_collection_run_status_grants.sql', 1318350062),
                 ('5', 'V5__legacy_activity_period_projection.sql', -1313754193),
                 ('6', 'V6__comparison_valid_observation_hourly_projection.sql', -290358219),
                 ('7', 'V7__activity_rating_read_grants.sql', -1228913579),
                 ('8', 'V8__legacy_overview_projection.sql', -574188650)
             ) AS expected(version, script, checksum)
             FULL JOIN (
                 SELECT version, script, checksum
                   FROM flyway.flyway_schema_history
                  WHERE version IS NOT NULL
                    AND success
             ) AS actual USING (version)
            WHERE expected.version IS NULL
               OR actual.version IS NULL
               OR actual.script IS DISTINCT FROM expected.script
               OR actual.checksum IS DISTINCT FROM expected.checksum
       ) THEN
        RAISE EXCEPTION 'restored Flyway history does not match frozen V1-V8';
    END IF;
    SELECT max(id) INTO latest_revision FROM analytics.dataset_revision;
    IF latest_revision IS NULL THEN
        RAISE EXCEPTION 'restored database has no dataset revision';
    END IF;
    SELECT count(*) INTO ready_count
      FROM analytics.projection_state
     WHERE dataset_revision_id = latest_revision
       AND status = 'ready'
       AND projection_name IN (
           'publication_latest', 'publication_hourly',
           'institution_daily_metrics', 'institution_monthly_metrics',
           'institution_period_metrics', 'comparison'
       );
    IF ready_count <> 6 THEN
        RAISE EXCEPTION 'restored latest revision % has % ready core projections',
            latest_revision, ready_count;
    END IF;
END
$assertions$;

SELECT jsonb_build_object(
    'database', current_database(),
    'serverVersionNum', current_setting('server_version_num')::integer,
    'inRecovery', pg_is_in_recovery(),
    'flywaySchemaVersion', (
        SELECT max(version::integer) FROM flyway.flyway_schema_history
         WHERE version IS NOT NULL AND success
    ),
    'flywayMigrationCount', (
        SELECT count(*) FROM flyway.flyway_schema_history
         WHERE version IS NOT NULL AND success
    ),
    'flywayMigrations', (
        SELECT jsonb_agg(
                   jsonb_build_object(
                       'version', version,
                       'script', script,
                       'checksum', checksum
                   )
                   ORDER BY version::integer
               )
          FROM flyway.flyway_schema_history
         WHERE version IS NOT NULL AND success
    ),
    'lastWalReplayLsn', pg_last_wal_replay_lsn(),
    'lastXactReplayAt', pg_last_xact_replay_timestamp(),
    'datasetRevision', (SELECT max(id) FROM analytics.dataset_revision),
    'datasetCommittedAt', (SELECT max(committed_at) FROM analytics.dataset_revision),
    'coreReadyProjections', (
        SELECT count(*) FROM analytics.projection_state
         WHERE dataset_revision_id = (SELECT max(id) FROM analytics.dataset_revision)
           AND status = 'ready'
    )
);
SQL
)"

"$PG_BIN/pg_amcheck" --all --host="$socket_dir" --port="$RESTORE_PORT" \
  --username="$RESTORE_DATABASE_USER"

"$PG_BIN/pg_ctl" --pgdata="$pgdata" --mode=fast --wait stop
started_postgres=false

finished_epoch="$(date -u +%s)"
finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
duration_seconds=$((finished_epoch - started_epoch))
status=pass
if (( duration_seconds > RESTORE_RTO_SECONDS )); then
  status=fail
fi

report_tmp="$(mktemp "$RESTORE_REPORT_DIR/.restore-report.XXXXXX")"
report_final="$RESTORE_REPORT_DIR/restore-${mode}-${started_at//[:]/}.json"
jq -n \
  --arg status "$status" \
  --arg mode "$mode" \
  --argjson repository "$repo" \
  --arg startedAt "$started_at" \
  --arg finishedAt "$finished_at" \
  --arg targetTime "$target_time" \
  --argjson durationSeconds "$duration_seconds" \
  --argjson rtoSeconds "$RESTORE_RTO_SECONDS" \
  --argjson database "$database_assertion" \
  --argjson backupInfo "$info_json" \
  '{
      status: $status,
      mode: $mode,
      repository: $repository,
      startedAt: $startedAt,
      finishedAt: $finishedAt,
      targetTime: (if $targetTime == "" then null else $targetTime end),
      durationSeconds: $durationSeconds,
      rtoSeconds: $rtoSeconds,
      rtoMet: ($durationSeconds <= $rtoSeconds),
      checks: {
          repositoryReadable: true,
          pageChecksums: true,
          databaseAssertions: true,
          pgAmcheck: true
      },
      database: $database,
      backupInfo: $backupInfo
  }' >"$report_tmp"
chmod 0600 "$report_tmp"
mv -- "$report_tmp" "$report_final"
sha256sum "$report_final" >"$report_final.sha256"
chmod 0600 "$report_final.sha256"

echo "restore verification status=$status mode=$mode duration_seconds=$duration_seconds report=$report_final"
if [[ "$status" != pass ]]; then
  exit 1
fi

sha256sum --check "$report_final.sha256" >/dev/null
if [[ "$mode" == latest ]]; then
  stable_report="$RESTORE_REPORT_DIR/latest.json"
else
  stable_report="$RESTORE_REPORT_DIR/latest-pitr.json"
fi
stable_tmp="$(mktemp "$RESTORE_REPORT_DIR/.stable-restore.XXXXXX")"
install -m 0600 "$report_final" "$stable_tmp"
mv -- "$stable_tmp" "$stable_report"
sha256sum "$stable_report" >"$stable_report.sha256"
chmod 0600 "$stable_report.sha256"
