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
  echo "cannot resolve cutover preflight entrypoint origin" >&2
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
    echo "cutover preflight entrypoint or transition lock helper is unsafe" >&2
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
    echo "cutover preflight entrypoint directory chain is unsafe" >&2
    exit 73
  fi
  [[ "$transition_secure_dir" == / ]] && break
  transition_secure_dir="${transition_secure_dir%/*}"
  [[ -n "$transition_secure_dir" ]] || transition_secure_dir=/
done
if [[ ! -r "$transition_lock_helper" ]]; then
  echo "cutover preflight entrypoint or transition lock helper is unsafe" >&2
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

mode="${2:-}"
if [[ "${1:-}" != "--mode" || $# -ne 2 \
      || ( "$mode" != public-read && "$mode" != writer-cutover ) ]]; then
  echo "usage: $0 --mode public-read|writer-cutover" >&2
  exit 64
fi

: "${MRANKED_INSTALL_ROOT:=/opt/m-ranked/releases}"
: "${MRANKED_CURRENT_LINK:=/opt/m-ranked/current}"
if (( EUID != 0 )); then
  echo "cutover preflight must run as root" >&2
  exit 77
fi
mranked_transition_lock_acquire
mranked_transition_require_active_entrypoint "$transition_entry_path"

failures=0
fail() {
  echo "FAIL: $*" >&2
  failures=$((failures + 1))
}
pass() {
  echo "PASS: $*"
}
require_value() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    fail "$name is not set"
    return 1
  fi
}
reject_placeholder_value() {
  local name="$1"
  local value="${!name:-}"
  case "$value" in
    *[Rr][Ee][Pp][Ll][Aa][Cc][Ee]-[Ww][Ii][Tt][Hh]-*)
      fail "$name still contains a replace-with placeholder"
      return 1
      ;;
  esac
}
require_readable() {
  local path="$1"
  local description="$2"
  if [[ ! -f "$path" || ! -r "$path" || -L "$path" ]]; then
    fail "$description is not a readable regular file: $path"
    return 1
  fi
}
file_mode() {
  stat -c %a "$1" 2>/dev/null || stat -f %Lp "$1" 2>/dev/null
}
file_identity() {
  stat -c '%d:%i:%s:%Y:%Z' "$1" 2>/dev/null \
    || stat -f '%d:%i:%z:%m:%c' "$1" 2>/dev/null
}
check_not_group_world_writable() {
  local path="$1"
  local description="$2"
  local mode
  if ! require_readable "$path" "$description"; then
    return 1
  fi
  mode="$(file_mode "$path")" || mode=""
  if [[ "$mode" =~ ^[0-7]{3,4}$ ]] && (( (8#$mode & 8#022) == 0 )); then
    pass "$description is not group/world writable"
  else
    fail "$description is group/world writable or its mode cannot be read"
    return 1
  fi
}
file_age_seconds() {
  local path="$1"
  echo $(( $(date -u +%s) - $(stat -c %Y "$path") ))
}
check_file_age_gate() {
  local path="$1"
  local description="$2"
  local max_age_seconds="$3"
  if ! require_readable "$path" "$description"; then
    return
  fi
  local age_seconds
  age_seconds="$(file_age_seconds "$path")"
  if [[ "$age_seconds" =~ ^[0-9]+$ ]] \
      && (( age_seconds <= max_age_seconds )); then
    pass "$description age ${age_seconds}s is within gate"
  else
    fail "$description age is invalid or exceeds ${max_age_seconds}s"
  fi
}
check_json_gate() {
  local path="$1"
  local description="$2"
  if ! require_readable "$path" "$description"; then
    return
  fi
  if jq -e '(.status // .gate.status) == "pass"' "$path" >/dev/null; then
    pass "$description passed"
  else
    fail "$description is not pass"
  fi
}
check_reverse_sync_rehearsal_gate() {
  local path="$1"
  local deploy_release_id="$2"
  local deploy_manifest_sha256="$3"
  local source_namespace="$4"
  local approval_ticket="$5"
  local operator="$6"
  local max_age_seconds="$7"
  if ! require_readable "$path" "reverse-sync rehearsal report"; then
    return
  fi
  if [[ -z "$deploy_release_id" \
        || ! "$deploy_manifest_sha256" =~ ^[0-9a-f]{64}$ \
        || -z "$source_namespace" || -z "$approval_ticket" || -z "$operator" ]]; then
    fail "reverse-sync rehearsal expected provenance is incomplete"
    return
  fi

  check_sha256_sidecar "$path" "reverse-sync rehearsal report"
  check_not_group_world_writable "$path" "reverse-sync rehearsal report"
  check_not_group_world_writable \
    "$path.sha256" "reverse-sync rehearsal report SHA-256"
  check_file_age_gate "$path" "reverse-sync rehearsal report" "$max_age_seconds"
  check_file_age_gate "$path.sha256" \
    "reverse-sync rehearsal report SHA-256" "$max_age_seconds"

  local generated_at
  local generated_epoch
  local generated_age
  generated_at="$(jq -er '.generatedAt | select(type == "string")' "$path" 2>/dev/null)" \
    || generated_at=""
  generated_epoch="$(date -u --date="$generated_at" +%s 2>/dev/null)" \
    || generated_epoch=""
  if [[ "$generated_at" =~ (Z|\+00:00)$ \
        && "$generated_epoch" =~ ^[0-9]+$ ]]; then
    generated_age=$(( $(date -u +%s) - generated_epoch ))
    if (( generated_age >= 0 && generated_age <= max_age_seconds )); then
      pass "reverse-sync rehearsal generatedAt age ${generated_age}s is within gate"
    else
      fail "reverse-sync rehearsal generatedAt is future-dated or stale"
    fi
  else
    fail "reverse-sync rehearsal generatedAt is not a parseable UTC timestamp"
  fi

  local contract_filter='
      def positive_integer:
        type == "number" and . >= 1 and . == floor;
      def zero_integer: type == "number" and . == 0;
      def sha256: type == "string" and test("^[0-9a-f]{64}$");
      def uuid:
        type == "string"
        and test("^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$");
      type == "object"
      and keys == [
        "changeTicket", "database", "duplicates", "environment", "flyway",
        "forwardReconciliation", "generatedAt", "operator", "platforms",
        "preservation", "release", "replay", "reportType", "reportVersion",
        "reverseSync", "sFinal", "sourceNamespace", "status"
      ]
      and .reportType == "reverse-sync-rehearsal"
      and .reportVersion == 3
      and .status == "pass"
      and .environment == "production-like"
      and (.generatedAt | type) == "string"
      and (.database | type) == "string"
      and (.database | test("^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"))
      and .operator == $operator
      and .changeTicket == $approvalTicket
      and .sourceNamespace == $sourceNamespace
      and (.release | type == "object" and keys == ["id", "sha256SumsSha256"])
      and .release.id == $releaseId
      and (.release.sha256SumsSha256 | sha256)
      and .release.sha256SumsSha256 == $manifestSha256
      and (.flyway | type == "object" and keys == [
        "databaseMigrations", "fileSha256", "migrationCount", "schemaVersion"
      ])
      and .flyway.schemaVersion == 8
      and .flyway.migrationCount == 8
      and (.flyway.fileSha256 | type == "object" and keys == [
        "V1__target_baseline.sql",
        "V2__rebuild_core_projections.sql",
        "V3__collector_observation_times_and_identity_grants.sql",
        "V4__admin_collection_run_status_grants.sql",
        "V5__legacy_activity_period_projection.sql",
        "V6__comparison_valid_observation_hourly_projection.sql",
        "V7__activity_rating_read_grants.sql",
        "V8__legacy_overview_projection.sql"
      ])
      and .flyway.fileSha256 == {
        "V1__target_baseline.sql":"dc0ded29c5b7b42860dbabd04988c1803900685dc074c25adf5969e8be8d9fb1",
        "V2__rebuild_core_projections.sql":"113e94524c6617bf59ab7dc2760615bf9c6d10538c12290400e15f85df16c7dd",
        "V3__collector_observation_times_and_identity_grants.sql":"5233f98d3b39db74a449b1e9852f252def1606c5982e87d40ec366275d388ad1",
        "V4__admin_collection_run_status_grants.sql":"d5af14bfc692e9e3b57ed257b3632fbc616cb65ba47babb2aebb1d7dea5b7e82",
        "V5__legacy_activity_period_projection.sql":"d56c124e2d68eb9897d3fe9d10bde0adf730ea02b84e0d7ec09660775438ea41",
        "V6__comparison_valid_observation_hourly_projection.sql":"4ac99091046d40345c7024d3fab96ceb779fafb836c18c6a750f748f7bd29c64",
        "V7__activity_rating_read_grants.sql":"95244a71a992fb8d9de387622224ddb52365120ac47c4d0cf4cbb20f4e36f0eb",
        "V8__legacy_overview_projection.sql":"dc855dde66a705808e1565e3f56c4555995d370805cee68ee9293ae7fa0aec9c"
      }
      and .flyway.databaseMigrations == [
        {version:"1",script:"V1__target_baseline.sql",checksum:-1636077697,success:true},
        {version:"2",script:"V2__rebuild_core_projections.sql",checksum:839607018,success:true},
        {version:"3",script:"V3__collector_observation_times_and_identity_grants.sql",checksum:-1456658399,success:true},
        {version:"4",script:"V4__admin_collection_run_status_grants.sql",checksum:1318350062,success:true},
        {version:"5",script:"V5__legacy_activity_period_projection.sql",checksum:-1313754193,success:true},
        {version:"6",script:"V6__comparison_valid_observation_hourly_projection.sql",checksum:-290358219,success:true},
        {version:"7",script:"V7__activity_rating_read_grants.sql",checksum:-1228913579,success:true},
        {version:"8",script:"V8__legacy_overview_projection.sql",checksum:-574188650,success:true}
      ]
      and (.platforms | type) == "array"
      and (.platforms | length) == 4
      and all(.platforms[]; type == "string")
      and (.platforms | sort) == ["max", "rutube", "telegram", "vk"]
      and (.replay | type == "object" and keys == ["idempotent", "runCount"])
      and (.replay.runCount | positive_integer)
      and .replay.runCount >= 2
      and .replay.idempotent == true
      and (.duplicates | type == "object" and keys == [
        "identityCount", "observationCount", "primaryIdentityCount", "snapshotCount"
      ])
      and all(.duplicates[]; zero_integer)
      and (.preservation | type == "object" and keys == [
        "aliasMismatches", "identityMismatches", "publicationMismatches",
        "snapshotMismatches"
      ])
      and all(.preservation[]; zero_integer)
      and (.forwardReconciliation | type == "object" and keys == [
        "criticalMismatches", "status"
      ])
      and .forwardReconciliation.status == "pass"
      and (.forwardReconciliation.criticalMismatches | zero_integer)
      and (.reverseSync | type == "object" and keys == [
        "baselineRevisionCount", "baselineRevisionSetSha256",
        "fixedRevisionCount", "fixedRevisionSetSha256", "journalStateVersion",
        "planSha256", "status"
      ])
      and .reverseSync.status == "stopped"
      and .reverseSync.journalStateVersion == 3
      and (.reverseSync.baselineRevisionCount | positive_integer)
      and (.reverseSync.baselineRevisionSetSha256 | sha256)
      and (.reverseSync.fixedRevisionCount | positive_integer)
      and .reverseSync.fixedRevisionCount >= 4
      and (.reverseSync.fixedRevisionSetSha256 | sha256)
      and (.reverseSync.planSha256 | sha256)
      and (.sFinal | type == "object" and keys == ["batchId", "gate", "sourceSha256"])
      and (.sFinal.batchId | uuid)
      and (.sFinal.sourceSha256 | sha256)
      and .sFinal.gate == "pass"
    '
  if jq -e \
      --arg releaseId "$deploy_release_id" \
      --arg manifestSha256 "$deploy_manifest_sha256" \
      --arg sourceNamespace "$source_namespace" \
      --arg approvalTicket "$approval_ticket" \
      --arg operator "$operator" \
      "$contract_filter" "$path" >/dev/null; then
    pass "reverse-sync rehearsal v3 is fresh and bound to release, namespace and approval"
  else
    fail "reverse-sync rehearsal v3 evidence is incomplete, malformed or unbound"
  fi
}
check_collector_parity_gate() {
  local report_path="$1"
  local evidence_root="$2"
  local release_path="$3"
  local active_release_link="$4"
  local install_root="$5"
  local deploy_report="$6"
  local operator="$7"
  local approval_ticket="$8"
  local source_namespace="$9"
  local max_age_seconds="${10}"
  local install_root_real
  local active_raw_target
  local active_resolved_target
  local verifier
  local verifier_output

  install_root_real="$(readlink -f -- "$install_root" 2>/dev/null || true)"
  active_raw_target="$(readlink -- "$active_release_link" 2>/dev/null || true)"
  active_resolved_target="$(readlink -f -- "$active_release_link" 2>/dev/null || true)"
  verifier="$release_path/operations/bin/collector-parity-evidence"
  if [[ -z "$release_path" || "$install_root_real" != "$install_root" \
        || "${release_path%/*}" != "$install_root_real" \
        || "$active_raw_target" != "$release_path" \
        || "$active_resolved_target" != "$release_path" \
        || ! -d "$release_path" || -L "$release_path" \
        || ! -x "$verifier" || -L "$verifier" ]]; then
    fail "active release collector parity verifier is unavailable"
    return 1
  fi
  # check_active_release_gate published release_path only after its complete
  # manifest/report recheck.  Re-read the link immediately before exec while
  # FD 8 still serializes every cooperating deploy/cutover transition.
  if [[ "$(readlink -- "$active_release_link" 2>/dev/null || true)" \
          != "$release_path" \
        || "$(readlink -f -- "$active_release_link" 2>/dev/null || true)" \
          != "$release_path" ]]; then
    fail "active release changed before collector parity verification"
    return 1
  fi
  if verifier_output="$(
    unset BASH_ENV CDPATH ENV PYTHONHOME PYTHONPATH __PYVENV_LAUNCHER__
    exec /bin/bash -p "$verifier" verify \
      --report "$report_path" \
      --evidence-root "$evidence_root" \
      --active-release-link "$active_release_link" \
      --install-root "$install_root" \
      --deploy-report "$deploy_report" \
      --operator "$operator" \
      --approval-ticket "$approval_ticket" \
      --source-namespace "$source_namespace" \
      --max-age-seconds "$max_age_seconds"
  )" && jq -e \
      --arg report "$report_path" \
      '.status == "pass" and .command == "verify" and .report == $report' \
      <<<"$verifier_output" >/dev/null; then
    pass "target collector parity evidence passed the release-bound verifier"
    return 0
  fi
  fail "target collector parity evidence is invalid or unbound"
  return 1
}
check_sha256_sidecar() {
  local path="$1"
  local description="$2"
  local checksum_path="$path.sha256"
  if ! require_readable "$checksum_path" "$description SHA-256"; then
    return
  fi
  local checksum_record
  local computed_record
  checksum_record="$(<"$checksum_path")"
  computed_record="$(sha256sum "$path")"
  if [[ "$checksum_record" =~ ^([0-9a-f]{64})[[:space:]]+.+$ \
        && "${BASH_REMATCH[1]}" == "${computed_record%% *}" ]]; then
    pass "$description SHA-256 matches"
  else
    fail "$description SHA-256 does not match"
  fi
}

validate_release_symlinks() {
  local tree="$1"
  local symlink_manifest="$tree/SYMLINKS.sha256"
  local expected_records
  local actual_records
  local link_path
  local relative_path
  local raw_target
  local raw_target_after
  local raw_target_record
  local raw_target_record_after
  local resolved_path
  local resolved_path_after
  local target_path
  local target_parent_real
  local target_sha256
  local tree_real
  local symlink_manifest_sha256
  local symlink_manifest_sha256_after

  if [[ ! -f "$symlink_manifest" || -L "$symlink_manifest" \
        || ! -f "$tree/SHA256SUMS" || -L "$tree/SHA256SUMS" ]]; then
    return 1
  fi
  tree_real="$(readlink -f -- "$tree")" || return 1
  expected_records="$(mktemp)"
  actual_records="$(mktemp)"
  symlink_manifest_sha256="$(
    sha256sum "$symlink_manifest" | cut -d' ' -f1
  )" || {
    rm -f -- "$expected_records" "$actual_records"
    return 1
  }
  if [[ ! "$symlink_manifest_sha256" =~ ^[0-9a-f]{64}$ ]]; then
    rm -f -- "$expected_records" "$actual_records"
    return 1
  fi
  if ! LC_ALL=C awk '
      !/^[0-9a-f]{64}  [A-Za-z0-9._+@%\/-]+$/ { exit 1 }
      {
          path = substr($0, 67)
          if (path ~ /^\// || path ~ /(^|\/)\.\.?(\/|$)/ || seen[path]++) {
              exit 1
          }
          print $0
      }
    ' "$symlink_manifest" | LC_ALL=C sort >"$expected_records" \
      || ! cmp --silent "$symlink_manifest" "$expected_records"; then
    rm -f -- "$expected_records" "$actual_records"
    return 1
  fi
  if ! (
    cd -- "$tree" || exit 1
    find . -type l -print0 |
      while IFS= read -r -d '' link_path; do
        relative_path="${link_path#./}"
        raw_target_record="$(
          {
            readlink -- "$link_path" || exit 1
            printf '.'
          }
        )" || exit 1
        if [[ "$raw_target_record" != *$'\n.' ]]; then
          exit 1
        fi
        raw_target="${raw_target_record%$'\n.'}"
        if [[ ! "$relative_path" =~ ^[A-Za-z0-9._+@%/-]+$ \
              || "$relative_path" == /* \
              || "$relative_path" == . \
              || "$relative_path" == .. \
              || "$relative_path" == ../* \
              || "$relative_path" == */../* \
              || "$relative_path" == */.. \
              || ! "$raw_target" =~ ^[-A-Za-z0-9._+@%/=:,~]+$ ]]; then
          exit 1
        fi
        if [[ ! -e "$link_path" ]]; then
          exit 1
        fi
        if [[ "$raw_target" == /* ]]; then
          target_path="$raw_target"
        else
          target_path="${link_path%/*}/$raw_target"
        fi
        target_parent_real="$(
          readlink -f -- "$(dirname -- "$target_path")"
        )" || exit 1
        resolved_path="$(readlink -f -- "$link_path")" || exit 1
        case "$resolved_path" in
          "$tree_real"/*)
            if [[ "$raw_target" == /* ]]; then
              exit 1
            fi
            case "$target_parent_real" in
              "$tree_real"|"$tree_real"/*) ;;
              *) exit 1 ;;
            esac
            ;;
          *)
            case "$relative_path:$resolved_path" in
              .venv/bin/python:/usr/bin/python3.13|\
              .venv/bin/python:/usr/local/bin/python3.13|\
              .venv/bin/python3:/usr/bin/python3.13|\
              .venv/bin/python3:/usr/local/bin/python3.13|\
              .venv/bin/python3.13:/usr/bin/python3.13|\
              .venv/bin/python3.13:/usr/local/bin/python3.13) ;;
              *) exit 1 ;;
            esac
            if [[ "$raw_target" == /* ]]; then
              case "$raw_target" in
                /usr/bin/python3.13|/usr/local/bin/python3.13) ;;
                *) exit 1 ;;
              esac
            else
              case "$target_parent_real" in
                "$tree_real"|"$tree_real"/*) ;;
                *) exit 1 ;;
              esac
            fi
            ;;
        esac
        raw_target_record_after="$(
          {
            readlink -- "$link_path" || exit 1
            printf '.'
          }
        )" || exit 1
        if [[ "$raw_target_record_after" != *$'\n.' ]]; then
          exit 1
        fi
        raw_target_after="${raw_target_record_after%$'\n.'}"
        resolved_path_after="$(readlink -f -- "$link_path")" || exit 1
        if [[ "$raw_target_after" != "$raw_target" \
              || "$resolved_path_after" != "$resolved_path" ]]; then
          exit 1
        fi
        target_sha256="$(
          printf '%s' "$raw_target" | sha256sum | cut -d' ' -f1
        )" || exit 1
        if [[ ! "$target_sha256" =~ ^[0-9a-f]{64}$ ]]; then
          exit 1
        fi
        printf '%s  %s\n' "$target_sha256" "$relative_path"
      done
  ) | LC_ALL=C sort >"$actual_records"; then
    rm -f -- "$expected_records" "$actual_records"
    return 1
  fi
  if ! cmp --silent "$expected_records" "$actual_records"; then
    rm -f -- "$expected_records" "$actual_records"
    return 1
  fi
  symlink_manifest_sha256_after="$(
    sha256sum "$symlink_manifest" | cut -d' ' -f1
  )" || symlink_manifest_sha256_after=""
  if [[ "$symlink_manifest_sha256_after" != "$symlink_manifest_sha256" ]] \
      || ! LC_ALL=C awk -v sha256="$symlink_manifest_sha256" '
        $0 == sha256 "  SYMLINKS.sha256" \
          || $0 == sha256 " *SYMLINKS.sha256" { matches++ }
        END { exit(matches == 1 ? 0 : 1) }
      ' "$tree/SHA256SUMS"; then
    rm -f -- "$expected_records" "$actual_records"
    return 1
  fi
  rm -f -- "$expected_records" "$actual_records"
}

verify_exact_release_manifest() {
  local tree="$1"
  local manifest_paths
  local actual_paths
  manifest_paths="$(mktemp)"
  actual_paths="$(mktemp)"
  if ! awk '
      !/^[0-9a-f]{64} [ *][A-Za-z0-9._+@%\/-]+$/ { exit 1 }
      {
          path = substr($0, 67)
          if (path ~ /^\// || path ~ /(^|\/)\.\.?(\/|$)/ || seen[path]++) {
              exit 1
          }
          print path
      }
      END { if (NR == 0) exit 1 }
    ' "$tree/SHA256SUMS" | sort >"$manifest_paths"; then
    rm -f -- "$manifest_paths" "$actual_paths"
    return 1
  fi
  (
    cd -- "$tree"
    find . -type f ! -path './SHA256SUMS' -print \
      | sed 's#^\./##' \
      | sort
  ) >"$actual_paths"
  if ! cmp --silent "$manifest_paths" "$actual_paths"; then
    rm -f -- "$manifest_paths" "$actual_paths"
    return 1
  fi
  rm -f -- "$manifest_paths" "$actual_paths"
  if ! (
    cd -- "$tree"
    sha256sum --check --strict SHA256SUMS >/dev/null 2>&1
  ); then
    return 1
  fi
  validate_release_symlinks "$tree"
}

check_active_release_gate() {
  local report_path="$1"
  local install_root="$2"
  local current_link="$3"
  local allowed_path_regex="${4:-^/(opt|srv)/m-ranked/[A-Za-z0-9._/-]+$}"
  local initial_failures="$failures"
  local install_root_real=""
  local current_parent=""
  local current_parent_real=""
  local current_raw_target=""
  local current_release_path=""
  local release_id=""
  local manifest_path=""
  local manifest_sha256=""
  local manifest_sha256_after=""
  local manifest_state=""
  local manifest_state_after=""
  local link_state=""
  local link_state_after=""
  local release_mode=""

  deploy_release_id=""
  deploy_manifest_sha256=""
  deploy_release_path=""
  if ! require_readable "$report_path" "shadow deployment report"; then
    return 1
  fi
  check_sha256_sidecar "$report_path" "shadow deployment report"
  check_not_group_world_writable "$report_path" "shadow deployment report"
  check_not_group_world_writable \
    "$report_path.sha256" "shadow deployment report SHA-256"

  if [[ ! "$install_root" =~ $allowed_path_regex \
        || ! "$current_link" =~ $allowed_path_regex ]]; then
    fail "configured install root or current release link is unsafe"
    return 1
  fi
  if [[ -L "$install_root" || ! -d "$install_root" ]]; then
    fail "configured install root is not a real directory"
    return 1
  fi
  install_root_real="$(readlink -f -- "$install_root")" || install_root_real=""
  if [[ "$install_root_real" != "$install_root" ]]; then
    fail "configured install root is not canonical"
    return 1
  fi
  release_mode="$(file_mode "$install_root")" || release_mode=""
  if [[ ! "$release_mode" =~ ^[0-7]{3,4}$ ]] \
      || (( (8#$release_mode & 8#022) != 0 )); then
    fail "configured install root is group/world writable"
    return 1
  fi

  current_parent="${current_link%/*}"
  current_parent_real="$(readlink -f -- "$current_parent")" \
    || current_parent_real=""
  if [[ "$current_parent_real" != "$current_parent" ]]; then
    fail "configured current release link has a non-canonical parent"
    return 1
  fi
  release_mode="$(file_mode "$current_parent")" || release_mode=""
  if [[ ! "$release_mode" =~ ^[0-7]{3,4}$ ]] \
      || (( (8#$release_mode & 8#022) != 0 )); then
    fail "configured current release link parent is group/world writable"
    return 1
  fi
  if [[ ! -L "$current_link" ]]; then
    fail "configured current release path is not a symlink"
    return 1
  fi
  current_raw_target="$(readlink -- "$current_link")" || current_raw_target=""
  current_release_path="$(readlink -f -- "$current_link")" \
    || current_release_path=""
  release_id="${current_release_path##*/}"
  if [[ "$current_raw_target" != "$current_release_path" \
        || ! -d "$current_release_path" || -L "$current_release_path" \
        || "${current_release_path%/*}" != "$install_root_real" \
        || ! "$release_id" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$ ]]; then
    fail "current release symlink does not name one canonical immutable release"
    return 1
  fi
  case "$release_id" in
    [Rr][Ee][Pp][Ll][Aa][Cc][Ee]-[Ww][Ii][Tt][Hh]-*)
      fail "current release symlink names a placeholder release"
      return 1
      ;;
  esac
  release_mode="$(file_mode "$current_release_path")" || release_mode=""
  if [[ ! "$release_mode" =~ ^[0-7]{3,4}$ ]] \
      || (( (8#$release_mode & 8#022) != 0 )); then
    fail "current release root is group/world writable or its mode cannot be read"
    return 1
  fi

  manifest_path="$current_release_path/SHA256SUMS"
  if ! require_readable "$manifest_path" "active release SHA256SUMS"; then
    return 1
  fi
  check_not_group_world_writable "$manifest_path" "active release SHA256SUMS"
  link_state="$(file_identity "$current_link")" || link_state=""
  manifest_state="$(file_identity "$manifest_path")" \
    || manifest_state=""
  manifest_sha256="$(sha256sum "$manifest_path" | cut -d' ' -f1)" \
    || manifest_sha256=""
  if [[ ! "$manifest_sha256" =~ ^[0-9a-f]{64}$ \
        || -z "$link_state" || -z "$manifest_state" ]]; then
    fail "active release provenance could not be captured"
    return 1
  fi
  if ! verify_exact_release_manifest "$current_release_path"; then
    fail "active release SHA256SUMS or symlink inventory verification failed"
  fi

  if ! jq -e \
      --arg releasePath "$current_release_path" \
      --arg releaseId "$release_id" \
      --arg manifestSha256 "$manifest_sha256" '
      .status == "pass"
      and .releasePath == $releasePath
      and .releaseId == $releaseId
      and .releaseManifestSha256 == $manifestSha256
      and (.releaseManifestSha256 | test("^[0-9a-f]{64}$"))
      and .flyway.validated == true
      and .flyway.schemaVersion == "8"
      and .flyway.migrationCount == 8
      and .flyway.v1Sha256 == "dc0ded29c5b7b42860dbabd04988c1803900685dc074c25adf5969e8be8d9fb1"
      and .flyway.v2Sha256 == "113e94524c6617bf59ab7dc2760615bf9c6d10538c12290400e15f85df16c7dd"
      and .flyway.v3Sha256 == "5233f98d3b39db74a449b1e9852f252def1606c5982e87d40ec366275d388ad1"
      and .flyway.v4Sha256 == "d5af14bfc692e9e3b57ed257b3632fbc616cb65ba47babb2aebb1d7dea5b7e82"
      and .flyway.v5Sha256 == "d56c124e2d68eb9897d3fe9d10bde0adf730ea02b84e0d7ec09660775438ea41"
      and .flyway.v6Sha256 == "4ac99091046d40345c7024d3fab96ceb779fafb836c18c6a750f748f7bd29c64"
      and .flyway.v7Sha256 == "95244a71a992fb8d9de387622224ddb52365120ac47c4d0cf4cbb20f4e36f0eb"
      and .flyway.v8Sha256 == "dc855dde66a705808e1565e3f56c4555995d370805cee68ee9293ae7fa0aec9c"
      and .projectionPublisherActive == true
    ' "$report_path" >/dev/null; then
    fail "shadow deployment, active release or Flyway checksum evidence is invalid"
  fi

  if [[ "$(readlink -- "$current_link" 2>/dev/null || true)" \
          != "$current_raw_target" \
        || "$(readlink -f -- "$current_link" 2>/dev/null || true)" \
          != "$current_release_path" ]]; then
    fail "current release symlink changed during preflight"
  fi
  link_state_after="$(file_identity "$current_link")" \
    || link_state_after=""
  manifest_state_after="$(file_identity "$manifest_path")" \
    || manifest_state_after=""
  manifest_sha256_after="$(sha256sum "$manifest_path" | cut -d' ' -f1)" \
    || manifest_sha256_after=""
  if [[ "$link_state_after" != "$link_state" \
        || "$manifest_state_after" != "$manifest_state" \
        || "$manifest_sha256_after" != "$manifest_sha256" ]]; then
    fail "active release provenance changed during preflight"
  fi
  if ! verify_exact_release_manifest "$current_release_path"; then
    fail "active release changed during final manifest/inventory verification"
  fi

  if (( failures == initial_failures )); then
    deploy_release_id="$release_id"
    deploy_manifest_sha256="$manifest_sha256"
    deploy_release_path="$current_release_path"
    pass "shadow deployment is bound to the active immutable release and frozen V1-V8"
    return 0
  fi
  return 1
}

for command_name in curl jq psql stat date df tail tr sha256sum systemctl \
  readlink cut awk sort find cmp mktemp rm sed dirname; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    fail "required command is missing: $command_name"
  fi
done
if (( failures > 0 )); then
  exit 69
fi

for variable_name in \
  OPERATOR_ID CHANGE_TICKET TARGET_API_URL TARGET_WEB_URL LEGACY_HEALTH_URL \
  TARGET_DATABASE_URL TARGET_PGPASSFILE OUTBOX_DATABASE_URL OUTBOX_PGPASSFILE \
  BACKUP_MONITOR_DATABASE_URL BACKUP_PGPASSFILE RECONCILIATION_REPORT \
  RESTORE_VERIFICATION_REPORT CONTRACT_GATE_REPORT VISUAL_GATE_REPORT \
  PERFORMANCE_GATE_REPORT DEPLOY_REPORT DATA_FILESYSTEM_PATH \
  MRANKED_INSTALL_ROOT MRANKED_CURRENT_LINK; do
  require_value "$variable_name" || true
done
for variable_name in OPERATOR_ID CHANGE_TICKET; do
  reject_placeholder_value "$variable_name" || true
done
if (( failures > 0 )); then
  exit 64
fi

RECONCILIATION_MAX_AGE_SECONDS="${RECONCILIATION_MAX_AGE_SECONDS:-1800}"
RESTORE_REPORT_MAX_AGE_SECONDS="${RESTORE_REPORT_MAX_AGE_SECONDS:-86400}"
REVERSE_SYNC_REHEARSAL_MAX_AGE_SECONDS="${REVERSE_SYNC_REHEARSAL_MAX_AGE_SECONDS:-86400}"
COLLECTOR_PARITY_MAX_AGE_SECONDS="${COLLECTOR_PARITY_MAX_AGE_SECONDS:-86400}"
MAX_OUTBOX_LAG_SECONDS="${MAX_OUTBOX_LAG_SECONDS:-60}"
MAX_WAL_ARCHIVE_AGE_SECONDS="${MAX_WAL_ARCHIVE_AGE_SECONDS:-900}"
MAX_REPLICA_LAG_SECONDS="${MAX_REPLICA_LAG_SECONDS:-900}"
MAX_DISK_PERCENT="${MAX_DISK_PERCENT:-69}"
ROLLBACK_WINDOW_HOURS="${ROLLBACK_WINDOW_HOURS:-72}"
for value_name in \
  RECONCILIATION_MAX_AGE_SECONDS RESTORE_REPORT_MAX_AGE_SECONDS \
  REVERSE_SYNC_REHEARSAL_MAX_AGE_SECONDS COLLECTOR_PARITY_MAX_AGE_SECONDS \
  MAX_OUTBOX_LAG_SECONDS MAX_WAL_ARCHIVE_AGE_SECONDS MAX_REPLICA_LAG_SECONDS \
  MAX_DISK_PERCENT ROLLBACK_WINDOW_HOURS; do
  value="${!value_name}"
  if [[ ! "$value" =~ ^[1-9][0-9]*$ ]]; then
    fail "$value_name must be a positive integer"
  fi
done

if curl --fail --silent --show-error --max-time 10 "$LEGACY_HEALTH_URL" >/dev/null; then
  pass "legacy read path is healthy"
else
  fail "legacy read path is not healthy"
fi
if curl --fail --silent --show-error --max-time 10 "$TARGET_API_URL" >/dev/null; then
  pass "target API is ready"
else
  fail "target API is not ready"
fi
if curl --fail --silent --show-error --max-time 10 "$TARGET_WEB_URL" >/dev/null; then
  pass "target web is ready"
else
  fail "target web is not ready"
fi

check_json_gate "$CONTRACT_GATE_REPORT" "HTTP contract gate"
check_json_gate "$VISUAL_GATE_REPORT" "visual parity gate"
check_json_gate "$PERFORMANCE_GATE_REPORT" "performance budget gate"
deploy_release_id=""
deploy_manifest_sha256=""
deploy_release_path=""
check_active_release_gate \
  "$DEPLOY_REPORT" "$MRANKED_INSTALL_ROOT" "$MRANKED_CURRENT_LINK" || true

if require_readable "$RECONCILIATION_REPORT" "reconciliation report"; then
  if jq -e '.gate.status == "pass" and .gate.critical_mismatches == 0' \
      "$RECONCILIATION_REPORT" >/dev/null; then
    pass "reconciliation has zero critical mismatches"
  else
    fail "reconciliation has a critical mismatch"
  fi
  reconciliation_age="$(file_age_seconds "$RECONCILIATION_REPORT")"
  if (( reconciliation_age >= 0 \
        && reconciliation_age <= RECONCILIATION_MAX_AGE_SECONDS )); then
    pass "reconciliation age ${reconciliation_age}s is within gate"
  else
    fail "reconciliation age ${reconciliation_age}s exceeds ${RECONCILIATION_MAX_AGE_SECONDS}s"
  fi
fi

if require_readable "$RESTORE_VERIFICATION_REPORT" "restore verification report"; then
  check_sha256_sidecar "$RESTORE_VERIFICATION_REPORT" "restore verification report"
  if jq -e '
      .status == "pass"
      and .rtoMet == true
      and .checks.pageChecksums == true
      and .checks.databaseAssertions == true
      and .checks.pgAmcheck == true
      and .database.flywaySchemaVersion == 8
      and .database.flywayMigrationCount == 8
      and .database.flywayMigrations == [
          {version:"1",script:"V1__target_baseline.sql",checksum:-1636077697},
          {version:"2",script:"V2__rebuild_core_projections.sql",checksum:839607018},
          {version:"3",script:"V3__collector_observation_times_and_identity_grants.sql",checksum:-1456658399},
          {version:"4",script:"V4__admin_collection_run_status_grants.sql",checksum:1318350062},
          {version:"5",script:"V5__legacy_activity_period_projection.sql",checksum:-1313754193},
          {version:"6",script:"V6__comparison_valid_observation_hourly_projection.sql",checksum:-290358219},
          {version:"7",script:"V7__activity_rating_read_grants.sql",checksum:-1228913579},
          {version:"8",script:"V8__legacy_overview_projection.sql",checksum:-574188650}
      ]
  ' \
      "$RESTORE_VERIFICATION_REPORT" >/dev/null; then
    pass "latest backup has a successful V1-V8 restore verification"
  else
    fail "latest backup restore verification is incomplete or failed"
  fi
  restore_age="$(file_age_seconds "$RESTORE_VERIFICATION_REPORT")"
  if (( restore_age >= 0 && restore_age <= RESTORE_REPORT_MAX_AGE_SECONDS )); then
    pass "restore report age ${restore_age}s is within gate"
  else
    fail "restore report age ${restore_age}s exceeds ${RESTORE_REPORT_MAX_AGE_SECONDS}s"
  fi
fi

if require_readable "$TARGET_PGPASSFILE" "target read pgpass"; then
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
       count(*) FILTER (
           WHERE state.status = 'ready'
             AND state.dataset_revision_id = latest.id
       ),
       count(*) FILTER (
           WHERE state.status <> 'ready'
              OR state.dataset_revision_id <> latest.id
       )
  FROM latest
 CROSS JOIN core
  LEFT JOIN analytics.projection_state AS state
    ON state.projection_name = core.name
 GROUP BY latest.id;
SQL
  )" || projection_state=""
  IFS='|' read -r revision ready_count stale_count <<<"$projection_state"
  if [[ "$revision" =~ ^[1-9][0-9]*$ && "$ready_count" == 6 && "$stale_count" == 0 ]]; then
    pass "all six projections are ready at dataset revision $revision"
  else
    fail "core projections are missing, stale or rebuilding"
  fi
fi

if require_readable "$OUTBOX_PGPASSFILE" "outbox pgpass"; then
  outbox_state="$(
    PGPASSFILE="$OUTBOX_PGPASSFILE" psql "$OUTBOX_DATABASE_URL" \
      --no-psqlrc --set ON_ERROR_STOP=1 --tuples-only --no-align \
      --field-separator='|' <<'SQL'
SELECT count(*),
       coalesce(extract(epoch FROM (transaction_timestamp() - min(occurred_at)))::bigint, 0)
  FROM ops_and_admin.outbox_event
 WHERE published_at IS NULL;
SQL
  )" || outbox_state=""
  IFS='|' read -r pending_count outbox_age <<<"$outbox_state"
  if [[ "$pending_count" =~ ^[0-9]+$ && "$outbox_age" =~ ^[0-9]+$ \
        && "$outbox_age" -le "$MAX_OUTBOX_LAG_SECONDS" ]]; then
    pass "outbox pending=$pending_count oldest_age=${outbox_age}s"
  else
    fail "outbox backlog exceeds ${MAX_OUTBOX_LAG_SECONDS}s"
  fi
fi

if require_readable "$BACKUP_PGPASSFILE" "backup monitor pgpass"; then
  wal_state="$(
    PGPASSFILE="$BACKUP_PGPASSFILE" psql "$BACKUP_MONITOR_DATABASE_URL" \
      --no-psqlrc --set ON_ERROR_STOP=1 --tuples-only --no-align \
      --field-separator='|' <<'SQL'
SELECT coalesce(extract(epoch FROM (transaction_timestamp() - last_archived_time))::bigint, 999999999),
       CASE WHEN last_failed_time IS NOT NULL
                  AND (last_archived_time IS NULL OR last_failed_time > last_archived_time)
            THEN 1 ELSE 0 END
  FROM pg_stat_archiver;
SQL
  )" || wal_state=""
  IFS='|' read -r wal_age last_archive_failed <<<"$wal_state"
  if [[ "$wal_age" =~ ^[0-9]+$ && "$last_archive_failed" == 0 \
        && "$wal_age" -le "$MAX_WAL_ARCHIVE_AGE_SECONDS" ]]; then
    pass "WAL archive age ${wal_age}s meets RPO gate"
  else
    fail "WAL archive is failed or older than ${MAX_WAL_ARCHIVE_AGE_SECONDS}s"
  fi

  replica_state="$(
    PGPASSFILE="$BACKUP_PGPASSFILE" psql "$BACKUP_MONITOR_DATABASE_URL" \
      --no-psqlrc --set ON_ERROR_STOP=1 --tuples-only --no-align \
      --field-separator='|' <<'SQL'
