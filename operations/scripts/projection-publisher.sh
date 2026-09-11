#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

if [[ "${1:-}" == "--once" && $# -eq 1 ]]; then
  :
else
  echo "usage: $0 --once" >&2
  exit 64
fi

: "${PROJECTION_DATABASE_URL:?PROJECTION_DATABASE_URL is required}"
: "${PGPASSFILE:?PGPASSFILE is required}"

PROJECTION_CAPACITY_PATH="${PROJECTION_CAPACITY_PATH:?PROJECTION_CAPACITY_PATH is required}"
PROJECTION_CAPACITY_MULTIPLIER="${PROJECTION_CAPACITY_MULTIPLIER:-1}"
PROJECTION_MIN_FREE_BYTES="${PROJECTION_MIN_FREE_BYTES:-5368709120}"
PROJECTION_LOCK_FILE="${PROJECTION_LOCK_FILE:-/run/m-ranked-projection-publisher/publisher.lock}"

for value_name in \
  PROJECTION_CAPACITY_MULTIPLIER PROJECTION_MIN_FREE_BYTES; do
  value="${!value_name}"
  if [[ ! "$value" =~ ^[0-9]+$ || "$value" == 0 ]]; then
    echo "$value_name must be a positive integer" >&2
    exit 64
  fi
done
if [[ ! -f "$PGPASSFILE" || ! -r "$PGPASSFILE" || -L "$PGPASSFILE" ]]; then
  echo "projection database credential is not a readable regular file" >&2
  exit 77
fi
if [[ "$PROJECTION_CAPACITY_PATH" != /* || ! -d "$PROJECTION_CAPACITY_PATH" ]]; then
  echo "PROJECTION_CAPACITY_PATH must be an existing absolute directory" >&2
  exit 64
fi
if [[ "$PROJECTION_LOCK_FILE" != /* ]]; then
  echo "PROJECTION_LOCK_FILE must be absolute" >&2
  exit 64
fi
for command_name in psql df awk flock dirname; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "required command is missing: $command_name" >&2
    exit 69
  fi
done

lock_parent="$(dirname -- "$PROJECTION_LOCK_FILE")"
if [[ ! -d "$lock_parent" ]]; then
  echo "projection lock directory does not exist: $lock_parent" >&2
  exit 73
fi
exec 9>"$PROJECTION_LOCK_FILE"
if ! flock -n 9; then
  echo "another projection publication is already active" >&2
  exit 75
fi

schema_contract="$(
  psql "$PROJECTION_DATABASE_URL" --no-psqlrc --set ON_ERROR_STOP=1 \
    --quiet --tuples-only --no-align \
    --command 'SELECT contract_id FROM ops_and_admin.schema_contract'
)"
if [[ "$schema_contract" != storage-publisher-final-2026-09-08-r2 ]]; then
  echo "database schema contract mismatch" >&2
  exit 65
fi

inspect_latest() {
  psql "$PROJECTION_DATABASE_URL" \
    --no-psqlrc --set ON_ERROR_STOP=1 --quiet \
    --tuples-only --no-align --field-separator='|' <<'SQL'
WITH latest_revision AS (
    SELECT max(id) AS id FROM analytics.dataset_revision
), core_projection(projection_name) AS (VALUES
    ('publication_latest'),
    ('publication_hourly'),
    ('institution_daily_metrics'),
    ('institution_monthly_metrics'),
    ('institution_period_metrics'),
    ('comparison'),
    ('publication_history')
), readiness AS (
    SELECT revision.id,
           count(state.projection_name) AS ready_count
      FROM latest_revision AS revision
     CROSS JOIN core_projection AS core
      LEFT JOIN analytics.projection_state AS state
        ON state.projection_name = core.projection_name
       AND state.dataset_revision_id = revision.id
       AND state.status = 'ready'
     GROUP BY revision.id
), publisher_state AS (
    SELECT readiness.id,
           readiness.ready_count,
           (
               SELECT count(*)
                 FROM analytics.projection_state AS candidate
                WHERE candidate.projection_name IN (
                    SELECT projection_name FROM core_projection
                )
           ) AS state_count,
           (
               SELECT count(*)
                 FROM ops_and_admin.outbox_event AS event
                WHERE event.event_type = 'projection.rebuild.requested'
                  AND event.published_at IS NULL
                  AND event.dataset_revision_id <= readiness.id
           ) AS request_count
      FROM readiness
)
SELECT CASE
           WHEN id IS NULL THEN 'idle'
           WHEN ready_count = 7 AND state_count = 7 AND request_count = 0 THEN 'ready'
           WHEN ready_count = 7 AND state_count = 7 THEN 'finalize'
           ELSE 'publish'
       END,
       coalesce(id, 0),
       ready_count,
       request_count
  FROM publisher_state;
SQL
}

capacity_guard() {
  local available_kib
  local estimate
  local accepted available_bytes source_heap source_indexes old_heap old_indexes
  local new_heap new_indexes temp_bytes wal_bytes dynamic_bytes required_bytes extra
  available_kib="$(
    df -Pk -- "$PROJECTION_CAPACITY_PATH" \
      | awk 'NR == 2 { print $4 }'
  )"
  if [[ ! "$available_kib" =~ ^[0-9]+$ ]]; then
    echo "cannot determine projection filesystem capacity" >&2
    return 70
  fi

  # Use PostgreSQL numeric arithmetic so a huge configured multiplier cannot
  # overflow Bash signed integers and turn the guard into a fail-open check.
  estimate="$(
    psql "$PROJECTION_DATABASE_URL" \
      --no-psqlrc --set ON_ERROR_STOP=1 --quiet \
      --tuples-only --no-align --field-separator='|' \
      --set capacity_multiplier="$PROJECTION_CAPACITY_MULTIPLIER" \
      --set min_free_bytes="$PROJECTION_MIN_FREE_BYTES" \
      --set available_kib="$available_kib" <<'SQL'
WITH source_root(schema_name, relation_name) AS (VALUES
    ('ingest', 'publication_metric_snapshot'),
    ('ingest', 'account_metric_snapshot'),
    ('ingest', 'reaction_breakdown'),
    ('ingest', 'deletion_observation')
), serving_root(schema_name, relation_name) AS (VALUES
    ('analytics', 'publication_latest'),
    ('analytics', 'publication_hourly'),
    ('analytics', 'institution_daily_metrics'),
    ('analytics', 'institution_monthly_metrics'),
    ('analytics', 'institution_period_metrics'),
    ('analytics', 'comparison_cohort'),
    ('analytics', 'comparison_cohort_member'),
    ('analytics', 'comparison_metric_point'),
    ('analytics', 'comparison_publication_hourly'),
    ('analytics', 'legacy_overview_account'),
    ('analytics', 'legacy_overview_card'),
    ('analytics', 'account_latest'),
    ('analytics', 'publication_history')
), roots AS (
    SELECT 'source' AS class, source_root.* FROM source_root
    UNION ALL
    SELECT 'serving', serving_root.* FROM serving_root
), relation_oid AS (
    SELECT DISTINCT roots.class, coalesce(tree.relid, root.oid) AS oid
      FROM roots
      JOIN pg_namespace AS namespace ON namespace.nspname = roots.schema_name
      JOIN pg_class AS root
        ON root.relnamespace = namespace.oid
       AND root.relname = roots.relation_name
      LEFT JOIN LATERAL pg_partition_tree(root.oid) AS tree ON true
), measured AS (
    SELECT class,
           coalesce(sum(pg_table_size(oid)), 0)::numeric AS heap_bytes,
           coalesce(sum(pg_indexes_size(oid)), 0)::numeric AS index_bytes
      FROM relation_oid
     GROUP BY class
), components AS (
    SELECT coalesce((SELECT heap_bytes FROM measured WHERE class='source'),0) AS source_heap,
           coalesce((SELECT index_bytes FROM measured WHERE class='source'),0) AS source_indexes,
           coalesce((SELECT heap_bytes FROM measured WHERE class='serving'),0) AS old_heap,
           coalesce((SELECT index_bytes FROM measured WHERE class='serving'),0) AS old_indexes
), estimate AS (
    SELECT *, greatest(old_heap, source_heap) AS new_heap,
           greatest(old_indexes, source_indexes) AS new_indexes,
           source_heap + source_indexes AS temp_bytes
      FROM components
), total AS (
    SELECT *, old_heap + old_indexes + new_heap + new_indexes AS wal_bytes
      FROM estimate
), required AS (
    SELECT *, old_heap + old_indexes + new_heap + new_indexes + temp_bytes + wal_bytes AS dynamic_bytes
      FROM total
)
SELECT CASE WHEN :'available_kib'::numeric * 1024 >=
                      dynamic_bytes * :'capacity_multiplier'::numeric
                      + :'min_free_bytes'::numeric
            THEN 'true' ELSE 'false' END,
       (:'available_kib'::numeric * 1024)::text,
       source_heap::text, source_indexes::text, old_heap::text, old_indexes::text,
       new_heap::text, new_indexes::text, temp_bytes::text, wal_bytes::text,
       dynamic_bytes::text,
       (dynamic_bytes * :'capacity_multiplier'::numeric
          + :'min_free_bytes'::numeric)::text
  FROM required;
SQL
  )" || {
    echo "projection capacity estimate failed closed" >&2
    return 70
  }
  IFS='|' read -r accepted available_bytes source_heap source_indexes old_heap \
    old_indexes new_heap new_indexes temp_bytes wal_bytes dynamic_bytes \
    required_bytes extra <<<"$estimate"
  for value in "$available_bytes" "$source_heap" "$source_indexes" "$old_heap" \
    "$old_indexes" "$new_heap" "$new_indexes" "$temp_bytes" "$wal_bytes" \
    "$dynamic_bytes" "$required_bytes"; do
    if [[ ! "$value" =~ ^[0-9]+$ ]]; then
      echo "projection capacity estimate returned an invalid value" >&2
      return 70
    fi
  done
  if [[ -n "${extra:-}" || ( "$accepted" != true && "$accepted" != false ) ]]; then
    echo "projection capacity estimate returned an invalid envelope" >&2
    return 70
  fi
  if [[ "$accepted" != true ]]; then
    echo "projection capacity guard refused rebuild required_bytes=$required_bytes available_bytes=$available_bytes old_heap_bytes=$old_heap old_index_bytes=$old_indexes new_heap_bytes=$new_heap new_index_bytes=$new_indexes temp_bytes=$temp_bytes wal_bytes=$wal_bytes reserve_bytes=$PROJECTION_MIN_FREE_BYTES" >&2
    return 75
  fi
  echo "projection capacity accepted required_bytes=$required_bytes available_bytes=$available_bytes old_heap_bytes=$old_heap old_index_bytes=$old_indexes new_heap_bytes=$new_heap new_index_bytes=$new_indexes temp_bytes=$temp_bytes wal_bytes=$wal_bytes reserve_bytes=$PROJECTION_MIN_FREE_BYTES"
}

publish_revision() {
  local revision="$1"
  local needs_rebuild="$2"
  psql "$PROJECTION_DATABASE_URL" \
    --no-psqlrc --set ON_ERROR_STOP=1 --quiet \
    --tuples-only --no-align --set revision="$revision" \
    --set needs_rebuild="$needs_rebuild" <<'SQL'
BEGIN;
\if :needs_rebuild
SELECT analytics.rebuild_serving_projections(CAST(:'revision' AS bigint))::text
       AS rebuild_result \gset
\else
SELECT '{}'::text AS rebuild_result \gset
\endif

WITH core_projection(projection_name) AS (VALUES
    ('publication_latest'),
    ('publication_hourly'),
    ('institution_daily_metrics'),
    ('institution_monthly_metrics'),
    ('institution_period_metrics'),
    ('comparison'),
    ('publication_history')
)
SELECT (
           count(state.projection_name) = 7
       ) AS core_ready
  FROM core_projection AS core
  LEFT JOIN analytics.projection_state AS state
    ON state.projection_name = core.projection_name
   AND state.dataset_revision_id = CAST(:'revision' AS bigint)
   AND state.status = 'ready'
\gset

\if :core_ready
INSERT INTO ops_and_admin.outbox_event(
    dataset_revision_id, event_type, aggregate_type, aggregate_id,
    affected_tags, payload
)
VALUES (
    CAST(:'revision' AS bigint),
    'dataset.revision.changed',
    'projection',
    'core',
    ARRAY['publications', 'overview', 'comparison'],
    jsonb_build_object(
        'revision', CAST(:'revision' AS bigint),
        'projectionCount', 7
    )
)
ON CONFLICT (dataset_revision_id, event_type, aggregate_type, aggregate_id)
DO NOTHING;

INSERT INTO ops_and_admin.outbox_event(
    dataset_revision_id, event_type, aggregate_type, aggregate_id,
    affected_tags, payload, published_at
)
VALUES (
    CAST(:'revision' AS bigint),
    'projection.published',
    'projection',
    'core',
    ARRAY['publications', 'overview', 'comparison'],
    jsonb_build_object(
        'revision', CAST(:'revision' AS bigint),
        'projectionCount', 7
    ),
    transaction_timestamp()
)
ON CONFLICT (dataset_revision_id, event_type, aggregate_type, aggregate_id)
DO NOTHING;

UPDATE ops_and_admin.outbox_event
   SET published_at = transaction_timestamp(),
       available_at = transaction_timestamp(),
       last_error_code = NULL
 WHERE event_type = 'projection.rebuild.requested'
   AND published_at IS NULL
   AND dataset_revision_id <= CAST(:'revision' AS bigint);

COMMIT;
\echo :rebuild_result
\else
ROLLBACK;
\quit 75
\endif
SQL
}

if ! state="$(inspect_latest)"; then
  echo "projection readiness inspection failed" >&2
  exit 75
fi

  IFS='|' read -r action revision ready_count request_count extra <<<"$state"
  if [[ -n "${extra:-}" \
        || ( "$action" != idle && "$action" != ready \
             && "$action" != finalize && "$action" != publish ) \
        || ! "$revision" =~ ^[0-9]+$ \
        || ! "$ready_count" =~ ^[0-9]$ \
        || ! "$request_count" =~ ^[0-9]+$ \
        || ( ( "$action" == ready || "$action" == finalize ) && "$ready_count" != 7 ) ]]; then
    echo "projection readiness query returned an invalid envelope" >&2
    exit 70
  fi

case "$action" in
    idle)
      echo "projection publisher idle: no dataset revision"
      exit 0
      ;;
    ready)
      echo "core projections already ready revision=$revision"
      exit 0
      ;;
    finalize|publish)
      if [[ ! "$revision" =~ ^[1-9][0-9]*$ ]]; then
        echo "refusing to publish an invalid dataset revision" >&2
        exit 70
      fi
      needs_rebuild=false
      if [[ "$action" == publish ]]; then
        needs_rebuild=true
        capacity_guard
      fi
      if result="$(publish_revision "$revision" "$needs_rebuild")"; then
        echo "published core projections revision=$revision rebuilt=$needs_rebuild result=$result"
        exit 0
      fi
      echo "projection publish revision=$revision failed; no automatic retry was attempted" >&2
      exit 75
      ;;
esac
