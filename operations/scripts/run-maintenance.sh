#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

: "${MAINTENANCE_DATABASE_URL:?MAINTENANCE_DATABASE_URL is required}"
: "${PGPASSFILE:?PGPASSFILE is required}"

MAINTENANCE_PARTITIONS_AHEAD="${MAINTENANCE_PARTITIONS_AHEAD:-2}"
MAINTENANCE_ENABLE_RAW_PURGE="${MAINTENANCE_ENABLE_RAW_PURGE:-false}"
MAINTENANCE_RAW_PURGE_BATCH_SIZE="${MAINTENANCE_RAW_PURGE_BATCH_SIZE:-1000}"
MAINTENANCE_RAW_PURGE_MAX_BATCHES="${MAINTENANCE_RAW_PURGE_MAX_BATCHES:-10}"

MAINTENANCE_ENABLE_OUTBOX_PURGE="${MAINTENANCE_ENABLE_OUTBOX_PURGE:-false}"
MAINTENANCE_OUTBOX_BATCH_SIZE="${MAINTENANCE_OUTBOX_BATCH_SIZE:-1000}"
MAINTENANCE_OUTBOX_MAX_BATCHES="${MAINTENANCE_OUTBOX_MAX_BATCHES:-20}"
MAINTENANCE_OUTBOX_MAX_SECONDS="${MAINTENANCE_OUTBOX_MAX_SECONDS:-20}"
for name in MAINTENANCE_OUTBOX_BATCH_SIZE MAINTENANCE_OUTBOX_MAX_BATCHES MAINTENANCE_OUTBOX_MAX_SECONDS; do
  value="${!name}"
  if [[ ! "$value" =~ ^[1-9][0-9]{0,4}$ ]] || (( value > 10000 )); then
    echo "$name must be between 1 and 10000" >&2; exit 64
  fi
done
if (( MAINTENANCE_OUTBOX_MAX_SECONDS > 60 || MAINTENANCE_OUTBOX_MAX_BATCHES > 100 )); then
  echo "outbox budget exceeds 60 seconds / 100 batches" >&2; exit 64
fi
if [[ "$MAINTENANCE_ENABLE_OUTBOX_PURGE" != true && "$MAINTENANCE_ENABLE_OUTBOX_PURGE" != false ]]; then
  echo "MAINTENANCE_ENABLE_OUTBOX_PURGE must be true or false" >&2; exit 64
fi

if [[ ! "$MAINTENANCE_PARTITIONS_AHEAD" =~ ^[0-9]+$ ]] \
  || (( MAINTENANCE_PARTITIONS_AHEAD > 12 )); then
  echo "MAINTENANCE_PARTITIONS_AHEAD must be between 0 and 12" >&2
  exit 64
fi
for value_name in MAINTENANCE_RAW_PURGE_BATCH_SIZE MAINTENANCE_RAW_PURGE_MAX_BATCHES; do
  value="${!value_name}"
  if [[ ! "$value" =~ ^[1-9][0-9]*$ ]]; then
    echo "$value_name must be a positive integer" >&2
    exit 64
  fi
done
if (( MAINTENANCE_RAW_PURGE_BATCH_SIZE > 10000 || MAINTENANCE_RAW_PURGE_MAX_BATCHES > 20 )); then
  echo "raw purge must not exceed 10000 rows per batch or 20 batches" >&2
  exit 64
fi
if [[ "$MAINTENANCE_ENABLE_RAW_PURGE" != false \
      && "$MAINTENANCE_ENABLE_RAW_PURGE" != true ]]; then
  echo "MAINTENANCE_ENABLE_RAW_PURGE must be true or false" >&2
  exit 64
fi
if [[ ! -r "$PGPASSFILE" ]]; then
  echo "database credential is not readable" >&2
  exit 77
fi
if ! command -v psql >/dev/null 2>&1; then
  echo "required command is missing: psql" >&2
  exit 69
fi

psql "$MAINTENANCE_DATABASE_URL" --no-psqlrc --set ON_ERROR_STOP=1 \
  --set partitions_ahead="$MAINTENANCE_PARTITIONS_AHEAD" <<'SQL'
SET statement_timeout = '15s';
SET lock_timeout = '1s';
SELECT ops_and_admin.refresh_storage_observation() AS storage_observation;
SELECT ops_and_admin.ensure_publication_metric_partition(
           (date_trunc('month', current_date)
              + make_interval(months => offset_month))::date
       ) AS ensured_partition
  FROM generate_series(0, CAST(:'partitions_ahead' AS integer)) AS offsets(offset_month);

