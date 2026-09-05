#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

once=false
if [[ "${1:-}" == "--once" && $# -eq 1 ]]; then
  once=true
elif [[ $# -ne 0 ]]; then
  echo "usage: $0 [--once]" >&2
  exit 64
fi

: "${PROJECTION_DATABASE_URL:?PROJECTION_DATABASE_URL is required}"
: "${PGPASSFILE:?PGPASSFILE is required}"

PROJECTION_POLL_SECONDS="${PROJECTION_POLL_SECONDS:-2}"
PROJECTION_MAX_BACKOFF_SECONDS="${PROJECTION_MAX_BACKOFF_SECONDS:-60}"
PROJECTION_ONCE_MAX_ATTEMPTS="${PROJECTION_ONCE_MAX_ATTEMPTS:-5}"

for value_name in \
  PROJECTION_POLL_SECONDS PROJECTION_MAX_BACKOFF_SECONDS \
  PROJECTION_ONCE_MAX_ATTEMPTS; do
  value="${!value_name}"
  if [[ ! "$value" =~ ^[1-9][0-9]*$ ]]; then
    echo "$value_name must be a positive integer" >&2
    exit 64
  fi
done
if (( PROJECTION_MAX_BACKOFF_SECONDS > 900 )); then
  echo "PROJECTION_MAX_BACKOFF_SECONDS must not exceed 900" >&2
  exit 64
fi
if (( PROJECTION_ONCE_MAX_ATTEMPTS > 20 )); then
  echo "PROJECTION_ONCE_MAX_ATTEMPTS must not exceed 20" >&2
  exit 64
fi
if [[ ! -f "$PGPASSFILE" || ! -r "$PGPASSFILE" || -L "$PGPASSFILE" ]]; then
  echo "projection database credential is not a readable regular file" >&2
  exit 77
fi
for command_name in psql sleep; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "required command is missing: $command_name" >&2
    exit 69
  fi
done

stopping=false
trap 'stopping=true' TERM INT

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
    ('comparison')
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
                 FROM ops_and_admin.outbox_event AS event
                WHERE event.event_type = 'projection.rebuild.requested'
                  AND event.published_at IS NULL
                  AND event.dataset_revision_id <= readiness.id
           ) AS request_count
      FROM readiness
)
SELECT CASE
           WHEN id IS NULL THEN 'idle'
           WHEN ready_count = 6 AND request_count = 0 THEN 'ready'
           WHEN ready_count = 6 THEN 'finalize'
           ELSE 'publish'
       END,
       coalesce(id, 0),
       ready_count,
       request_count
  FROM publisher_state;
SQL
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
SELECT analytics.rebuild_core_projections(CAST(:'revision' AS bigint))::text
       AS rebuild_result \gset
\else
SELECT '{}'::text AS rebuild_result \gset
\endif

WITH latest_revision AS (
    SELECT max(id) AS id FROM analytics.dataset_revision
), core_projection(projection_name) AS (VALUES
    ('publication_latest'),
    ('publication_hourly'),
    ('institution_daily_metrics'),
    ('institution_monthly_metrics'),
    ('institution_period_metrics'),
    ('comparison')
)
SELECT (
           revision.id = CAST(:'revision' AS bigint)
           AND count(state.projection_name) = 6
       ) AS core_ready
  FROM latest_revision AS revision
 CROSS JOIN core_projection AS core
  LEFT JOIN analytics.projection_state AS state
    ON state.projection_name = core.projection_name
   AND state.dataset_revision_id = revision.id
   AND state.status = 'ready'
 GROUP BY revision.id
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
        'projectionCount', 6
    )
)
ON CONFLICT (dataset_revision_id, event_type, aggregate_type, aggregate_id)
DO NOTHING;

INSERT INTO ops_and_admin.outbox_event(
    dataset_revision_id, event_type, aggregate_type, aggregate_id,
    affected_tags, payload
)
VALUES (
    CAST(:'revision' AS bigint),
    'projection.published',
    'projection',
    'core',
    ARRAY['publications', 'overview', 'comparison'],
    jsonb_build_object(
        'revision', CAST(:'revision' AS bigint),
        'projectionCount', 6
    )
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

backoff_seconds() {
  local failures="$1"
  local delay=$(( failures * failures ))
  if (( delay > PROJECTION_MAX_BACKOFF_SECONDS )); then
    delay="$PROJECTION_MAX_BACKOFF_SECONDS"
  fi
  echo "$delay"
}

failure_count=0
once_attempts=0
while [[ "$stopping" == false ]]; do
  if [[ "$once" == true ]]; then
    once_attempts=$((once_attempts + 1))
    if (( once_attempts > PROJECTION_ONCE_MAX_ATTEMPTS )); then
      echo "latest projection revision did not stabilize after ${PROJECTION_ONCE_MAX_ATTEMPTS} attempts" >&2
      exit 75
    fi
  fi

  if ! state="$(inspect_latest)"; then
    failure_count=$((failure_count + 1))
    if [[ "$once" == true && "$once_attempts" -ge "$PROJECTION_ONCE_MAX_ATTEMPTS" ]]; then
      echo "projection readiness inspection failed after ${once_attempts} attempts" >&2
      exit 75
    fi
    delay="$(backoff_seconds "$failure_count")"
    echo "projection readiness inspection failed; retrying in ${delay}s" >&2
    sleep "$delay"
    continue
  fi

  IFS='|' read -r action revision ready_count request_count extra <<<"$state"
  if [[ -n "${extra:-}" \
        || ( "$action" != idle && "$action" != ready \
             && "$action" != finalize && "$action" != publish ) \
        || ! "$revision" =~ ^[0-9]+$ \
        || ! "$ready_count" =~ ^[0-6]$ \
        || ! "$request_count" =~ ^[0-9]+$ ]]; then
    echo "projection readiness query returned an invalid envelope" >&2
    exit 70
  fi

  case "$action" in
    idle)
      failure_count=0
      if [[ "$once" == true ]]; then
        echo "projection publisher idle: no dataset revision"
        exit 0
      fi
      sleep "$PROJECTION_POLL_SECONDS"
      ;;
    ready)
      failure_count=0
      if [[ "$once" == true ]]; then
        echo "core projections already ready revision=$revision"
        exit 0
      fi
      sleep "$PROJECTION_POLL_SECONDS"
      ;;
    finalize|publish)
      if [[ ! "$revision" =~ ^[1-9][0-9]*$ ]]; then
        echo "refusing to publish an invalid dataset revision" >&2
        exit 70
      fi
      needs_rebuild=false
      if [[ "$action" == publish ]]; then
        needs_rebuild=true
      fi
      if result="$(publish_revision "$revision" "$needs_rebuild")"; then
        failure_count=0
        echo "published core projections revision=$revision rebuilt=$needs_rebuild result=$result"
        # Re-read immediately. A collector may have committed while this
        # rebuild held the dataset-revision table lock; coalesce that newer
        # revision before --once succeeds or the daemon sleeps.
        continue
      fi
      failure_count=$((failure_count + 1))
      if [[ "$once" == true && "$once_attempts" -ge "$PROJECTION_ONCE_MAX_ATTEMPTS" ]]; then
        echo "projection publish failed after ${once_attempts} attempts" >&2
        exit 75
      fi
      delay="$(backoff_seconds "$failure_count")"
      echo "projection publish revision=$revision failed or lost a latest-revision race; retrying in ${delay}s" >&2
      sleep "$delay"
      ;;
  esac
done