SELECT count(*) FILTER (WHERE state = 'streaming'),
       coalesce(max(extract(epoch FROM replay_lag))::bigint, 0)
  FROM pg_stat_replication;
SQL
  )" || replica_state=""
  IFS='|' read -r streaming_replicas replica_lag <<<"$replica_state"
  if [[ "$streaming_replicas" =~ ^[1-9][0-9]*$ && "$replica_lag" =~ ^[0-9]+$ \
        && "$replica_lag" -le "$MAX_REPLICA_LAG_SECONDS" ]]; then
    pass "streaming replicas=$streaming_replicas max_replay_lag=${replica_lag}s"
  else
    fail "no streaming standby or replay lag exceeds ${MAX_REPLICA_LAG_SECONDS}s"
  fi
fi

disk_percent="$(df --output=pcent "$DATA_FILESYSTEM_PATH" | tail -1 | tr -dc '0-9')"
if [[ "$disk_percent" =~ ^[0-9]+$ && "$disk_percent" -le "$MAX_DISK_PERCENT" ]]; then
  pass "data filesystem usage ${disk_percent}% is below cutover gate"
else
  fail "data filesystem usage exceeds ${MAX_DISK_PERCENT}% or cannot be measured"
fi

if [[ "$mode" == writer-cutover ]]; then
  require_value MIGRATION_SOURCE_NAMESPACE || true
  require_value REVERSE_SYNC_APPROVAL_TICKET || true
  require_value COLLECTOR_PARITY_REPORT || true
  require_value COLLECTOR_PARITY_EVIDENCE_ROOT || true
  require_value COLLECTOR_PARITY_APPROVAL_TICKET || true
  reject_placeholder_value MIGRATION_SOURCE_NAMESPACE || true
  reject_placeholder_value REVERSE_SYNC_APPROVAL_TICKET || true
  reject_placeholder_value COLLECTOR_PARITY_APPROVAL_TICKET || true
  if systemctl is-active --quiet m-ranked-target-projection-publisher.service; then
    pass "continuous projection publisher is active"
  else
    fail "continuous projection publisher is not active"
  fi
  if [[ -n "${COLLECTOR_PARITY_REPORT:-}" \
        && -n "${COLLECTOR_PARITY_EVIDENCE_ROOT:-}" \
        && -n "${COLLECTOR_PARITY_APPROVAL_TICKET:-}" ]]; then
    if [[ -z "$deploy_release_path" ]]; then
      fail "collector parity verifier is blocked by the active release gate"
    elif ! mranked_transition_require_active_file \
        "$deploy_release_path/operations/bin/collector-parity-evidence" \
        operations/bin/collector-parity-evidence true; then
      fail "collector parity verifier is not a protected active-release file"
    else
      check_collector_parity_gate \
        "$COLLECTOR_PARITY_REPORT" \
        "$COLLECTOR_PARITY_EVIDENCE_ROOT" \
        "$deploy_release_path" \
        "$MRANKED_CURRENT_LINK" \
        "$MRANKED_INSTALL_ROOT" \
        "$DEPLOY_REPORT" \
        "$OPERATOR_ID" \
        "$COLLECTOR_PARITY_APPROVAL_TICKET" \
        "${MIGRATION_SOURCE_NAMESPACE:-}" \
        "$COLLECTOR_PARITY_MAX_AGE_SECONDS" || true
    fi
  fi
  if [[ "${COMPATIBILITY_SYNC_READY:-false}" != true ]]; then
    fail "COMPATIBILITY_SYNC_READY is not true"
  fi
  if [[ -z "${REVERSE_SYNC_EXECUTABLE:-}" || ! -x "${REVERSE_SYNC_EXECUTABLE:-/nonexistent}" ]]; then
    fail "tested PG-to-legacy compatibility sync executable is unavailable"
  fi
  if [[ -z "${REVERSE_SYNC_REHEARSAL_REPORT:-}" ]]; then
    fail "REVERSE_SYNC_REHEARSAL_REPORT is not set"
  else
    check_reverse_sync_rehearsal_gate \
      "$REVERSE_SYNC_REHEARSAL_REPORT" \
      "$deploy_release_id" \
      "$deploy_manifest_sha256" \
      "${MIGRATION_SOURCE_NAMESPACE:-}" \
      "${REVERSE_SYNC_APPROVAL_TICKET:-}" \
      "$OPERATOR_ID" \
      "$REVERSE_SYNC_REHEARSAL_MAX_AGE_SECONDS"
  fi
  if (( ROLLBACK_WINDOW_HOURS < 24 )); then
    fail "rollback window must be at least 24 hours"
  else
    pass "rollback window is ${ROLLBACK_WINDOW_HOURS} hours"
  fi
fi

if (( failures > 0 )); then
  echo "preflight failed checks=$failures operator=$OPERATOR_ID ticket=$CHANGE_TICKET" >&2
  exit 1
fi

echo "preflight passed mode=$mode operator=$OPERATOR_ID ticket=$CHANGE_TICKET"
