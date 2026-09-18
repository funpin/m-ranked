#!/usr/bin/env bash
# Restart a collector only when its durable account/run progress is stale.
set -Eeuo pipefail

CONTAINER=${WATCHDOG_DB_CONTAINER:-mranked-production-postgres-1}
DB_USER=${WATCHDOG_DB_USER:-mranked_bootstrap}
DB_NAME=${WATCHDOG_DB_NAME:-mranked}
STARTUP_GRACE_MINUTES=${WATCHDOG_STARTUP_GRACE_MINUTES:-15}
PLATFORMS=(telegram vk max rutube)

require_minutes() {
  local name=$1 value=$2
  if [[ ! $value =~ ^[1-9][0-9]*$ ]]; then
    echo "$name must be a positive integer" >&2
    exit 2
  fi
}

threshold_minutes() {
  local platform=$1 variable default
  case "$platform" in
    telegram) variable=WATCHDOG_TELEGRAM_STALE_MINUTES; default=45 ;;
    vk)       variable=WATCHDOG_VK_STALE_MINUTES;       default=45 ;;
    max)      variable=WATCHDOG_MAX_STALE_MINUTES;      default=45 ;;
    rutube)   variable=WATCHDOG_RUTUBE_STALE_MINUTES;   default=90 ;;
    *) echo "unsupported platform: $platform" >&2; exit 2 ;;
  esac
  printf '%s\n' "${!variable:-$default}"
}

unit_uptime_minutes() {
  local unit=$1 active_us uptime_seconds now_us
  active_us=$(systemctl show "$unit" --property=ActiveEnterTimestampMonotonic --value)
  # Linux exposes monotonic boot time through /proc. Tests on non-Linux hosts
  # inject the same value without changing production configuration.
  if [[ -n ${WATCHDOG_TEST_MONOTONIC_SECONDS:-} ]]; then
    uptime_seconds=$WATCHDOG_TEST_MONOTONIC_SECONDS
  else
    read -r uptime_seconds _ </proc/uptime
    uptime_seconds=${uptime_seconds%%.*}
  fi
  if [[ ! $active_us =~ ^[0-9]+$ ]] || (( active_us == 0 )); then
    printf '0\n'
    return
  fi
  now_us=$((uptime_seconds * 1000000))
  if (( now_us <= active_us )); then
    printf '0\n'
  else
    printf '%s\n' "$(((now_us - active_us) / 60000000))"
  fi
}

progress_age_minutes() {
  local platform=$1
  # psql expands :'variables' only while reading a script. --set therefore
  # safely quotes the platform as a SQL literal when the query comes from stdin.
  docker exec -i "$CONTAINER" psql \
    --username "$DB_USER" --dbname "$DB_NAME" --no-psqlrc \
    --set ON_ERROR_STOP=1 --set "platform=$platform" \
    --tuples-only --no-align --file=- <<'SQL' | tail -n 1
      SET statement_timeout='5s';
      SET lock_timeout='1s';
      SET default_transaction_read_only=on;
      WITH progress AS (
        SELECT result.completed_at AS happened_at
          FROM ingest.collection_account_result AS result
          JOIN ingest.collection_run AS run
            ON run.id=result.collection_run_id
         WHERE run.platform=:'platform'::catalog.platform_code
           AND result.completed_at IS NOT NULL
        UNION ALL
        SELECT completed_at
          FROM ingest.collection_run
         WHERE platform=:'platform'::catalog.platform_code
           AND completed_at IS NOT NULL
      )
      SELECT coalesce(
        floor(extract(epoch FROM now()-max(happened_at))/60)::bigint::text,
        'never'
      )
      FROM progress;
SQL
}

require_minutes WATCHDOG_STARTUP_GRACE_MINUTES "$STARTUP_GRACE_MINUTES"
restarted=0
for platform in "${PLATFORMS[@]}"; do
  unit="m-ranked-target-collector@${platform}.service"
  threshold=$(threshold_minutes "$platform")
  require_minutes "watchdog threshold for $platform" "$threshold"

  if ! systemctl is-active --quiet "$unit"; then
    echo "collector $platform is not active; restarting $unit"
    systemctl restart "$unit"
    restarted=$((restarted + 1))
    continue
  fi

  uptime=$(unit_uptime_minutes "$unit")
  if (( uptime < STARTUP_GRACE_MINUTES )); then
    echo "collector $platform is inside ${STARTUP_GRACE_MINUTES}m startup grace"
    continue
  fi

  age=$(progress_age_minutes "$platform")
  stale=false
  if [[ $age == never ]]; then
    stale=true
  elif [[ ! $age =~ ^[0-9]+$ ]]; then
    echo "collector $platform returned invalid progress age: $age" >&2
    exit 1
  elif (( age >= threshold )); then
    stale=true
  fi
  if [[ $stale == true ]]; then
    echo "collector $platform has no durable progress for ${age}m (limit ${threshold}m); restarting $unit"
    systemctl restart "$unit"
    restarted=$((restarted + 1))
  else
    echo "collector $platform progress age ${age}m is below ${threshold}m"
  fi
done

echo "collector watchdog completed: restarted=$restarted"
