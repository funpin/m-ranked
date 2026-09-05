#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

: "${MAINTENANCE_DATABASE_URL:?MAINTENANCE_DATABASE_URL is required}"
: "${PGPASSFILE:?PGPASSFILE is required}"

MAINTENANCE_PARTITIONS_AHEAD="${MAINTENANCE_PARTITIONS_AHEAD:-2}"
MAINTENANCE_ENABLE_RAW_PURGE="${MAINTENANCE_ENABLE_RAW_PURGE:-false}"
MAINTENANCE_RAW_PURGE_BATCH_SIZE="${MAINTENANCE_RAW_PURGE_BATCH_SIZE:-10000}"
MAINTENANCE_RAW_PURGE_MAX_BATCHES="${MAINTENANCE_RAW_PURGE_MAX_BATCHES:-10}"

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
if (( MAINTENANCE_RAW_PURGE_BATCH_SIZE > 100000 )); then
  echo "MAINTENANCE_RAW_PURGE_BATCH_SIZE must not exceed 100000" >&2
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
SET statement_timeout = '5min';
SELECT ops_and_admin.ensure_publication_metric_partition(
           (date_trunc('month', current_date)
              + make_interval(months => offset_month))::date
       ) AS ensured_partition
  FROM generate_series(0, CAST(:'partitions_ahead' AS integer)) AS offsets(offset_month);

SELECT jsonb_build_object(
    'databaseBytes', pg_database_size(current_database()),
    'pendingOutbox', (
        SELECT count(*) FROM ops_and_admin.outbox_event
         WHERE published_at IS NULL
    ),
    'defaultPublicationSnapshots', (
        SELECT count(*) FROM ingest.publication_metric_snapshot_default
    ),
    'defaultReactionRows', (
        SELECT count(*) FROM ingest.reaction_breakdown_default
    ),
    'oldestPendingOutboxAt', (
        SELECT min(occurred_at) FROM ops_and_admin.outbox_event
         WHERE published_at IS NULL
    )
) AS maintenance_observation;
SQL

if [[ "$MAINTENANCE_ENABLE_RAW_PURGE" == false ]]; then
  echo "raw payload purge is disabled; no rows deleted"
  exit 0
fi

total_deleted=0
for (( batch = 1; batch <= MAINTENANCE_RAW_PURGE_MAX_BATCHES; batch++ )); do
  deleted="$(
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
