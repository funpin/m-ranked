#!/bin/bash -p
set -Eeuo pipefail

umask 077
PATH=/usr/bin:/bin:/usr/sbin:/sbin
export PATH
unset BASH_ENV CDPATH ENV PYTHONHOME PYTHONPATH TMPDIR __PYVENV_LAUNCHER__

transition_entry_source="${BASH_SOURCE[0]}"
case "$transition_entry_source" in
  /*) ;;
  *) transition_entry_source="$(pwd -P)/$transition_entry_source" ;;
esac
transition_entry_dir="${transition_entry_source%/*}"
transition_entry_name="${transition_entry_source##*/}"
transition_entry_dir="$(cd -- "$transition_entry_dir" && pwd -P)" || {
  echo "cannot resolve writer cutover entrypoint origin" >&2
  exit 73
}
transition_entry_path="$transition_entry_dir/$transition_entry_name"
transition_lock_helper="$transition_entry_dir/transition-lock.sh"
_mranked_bootstrap_stat() {
  /usr/bin/stat -c '%d:%i:%u:%g:%a:%h' -- "$1" 2>/dev/null \
    || /usr/bin/stat -f '%d:%i:%u:%g:%Lp:%l' "$1" 2>/dev/null
}
for transition_secure_file in "$transition_entry_path" "$transition_lock_helper"; do
  transition_metadata="$(_mranked_bootstrap_stat "$transition_secure_file")" \
    || transition_metadata=""
  IFS=: read -r transition_device transition_inode transition_owner \
    transition_group transition_mode transition_links <<<"$transition_metadata"
  if [[ ! -f "$transition_secure_file" || -L "$transition_secure_file" \
        || "$transition_owner" != 0 || "$transition_links" != 1 \
        || ! "$transition_mode" =~ ^[0-7]{3,4}$ ]] \
      || (( (8#$transition_mode & 8#022) != 0 )); then
    echo "writer cutover entrypoint or transition lock helper is unsafe" >&2
    exit 73
  fi
done
transition_helper_identity="$(_mranked_bootstrap_stat "$transition_lock_helper")"
transition_secure_dir="$transition_entry_dir"
while :; do
  transition_metadata="$(_mranked_bootstrap_stat "$transition_secure_dir")" \
    || transition_metadata=""
  IFS=: read -r transition_device transition_inode transition_owner \
    transition_group transition_mode transition_links <<<"$transition_metadata"
  if [[ ! -d "$transition_secure_dir" || -L "$transition_secure_dir" \
        || "$transition_owner" != 0 || ! "$transition_mode" =~ ^[0-7]{3,4}$ ]] \
      || (( (8#$transition_mode & 8#022) != 0 )); then
    echo "writer cutover entrypoint directory chain is unsafe" >&2
    exit 73
  fi
  [[ "$transition_secure_dir" == / ]] && break
  transition_secure_dir="${transition_secure_dir%/*}"
  [[ -n "$transition_secure_dir" ]] || transition_secure_dir=/
done
if [[ ! -r "$transition_lock_helper" ]]; then
  echo "writer cutover entrypoint or transition lock helper is unsafe" >&2
  exit 73
fi
# shellcheck source=operations/scripts/transition-lock.sh
source "$transition_lock_helper"
if [[ "$transition_helper_identity" != "$(_mranked_bootstrap_stat "$transition_lock_helper")" \
      || "$MRANKED_TRANSITION_HELPER_PATH" != "$transition_lock_helper" ]]; then
  echo "transition lock helper changed while it was sourced" >&2
  exit 73
fi
unset -f _mranked_bootstrap_stat
unset transition_secure_file transition_secure_dir transition_metadata \
  transition_device transition_inode transition_owner transition_group \
  transition_mode transition_links transition_helper_identity

confirmation=""
if [[ "${1:-}" == "--confirm" && $# -eq 2 ]]; then
  confirmation="$2"
else
  echo "usage: $0 --confirm WRITER-CUTOVER:<ticket>" >&2
  exit 64
fi

: "${OPERATOR_ID:?OPERATOR_ID is required}"
: "${CHANGE_TICKET:?CHANGE_TICKET is required}"
: "${LEGACY_SQLITE_PATH:?LEGACY_SQLITE_PATH is required}"
: "${MIGRATION_SNAPSHOT_DIR:?MIGRATION_SNAPSHOT_DIR is required}"
: "${MIGRATION_REPORT_DIR:?MIGRATION_REPORT_DIR is required}"
: "${MIGRATION_SOURCE_NAMESPACE:?MIGRATION_SOURCE_NAMESPACE is required}"
: "${MIGRATION_DATABASE_URL:?MIGRATION_DATABASE_URL is required}"
: "${MIGRATION_PGPASSFILE:?MIGRATION_PGPASSFILE is required}"
: "${TARGET_DATABASE_URL:?TARGET_DATABASE_URL is required}"
: "${TARGET_PGPASSFILE:?TARGET_PGPASSFILE is required}"
: "${OUTBOX_DATABASE_URL:?OUTBOX_DATABASE_URL is required}"
: "${OUTBOX_PGPASSFILE:?OUTBOX_PGPASSFILE is required}"
: "${REVERSE_SYNC_EXECUTABLE:?REVERSE_SYNC_EXECUTABLE is required}"
: "${TARGET_API_URL:?TARGET_API_URL is required}"
: "${ROLLBACK_WINDOW_HOURS:=72}"
: "${TARGET_COLLECTION_GATE_SECONDS:=900}"
: "${MRANKED_INSTALL_ROOT:=/opt/m-ranked/releases}"
: "${MRANKED_CURRENT_LINK:=/opt/m-ranked/current}"

if [[ "$confirmation" != "WRITER-CUTOVER:${CHANGE_TICKET}" ]]; then
  echo "confirmation mismatch" >&2
  exit 77
fi
if (( EUID != 0 )); then
  echo "writer cutover must run as root" >&2
  exit 77
fi
mranked_transition_lock_acquire
mranked_transition_require_active_entrypoint "$transition_entry_path"
mranked_transition_require_active_file \
  "$REVERSE_SYNC_EXECUTABLE" operations/bin/pg-to-legacy-sync true

for directory_name in MIGRATION_SNAPSHOT_DIR MIGRATION_REPORT_DIR; do
  directory_path="${!directory_name}"
  case "$directory_path" in
    /var/lib/m-ranked/*) ;;
    *) echo "$directory_name must be below /var/lib/m-ranked" >&2; exit 64 ;;
  esac
  if [[ -L "$directory_path" ]]; then
    echo "$directory_name must not be a symlink" >&2
    exit 73
  fi
done

if [[ ! -f "$LEGACY_SQLITE_PATH" || -L "$LEGACY_SQLITE_PATH" ]]; then
  echo "legacy SQLite source is missing or unsafe" >&2
  exit 66
fi
if [[ ! -r "$MIGRATION_PGPASSFILE" || ! -r "$TARGET_PGPASSFILE" \
      || ! -r "$OUTBOX_PGPASSFILE" || ! -x "$REVERSE_SYNC_EXECUTABLE" ]]; then
  echo "database credential or tested reverse-sync adapter is unavailable" >&2
  exit 77
fi
if [[ ! "$ROLLBACK_WINDOW_HOURS" =~ ^[1-9][0-9]*$ \
      || ! "$TARGET_COLLECTION_GATE_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
  echo "rollback window and collection gate must be positive integers" >&2
  exit 64
fi

for command_name in systemctl psql jq curl date install sha256sum cut sleep; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "required command is missing: $command_name" >&2
    exit 69
  fi
done

script_dir="$transition_entry_dir"
project_root="$(cd -- "$script_dir/../.." && pwd -P)"
python_bin="$project_root/.venv/bin/python"
preflight="$script_dir/cutover-preflight.sh"
route_switch="$script_dir/switch-routing.sh"
if [[ ! -x "$python_bin" ]]; then
  echo "release virtualenv Python is unavailable" >&2
  exit 69
fi
mranked_transition_require_active_file \
  "$preflight" operations/scripts/cutover-preflight.sh true
mranked_transition_require_active_file \
  "$route_switch" operations/scripts/switch-routing.sh true

cutover_mutated=false
reverse_sync_attempted=false
recover_pre_sync_failure() {
  local exit_code=$?
  trap - EXIT
  if (( exit_code != 0 )) && [[ "$cutover_mutated" == true ]]; then
    if [[ "$reverse_sync_attempted" == false ]]; then
      route_recovered=false
      collector_recovered=false
      "$route_switch" --phase legacy \
        --confirm "ROUTE:legacy:${CHANGE_TICKET}" && route_recovered=true
      systemctl start m-ranked-collector.service && collector_recovered=true
      if [[ "$route_recovered" == true && "$collector_recovered" == true ]]; then
        echo "pre-sync cutover failure recovered legacy route and collector" >&2
      else
        echo "pre-sync recovery was incomplete; keep all writers stopped and escalate" >&2
      fi
    else
      echo "cutover failed after reverse-sync start was attempted; execute the rehearsed rollback" >&2
    fi
  fi
  exit "$exit_code"
}
trap recover_pre_sync_failure EXIT

"$preflight" --mode writer-cutover

install -d -m 0700 "$MIGRATION_SNAPSHOT_DIR" "$MIGRATION_REPORT_DIR"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
s_final="$MIGRATION_SNAPSHOT_DIR/S-final-$stamp.sqlite3"
report_stem="s-final-$stamp"
report_json="$MIGRATION_REPORT_DIR/$report_stem.json"

# This is the first mutation. Public reads continue while every legacy admin
# mutation is denied and the legacy collector is stopped.
"$route_switch" --phase writer-freeze \
  --confirm "ROUTE:writer-freeze:${CHANGE_TICKET}"
cutover_mutated=true
systemctl stop m-ranked-collector.service

"$python_bin" -m migration.bridge backup "$LEGACY_SQLITE_PATH" "$s_final"
s_final_sha256="$(sha256sum "$s_final" | cut -d' ' -f1)"
PGPASSFILE="$MIGRATION_PGPASSFILE" "$python_bin" -m migration.bridge import "$s_final" \
  --source-namespace "$MIGRATION_SOURCE_NAMESPACE" \
  --snapshot-kind s_final \
  --postgres-dsn "$MIGRATION_DATABASE_URL" \
  --report-dir "$MIGRATION_REPORT_DIR" \
  --stem "$report_stem"

if ! jq -e --arg sFinal "$s_final" --arg sFinalSha256 "$s_final_sha256" '
    .report_type == "post-import-reconciliation"
    and .report_version == 1
    and .gate.status == "pass"
    and .gate.critical_mismatches == 0
    and .source.source_path == $sFinal
    and .source.source_sha256 == $sFinalSha256
    and .source.quick_check == "ok"
    and .source.foreign_key_violations == 0
    and .bridge.source_sha256 == $sFinalSha256
    and .bridge.dry_run == false
    and (.bridge.finished_at | type) == "string"
    and (.batch_id | type) == "string"
    and (.batch_id | test(
      "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    ))
    and .bridge.batch_id == .batch_id
  ' "$report_json" >/dev/null; then
  echo "new S-final import/reconciliation evidence is invalid; target writers remain stopped" >&2
  exit 1
fi
s_final_batch_id="$(jq -er '.batch_id' "$report_json")"

if ! reverse_preflight_json="$("$REVERSE_SYNC_EXECUTABLE" preflight)"; then
  echo "reverse-sync preflight failed for the new S-final; target writers remain stopped" >&2
  exit 1
fi
if ! jq -e \
    --arg namespace "$MIGRATION_SOURCE_NAMESPACE" \
    --arg batchId "$s_final_batch_id" \
    --arg sourceSha256 "$s_final_sha256" '
      .command == "preflight"
      and .status == "pass"
      and .sourceNamespace == $namespace
      and .postgres.aliasMappingsUnambiguous == true
      and .postgres.singlePrimaryIdentity == true
      and .postgres.sFinalBatchId == $batchId
      and .postgres.sFinalSourceSha256 == $sourceSha256
      and .legacySqlite.quickCheck == "ok"
    ' <<<"$reverse_preflight_json" >/dev/null; then
  echo "reverse-sync preflight is not bound to the new S-final; target writers remain stopped" >&2
  exit 1
fi

revision_before="$(
  PGPASSFILE="$TARGET_PGPASSFILE" psql "$TARGET_DATABASE_URL" \
    --no-psqlrc --set ON_ERROR_STOP=1 --tuples-only --no-align \
    --command 'SELECT max(id) FROM analytics.dataset_revision'
)"
if [[ ! "$revision_before" =~ ^[1-9][0-9]*$ ]]; then
  echo "cannot determine the S-final dataset revision" >&2
  exit 70
fi

reverse_sync_attempted=true
"$REVERSE_SYNC_EXECUTABLE" start \
  --rollback-window-hours "$ROLLBACK_WINDOW_HOURS" \
  --operator "$OPERATOR_ID" --ticket "$CHANGE_TICKET"
systemctl start m-ranked-target-reverse-sync.service
if ! systemctl is-active --quiet m-ranked-target-reverse-sync.service; then
  echo "reverse-sync worker failed to start; run rollback now" >&2
  exit 1
fi

systemctl start m-ranked-target-projection-publisher.service
if ! systemctl is-active --quiet m-ranked-target-projection-publisher.service; then
  echo "projection publisher is inactive before target collector start; run rollback now" >&2
  exit 1
fi

systemctl start \
  m-ranked-target-collector@telegram.service \
  m-ranked-target-collector@vk.service \
  m-ranked-target-collector@max.service \
  m-ranked-target-collector@rutube.service

deadline=$(( $(date -u +%s) + TARGET_COLLECTION_GATE_SECONDS ))
revision_after="$revision_before"
successful_platforms=0
ready_core_projections=0
api_dataset_revision=0
reverse_sync_lag=-1
while (( $(date -u +%s) < deadline )); do
  if ! systemctl is-active --quiet m-ranked-target-projection-publisher.service; then
    echo "projection publisher became inactive; run rollback now" >&2
    exit 1
  fi
  if ! systemctl is-active --quiet m-ranked-target-reverse-sync.service; then
    echo "reverse-sync worker became inactive; run rollback now" >&2
    exit 1
  fi
  for collector_unit in \
    m-ranked-target-collector@telegram.service \
    m-ranked-target-collector@vk.service \
    m-ranked-target-collector@max.service \
    m-ranked-target-collector@rutube.service; do
    if ! systemctl is-active --quiet "$collector_unit"; then
      echo "target collector became inactive: $collector_unit; run rollback now" >&2
      exit 1
    fi
  done
  projection_state="$(
    PGPASSFILE="$TARGET_PGPASSFILE" psql "$TARGET_DATABASE_URL" \
      --no-psqlrc --set ON_ERROR_STOP=1 --tuples-only --no-align \
      --field-separator='|' <<'SQL'
WITH latest AS (
    SELECT max(id) AS id FROM analytics.dataset_revision
), core(name) AS (VALUES
    ('publication_latest'), ('publication_hourly'),
    ('institution_daily_metrics'), ('institution_monthly_metrics'),
    ('institution_period_metrics'), ('comparison')
)
SELECT latest.id,
       count(state.projection_name) FILTER (
           WHERE state.status = 'ready'
             AND state.dataset_revision_id = latest.id
       )
  FROM latest
 CROSS JOIN core
  LEFT JOIN analytics.projection_state AS state
    ON state.projection_name = core.name
 GROUP BY latest.id;
SQL
  )"
  IFS='|' read -r revision_after ready_core_projections <<<"$projection_state"
  successful_platforms="$(
    PGPASSFILE="$OUTBOX_PGPASSFILE" psql "$OUTBOX_DATABASE_URL" \
      --no-psqlrc --set ON_ERROR_STOP=1 --tuples-only --no-align \
      --set cutover_started="$started_at" <<'SQL'
SELECT count(DISTINCT platform)
  FROM ingest.collection_run
 WHERE started_at >= CAST(:'cutover_started' AS timestamptz)
   AND status = 'succeeded';
SQL
  )"
  api_readiness_json=""
  api_dataset_revision=0
  if api_readiness_json="$(
      curl --fail --silent --show-error --max-time 10 "$TARGET_API_URL"
    )"; then
    api_dataset_revision="$(
      jq -er '
        .datasetRevision as $revision
        | select(
            .status == "UP"
            and ($revision | type) == "number"
            and $revision > 0
            and $revision == ($revision | floor)
          )
        | $revision
      ' <<<"$api_readiness_json"
    )" || api_dataset_revision=0
  fi
  if [[ "$revision_after" =~ ^[1-9][0-9]*$ \
        && "$revision_after" -gt "$revision_before" \
        && "$successful_platforms" == 4 \
        && "$ready_core_projections" == 6 \
        && "$api_dataset_revision" == "$revision_after" ]]; then
    reverse_sync_lag="$(
      "$REVERSE_SYNC_EXECUTABLE" status \
        | jq -er 'select(.status == "active") | .lagRevisionCount'
    )" || reverse_sync_lag=-1
    if [[ "$reverse_sync_lag" == 0 ]]; then
      break
    fi
  fi
  sleep 5
done
if [[ ! "$revision_after" =~ ^[1-9][0-9]*$ \
      || "$revision_after" -le "$revision_before" \
      || "$successful_platforms" != 4 \
      || "$ready_core_projections" != 6 \
      || "$api_dataset_revision" != "$revision_after" \
      || "$reverse_sync_lag" != 0 ]] \
      || ! systemctl is-active --quiet m-ranked-target-projection-publisher.service \
      || ! systemctl is-active --quiet m-ranked-target-reverse-sync.service; then
  echo "collectors/revision/projection publisher/API did not satisfy the post-collector gate; run rollback now" >&2
  exit 1
fi

duplicate_count="$(
  PGPASSFILE="$MIGRATION_PGPASSFILE" psql "$MIGRATION_DATABASE_URL" \
    --no-psqlrc --set ON_ERROR_STOP=1 --tuples-only --no-align <<'SQL'
SELECT count(*)
  FROM (
      SELECT published_month, publication_id, sampling_bucket
        FROM ingest.publication_metric_snapshot
       GROUP BY published_month, publication_id, sampling_bucket
      HAVING count(*) > 1
  ) AS duplicates;
SQL
)"
if [[ "$duplicate_count" != 0 ]]; then
  echo "duplicate ingestion detected; run rollback now" >&2
  exit 1
fi

state_dir=/var/lib/m-ranked/cutover
install -d -m 0700 "$state_dir"
state_file="$state_dir/writer-cutover-$stamp.json"
rollback_deadline="$(date -u --date="+$ROLLBACK_WINDOW_HOURS hours" +%Y-%m-%dT%H:%M:%SZ)"
jq -n \
  --arg status monitoring --arg operator "$OPERATOR_ID" --arg ticket "$CHANGE_TICKET" \
  --arg startedAt "$started_at" --arg rollbackDeadline "$rollback_deadline" \
  --arg sFinal "$s_final" --arg sFinalSha256 "$s_final_sha256" \
  --arg reconciliation "$report_json" --argjson revisionBefore "$revision_before" \
  --argjson revisionAfter "$revision_after" \
  --argjson apiDatasetRevision "$api_dataset_revision" \
  '{status:$status,operator:$operator,changeTicket:$ticket,startedAt:$startedAt,
    rollbackDeadline:$rollbackDeadline,sFinal:$sFinal,sFinalSha256:$sFinalSha256,
    reconciliation:$reconciliation,datasetRevisionBefore:$revisionBefore,
    datasetRevisionAfter:$revisionAfter,successfulCollectorPlatforms:4,
    readyCoreProjections:6,projectionPublisherActive:true,
    apiReadiness:{status:"UP",datasetRevision:$apiDatasetRevision,
      matchesLatestPublished:true},
    duplicateIngestion:0,
    legacyCollectorStopped:true,legacyAdminMutationsFrozen:true,
    reverseSyncActive:true,reverseSyncLagRevisions:0}' >"$state_file"
chmod 0600 "$state_file"
trap - EXIT

echo "writer cutover entered monitored rollback window; state=$state_file"
