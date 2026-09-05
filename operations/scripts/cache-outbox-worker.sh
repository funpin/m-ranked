#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

once=false
if [[ "${1:-}" == "--once" ]]; then
  once=true
elif [[ $# -ne 0 ]]; then
  echo "usage: $0 [--once]" >&2
  exit 64
fi

: "${OUTBOX_DATABASE_URL:?OUTBOX_DATABASE_URL is required}"
: "${PGPASSFILE:?PGPASSFILE is required}"
: "${REDIS_PASSWORD_FILE:?REDIS_PASSWORD_FILE is required}"

REDIS_HOST="${REDIS_HOST:-127.0.0.1}"
REDIS_PORT="${REDIS_PORT:-6379}"
REDIS_REVISION_KEY="${REDIS_REVISION_KEY:-mranked:dataset_revision}"
REDIS_REVISION_CHANNEL="${REDIS_REVISION_CHANNEL:-mranked:revision.changed}"
OUTBOX_POLL_SECONDS="${OUTBOX_POLL_SECONDS:-2}"
OUTBOX_CLAIM_SECONDS="${OUTBOX_CLAIM_SECONDS:-30}"
OUTBOX_MAX_BACKOFF_SECONDS="${OUTBOX_MAX_BACKOFF_SECONDS:-900}"

for value_name in OUTBOX_POLL_SECONDS OUTBOX_CLAIM_SECONDS OUTBOX_MAX_BACKOFF_SECONDS; do
  value="${!value_name}"
  if [[ ! "$value" =~ ^[1-9][0-9]*$ ]]; then
    echo "$value_name must be a positive integer" >&2
    exit 64
  fi
done

for command_name in psql redis-cli base64 sleep; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "required command is missing: $command_name" >&2
    exit 69
  fi
done

if [[ ! -r "$PGPASSFILE" || ! -r "$REDIS_PASSWORD_FILE" ]]; then
  echo "database or Redis credential is not readable" >&2
  exit 77
fi

redis_password="$(<"$REDIS_PASSWORD_FILE")"
if [[ -z "$redis_password" ]]; then
  echo "Redis credential is empty" >&2
  exit 77
fi

stopping=false
trap 'stopping=true' TERM INT

claim_event() {
  psql "$OUTBOX_DATABASE_URL" \
    --no-psqlrc --set ON_ERROR_STOP=1 --set claim_seconds="$OUTBOX_CLAIM_SECONDS" \
    --tuples-only --no-align --field-separator=$'\t' <<'SQL'
WITH candidate AS (
    SELECT id
      FROM ops_and_admin.outbox_event
     WHERE published_at IS NULL
       AND available_at <= transaction_timestamp()
       AND event_type <> 'projection.rebuild.requested'
     ORDER BY available_at, id
     FOR UPDATE SKIP LOCKED
     LIMIT 1
), claimed AS (
    UPDATE ops_and_admin.outbox_event AS event
       SET publish_attempts = event.publish_attempts + 1,
           available_at = transaction_timestamp()
               + make_interval(secs => CAST(:'claim_seconds' AS integer)),
           last_error_code = NULL
      FROM candidate
     WHERE event.id = candidate.id
    RETURNING event.id, event.dataset_revision_id, event.event_type,
              event.aggregate_type, event.aggregate_id, event.affected_tags,
              event.payload, event.occurred_at
)
SELECT id::text,
       dataset_revision_id::text,
       event_type,
       replace(
           encode(
               convert_to(
                   jsonb_build_object(
                       'id', id,
                       'datasetRevisionId', dataset_revision_id,
                       'eventType', event_type,
                       'aggregateType', aggregate_type,
                       'aggregateId', aggregate_id,
                       'affectedTags', affected_tags,
                       'payload', payload,
                       'occurredAt', occurred_at
                   )::text,
                   'UTF8'
               ),
               'base64'
           ),
           E'\n',
           ''
       )
  FROM claimed;
SQL
}

mark_success() {
  local event_id="$1"
  psql "$OUTBOX_DATABASE_URL" --no-psqlrc --set ON_ERROR_STOP=1 \
    --set event_id="$event_id" --quiet <<'SQL'
UPDATE ops_and_admin.outbox_event
   SET published_at = transaction_timestamp(),
       available_at = transaction_timestamp(),
       last_error_code = NULL
 WHERE id = CAST(:'event_id' AS bigint)
   AND published_at IS NULL;
SQL
}

mark_failure() {
  local event_id="$1"
  psql "$OUTBOX_DATABASE_URL" --no-psqlrc --set ON_ERROR_STOP=1 \
    --set event_id="$event_id" --set max_backoff="$OUTBOX_MAX_BACKOFF_SECONDS" \
    --quiet <<'SQL'
UPDATE ops_and_admin.outbox_event
   SET last_error_code = 'redis_unavailable',
       available_at = transaction_timestamp() + make_interval(
           secs => least(
               CAST(:'max_backoff' AS integer),
               greatest(5, publish_attempts * publish_attempts * 5)
           )
       )
 WHERE id = CAST(:'event_id' AS bigint)
   AND published_at IS NULL;
SQL
}

publish_event() {
  local revision="$1"
  local encoded_payload="$2"
  local payload
  payload="$(printf '%s' "$encoded_payload" | base64 --decode)"

  # Never let a delayed event move the shared revision backwards.
  REDISCLI_AUTH="$redis_password" redis-cli \
    --host "$REDIS_HOST" --port "$REDIS_PORT" --no-auth-warning \
    EVAL \
    "local c=tonumber(redis.call('GET',KEYS[1])); if c==nil then c=-1 end; local n=tonumber(ARGV[1]); if n>c then redis.call('SET',KEYS[1],ARGV[1]); end; return n" \
    1 "$REDIS_REVISION_KEY" "$revision" >/dev/null

  printf '%s' "$payload" | REDISCLI_AUTH="$redis_password" redis-cli \
    --host "$REDIS_HOST" --port "$REDIS_PORT" --no-auth-warning \
    -x PUBLISH "$REDIS_REVISION_CHANNEL" >/dev/null
}

while [[ "$stopping" == false ]]; do
  claimed="$(claim_event)"
  if [[ -z "$claimed" ]]; then
    if [[ "$once" == true ]]; then
      break
    fi
    sleep "$OUTBOX_POLL_SECONDS"
    continue
  fi

  IFS=$'\t' read -r event_id revision event_type encoded_payload <<<"$claimed"
  if [[ ! "$event_id" =~ ^[1-9][0-9]*$ \
        || ! "$revision" =~ ^[1-9][0-9]*$ \
        || ! "$event_type" =~ ^[A-Za-z0-9._-]+$ \
        || -z "$encoded_payload" ]]; then
    echo "outbox claim returned an invalid envelope" >&2
    exit 70
  fi

  if [[ "$event_type" == projection.published ]]; then
    mark_success "$event_id"
    echo "recorded projection publication event id=$event_id revision=$revision"
  elif publish_event "$revision" "$encoded_payload"; then
    mark_success "$event_id"
    echo "published cache revision event id=$event_id revision=$revision"
  else
    mark_failure "$event_id"
    echo "cache revision publish failed id=$event_id revision=$revision" >&2
    if [[ "$once" == true ]]; then
      exit 75
    fi
    sleep "$OUTBOX_POLL_SECONDS"
  fi

  if [[ "$once" == true ]]; then
    break
  fi
done

unset redis_password