SELECT jsonb_build_object(
    'databaseBytes', pg_database_size(current_database()),
    'outboxRowsEstimate', (
        SELECT n_live_tup FROM pg_stat_user_tables
         WHERE schemaname='ops_and_admin' AND relname='outbox_event'
    ),
    'defaultPublicationSnapshots', (
        SELECT count(*) FROM ingest.publication_metric_snapshot_default
    ),
    'defaultReactionRows', (
        SELECT count(*) FROM ingest.reaction_breakdown_default
    ),
    'oldestPendingOutboxAvailableAt', (
        SELECT available_at FROM ops_and_admin.outbox_event
         WHERE published_at IS NULL ORDER BY available_at,id LIMIT 1
    )
) AS maintenance_observation;
SQL

# Distinct from transport outbox. Commit each small batch; retry the next
# timer run on lock contention. Never promote historical pending to delivered.
if [[ "$MAINTENANCE_ENABLE_OUTBOX_PURGE" == true ]]; then
  began=$SECONDS
  total_outbox=0
  for ((batch=0; batch<MAINTENANCE_OUTBOX_MAX_BATCHES; batch++)); do
    (( SECONDS - began < MAINTENANCE_OUTBOX_MAX_SECONDS )) || break
    deleted="$(PGOPTIONS='-c lock_timeout=1s -c statement_timeout=5s' \
      psql "$MAINTENANCE_DATABASE_URL" -X -v ON_ERROR_STOP=1 -At \
      -v batch_size="$MAINTENANCE_OUTBOX_BATCH_SIZE" <<'SQL'
SELECT ops_and_admin.purge_delivered_outbox(interval '1 day', :'batch_size'::integer);
SQL
    )"
    [[ "$deleted" =~ ^[0-9]+$ ]] || { echo "invalid outbox purge result" >&2; exit 70; }
    total_outbox=$((total_outbox + deleted))
    (( deleted == MAINTENANCE_OUTBOX_BATCH_SIZE )) || break
  done
  echo "cache outbox purge completed rows=$total_outbox elapsed=$((SECONDS-began))"
  if [[ -n "${MAINTENANCE_METRICS_FILE:-}" ]]; then
    python3 - "$MAINTENANCE_METRICS_FILE" "$total_outbox" <<'PYMETRICS'
import os, pathlib, sys, tempfile, time
path=pathlib.Path(sys.argv[1])
fd,name=tempfile.mkstemp(prefix='.maintenance-',dir=path.parent)
try:
    with os.fdopen(fd,'w') as stream:
        stream.write(f'mranked_cache_outbox_cleanup_last_success_unixtime {time.time()}\n')
        stream.write(f'mranked_cache_outbox_cleanup_last_rows {int(sys.argv[2])}\n')
        os.fchmod(stream.fileno(),0o644)
    os.replace(name,path)
finally:
    pathlib.Path(name).unlink(missing_ok=True)
PYMETRICS
  fi
fi

if [[ "$MAINTENANCE_ENABLE_RAW_PURGE" == false ]]; then
  echo "raw payload purge is disabled; no rows deleted"
  exit 0
fi

total_deleted=0
raw_began=$SECONDS
for (( batch = 1; batch <= MAINTENANCE_RAW_PURGE_MAX_BATCHES; batch++ )); do
  (( SECONDS - raw_began < 20 )) || break
  deleted="$(
    PGOPTIONS='-c lock_timeout=1s -c statement_timeout=5s' \
    psql "$MAINTENANCE_DATABASE_URL" --no-psqlrc --set ON_ERROR_STOP=1 \
      --set batch_size="$MAINTENANCE_RAW_PURGE_BATCH_SIZE" \
      --tuples-only --no-align <<'SQL'
SELECT ops_and_admin.purge_expired_raw_payload(CAST(:'batch_size' AS integer));
SQL
  )"
  if [[ ! "$deleted" =~ ^[0-9]+$ ]]; then
    echo "raw payload purge returned an invalid count" >&2
    exit 70
  fi
  total_deleted=$((total_deleted + deleted))
  if (( deleted < MAINTENANCE_RAW_PURGE_BATCH_SIZE )); then
    break
  fi
done

echo "raw payload purge completed rows=$total_deleted"
