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
MAINTENANCE_ENABLE_REVISION_PURGE="${MAINTENANCE_ENABLE_REVISION_PURGE:-false}"
MAINTENANCE_ENABLE_SITE_SUMMARY="${MAINTENANCE_ENABLE_SITE_SUMMARY:-true}"
MAINTENANCE_SITE_SUMMARY_MAX_AGE_HOURS="${MAINTENANCE_SITE_SUMMARY_MAX_AGE_HOURS:-23}"
MAINTENANCE_REVISION_BATCH_SIZE="${MAINTENANCE_REVISION_BATCH_SIZE:-5000}"
MAINTENANCE_REVISION_MAX_BATCHES="${MAINTENANCE_REVISION_MAX_BATCHES:-20}"
MAINTENANCE_REVISION_MAX_SECONDS="${MAINTENANCE_REVISION_MAX_SECONDS:-60}"
MAINTENANCE_REVISION_KEEP_DAYS="${MAINTENANCE_REVISION_KEEP_DAYS:-7}"
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
if [[ "$MAINTENANCE_ENABLE_REVISION_PURGE" != true && "$MAINTENANCE_ENABLE_REVISION_PURGE" != false ]]; then
  echo "MAINTENANCE_ENABLE_REVISION_PURGE must be true or false" >&2; exit 64
fi
for name in MAINTENANCE_REVISION_BATCH_SIZE MAINTENANCE_REVISION_MAX_BATCHES MAINTENANCE_REVISION_MAX_SECONDS MAINTENANCE_REVISION_KEEP_DAYS; do
  value="${!name}"
  if [[ ! "$value" =~ ^[1-9][0-9]{0,4}$ ]] || (( value > 20000 )); then
    echo "$name must be between 1 and 20000" >&2; exit 64
  fi
done
if (( MAINTENANCE_REVISION_MAX_SECONDS > 120 || MAINTENANCE_REVISION_MAX_BATCHES > 100 || MAINTENANCE_REVISION_KEEP_DAYS < 2 )); then
  echo "revision purge budget exceeds 120 seconds / 100 batches, or keeps under 2 days" >&2; exit 64
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
fi

# Старые ревизии набора данных (0042): ~57 тысяч строк в сутки, без очистки
# росли бесконечно. Порции коммитятся по одной; ревизия, на которую ещё
# ссылаются витрины или очередь, остаётся. Индексы — storage-indexes.sql.
if [[ "$MAINTENANCE_ENABLE_REVISION_PURGE" == true ]]; then
  began=$SECONDS
  total_revisions=0
  for ((batch=0; batch<MAINTENANCE_REVISION_MAX_BATCHES; batch++)); do
    (( SECONDS - began < MAINTENANCE_REVISION_MAX_SECONDS )) || break
    deleted="$(PGOPTIONS='-c lock_timeout=1s -c statement_timeout=20s' \
      psql "$MAINTENANCE_DATABASE_URL" -X -v ON_ERROR_STOP=1 -At \
      -v batch_size="$MAINTENANCE_REVISION_BATCH_SIZE" -v keep_days="$MAINTENANCE_REVISION_KEEP_DAYS" <<'SQL'
SELECT ops_and_admin.purge_old_dataset_revisions(make_interval(days => :'keep_days'::integer), :'batch_size'::integer);
SQL
    )"
    [[ "$deleted" =~ ^[0-9]+$ ]] || { echo "invalid revision purge result" >&2; exit 70; }
    total_revisions=$((total_revisions + deleted))
    (( deleted == MAINTENANCE_REVISION_BATCH_SIZE )) || break
  done
  echo "dataset revision purge completed rows=$total_revisions elapsed=$((SECONDS-began))"
fi

# Сводка главной (0044): раз в сутки, остальные прогоны — одна проверка.
if [[ "$MAINTENANCE_ENABLE_SITE_SUMMARY" == true ]]; then
  if [[ ! "$MAINTENANCE_SITE_SUMMARY_MAX_AGE_HOURS" =~ ^[1-9][0-9]{0,2}$ ]]; then
    echo "MAINTENANCE_SITE_SUMMARY_MAX_AGE_HOURS must be between 1 and 999" >&2; exit 64
  fi
  script_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
  refreshed="$(psql "$MAINTENANCE_DATABASE_URL" -X -q -v ON_ERROR_STOP=1 -At \
    -v max_age_hours="$MAINTENANCE_SITE_SUMMARY_MAX_AGE_HOURS" \
    -f "$script_root/db/tools/refresh-site-summary.sql" | tail -n 1)"
  if [[ -n "$refreshed" ]]; then
    echo "site summary refreshed at=$refreshed"
  fi
fi

if [[ -n "${MAINTENANCE_METRICS_FILE:-}" ]]; then
  python3 - "$MAINTENANCE_METRICS_FILE" "${total_outbox:-}" "${total_revisions:-}" <<'PYMETRICS'
import os, pathlib, sys, tempfile, time
path=pathlib.Path(sys.argv[1])
fd,name=tempfile.mkstemp(prefix='.maintenance-',dir=path.parent)
try:
    with os.fdopen(fd,'w') as stream:
        now = time.time()
        if sys.argv[2]:
            stream.write(f'mranked_cache_outbox_cleanup_last_success_unixtime {now}\n')
            stream.write(f'mranked_cache_outbox_cleanup_last_rows {int(sys.argv[2])}\n')
        if sys.argv[3]:
            stream.write(f'mranked_dataset_revision_cleanup_last_success_unixtime {now}\n')
            stream.write(f'mranked_dataset_revision_cleanup_last_rows {int(sys.argv[3])}\n')
        os.fchmod(stream.fileno(),0o644)
    os.replace(name,path)
finally:
    pathlib.Path(name).unlink(missing_ok=True)
PYMETRICS
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
